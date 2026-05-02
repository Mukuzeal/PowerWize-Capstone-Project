"""
Rule-based Solar PV computation engine for Philippine market conditions.
All monetary values in PHP. No AI used here — deterministic calculations only.
"""

# ── Philippine solar constants ─────────────────────────────────────────────────
ELECTRICITY_RATE      = 14.3496  # PHP/kWh  (Meralco residential avg, 2026)
PEAK_SUN_HOURS        = 5.0     # hrs/day  (Philippine average)
SYSTEM_EFFICIENCY     = 0.78    # combined inverter + temp + wiring losses
PANEL_WATTAGE_W       = 400     # watts per panel (modern monocrystalline)
PANEL_AREA_SQM        = 2.0     # m² per panel including spacing
COST_MIN_PER_KWP      = 55_000  # PHP/kWp installed (min)
COST_MAX_PER_KWP      = 80_000  # PHP/kWp installed (max)
MAINTENANCE_ANNUAL_PCT = 0.005  # 0.5% of system cost per year


def _target_ratio(target_savings: str) -> float:
    return {"100": 1.0, "75": 0.75, "50": 0.50}.get(str(target_savings), 1.0)


def compute(
    kwh_monthly: float | None,
    bill_php: float | None,
    target_savings: str,
    roof_sqm: float | None,
    time_of_use_night_pct: int | None,
    electrical_phase: str,
) -> dict:
    # Resolve kWh from bill if not directly provided
    if not kwh_monthly:
        kwh_monthly = (bill_php or 0) / ELECTRICITY_RATE

    ratio = _target_ratio(target_savings)
    daily_kwh = kwh_monthly / 30.0
    target_daily_kwh = daily_kwh * ratio

    # System size
    system_kw = round(target_daily_kwh / (PEAK_SUN_HOURS * SYSTEM_EFFICIENCY), 2)
    system_kw = max(system_kw, 1.0)

    # Panel count
    panel_count = max(1, round((system_kw * 1000) / PANEL_WATTAGE_W))

    # Cost range
    cost_min = round(system_kw * COST_MIN_PER_KWP)
    cost_max = round(system_kw * COST_MAX_PER_KWP)
    cost_avg = (cost_min + cost_max) / 2

    # Savings
    monthly_savings = round(kwh_monthly * ratio * ELECTRICITY_RATE, 2)
    annual_savings  = monthly_savings * 12

    # ROI (years)
    annual_maintenance = cost_avg * MAINTENANCE_ANNUAL_PCT
    if annual_savings > annual_maintenance:
        roi_years = round(cost_avg / (annual_savings - annual_maintenance), 1)
    else:
        roi_years = None

    # Roof feasibility
    required_sqm = round(panel_count * PANEL_AREA_SQM, 1)
    if roof_sqm:
        ratio_roof = required_sqm / roof_sqm
        if ratio_roof <= 0.80:
            feasibility = "feasible"
        elif ratio_roof <= 1.20:
            feasibility = "limited"
        else:
            feasibility = "unfeasible"
    else:
        feasibility = "unknown"

    # System type recommendation
    night_pct = time_of_use_night_pct or 20
    battery_recommended = night_pct > 25 or target_savings == "100"
    system_type = "hybrid" if battery_recommended else "grid-tie"

    # Three-phase note
    phase_note = "Three-phase supply detected — a three-phase inverter is recommended." if electrical_phase == "three" else ""

    return {
        "kwh_monthly":       round(kwh_monthly, 2),
        "system_size_kw":    system_kw,
        "panel_count":       panel_count,
        "cost_min":          cost_min,
        "cost_max":          cost_max,
        "monthly_savings":   monthly_savings,
        "annual_savings":    round(annual_savings, 2),
        "roi_years":         roi_years,
        "feasibility":       feasibility,
        "required_roof_sqm": required_sqm,
        "system_type":       system_type,
        "battery_recommended": battery_recommended,
        "phase_note":        phase_note,
    }
