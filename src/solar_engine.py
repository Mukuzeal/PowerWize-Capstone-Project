import math

# ── Philippine solar constants ────────────────────────────────
ELECTRICITY_RATE       = 14.3496   # PHP/kWh
PEAK_SUN_HOURS         = 5.0
SYSTEM_EFFICIENCY      = 0.78
PANEL_WATTAGE_W        = 400
PANEL_AREA_SQM         = 2.0
COST_MIN_PER_KWP       = 55_000
COST_MAX_PER_KWP       = 80_000
MAINTENANCE_ANNUAL_PCT = 0.005


def _target_ratio(target_savings: str) -> float:
    return {
        "100": 1.0,
        "75": 0.75,
        "50": 0.50
    }.get(str(target_savings), 1.0)


def compute(
    kwh_monthly: float | None,
    bill_php: float | None,
    target_savings: str,
    roof_sqm: float | None,
    time_of_use_night_pct: int | None,
    electrical_phase: str,
) -> dict:

    bill_php = float(bill_php or 0)
    kwh_monthly = float(kwh_monthly or 0)

    # derive from bill if kWh missing or suspiciously low
    if bill_php > 0:
        estimated_kwh = bill_php / ELECTRICITY_RATE

        if kwh_monthly <= 0 or kwh_monthly < 50:
            kwh_monthly = estimated_kwh

        # auto-correct if user entered unrealistic value
        elif abs(kwh_monthly - estimated_kwh) > (estimated_kwh * 0.60):
            kwh_monthly = estimated_kwh

    if kwh_monthly <= 0:
        raise ValueError("Monthly consumption or bill is required.")

    ratio = _target_ratio(target_savings)

    daily_kwh = kwh_monthly / 30
    target_daily_kwh = daily_kwh * ratio

    # system size
    system_kw = target_daily_kwh / (PEAK_SUN_HOURS * SYSTEM_EFFICIENCY)
    system_kw = max(round(system_kw, 2), 1.0)

    # panel count (always round up)
    panel_count = max(1, math.ceil((system_kw * 1000) / PANEL_WATTAGE_W))

    # roof
    required_sqm = round(panel_count * PANEL_AREA_SQM, 1)

    if roof_sqm:
        roof_sqm = float(roof_sqm)
        ratio_roof = required_sqm / roof_sqm

        if ratio_roof <= 0.80:
            feasibility = "feasible"
        elif ratio_roof <= 1.20:
            feasibility = "limited"
        else:
            feasibility = "unfeasible"
    else:
        feasibility = "unknown"

    # cost
    cost_min = round(system_kw * COST_MIN_PER_KWP)
    cost_max = round(system_kw * COST_MAX_PER_KWP)
    cost_avg = (cost_min + cost_max) / 2

    # savings
    monthly_savings = round(kwh_monthly * ratio * ELECTRICITY_RATE, 2)
    annual_savings = monthly_savings * 12

    # roi
    annual_maintenance = cost_avg * MAINTENANCE_ANNUAL_PCT

    roi_years = None
    if annual_savings > annual_maintenance:
        roi_years = round(
            cost_avg / (annual_savings - annual_maintenance),
            1
        )

    # system type
    night_pct = int(time_of_use_night_pct or 20)

    battery_recommended = (
        night_pct > 25 or
        target_savings == "100"
    )

    system_type = "hybrid" if battery_recommended else "grid-tie"

    phase_note = ""
    if electrical_phase == "three":
        phase_note = (
            "Three-phase supply detected — "
            "three-phase inverter recommended."
        )

    return {
        "kwh_monthly": round(kwh_monthly, 2),
        "system_size_kw": system_kw,
        "panel_count": panel_count,
        "cost_min": cost_min,
        "cost_max": cost_max,
        "monthly_savings": monthly_savings,
        "annual_savings": round(annual_savings, 2),
        "roi_years": roi_years,
        "feasibility": feasibility,
        "required_roof_sqm": required_sqm,
        "system_type": system_type,
        "battery_recommended": battery_recommended,
        "phase_note": phase_note,
    }