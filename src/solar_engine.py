import math

# ── Philippine solar constants ────────────────────────────────
# VERIFIED: Updated against the published September 2026 Meralco residential rate.
# The previous constant (14.3496) was the record high from April 2026.
ELECTRICITY_RATE       = 14.7424   # PHP/kWh
PEAK_SUN_HOURS         = 5.0
SYSTEM_EFFICIENCY      = 0.78
PANEL_WATTAGE_W        = 400
PANEL_AREA_SQM         = 2.0
COST_MIN_PER_KWP       = 45_000   # client quotes ~P50k/kWp installed; range brackets it
COST_MAX_PER_KWP       = 55_000
MAINTENANCE_ANNUAL_PCT = 0.005

# ── Off-grid (no utility connection) ────────────────────────────
OFFGRID_DESIGN_MARGIN    = 1.3     # oversize panels — no grid to fall back on for shortfalls
AUTONOMY_DAYS            = 1       # days the battery must cover alone
BATTERY_DOD              = 0.8     # usable fraction of rated battery capacity
BATTERY_COST_MIN_PER_KWH = 20_000  # PHP/kWh, LiFePO4 bracket
BATTERY_COST_MAX_PER_KWH = 28_000

# ── Scope limit ──────────────────────────────────────────────────
INDUSTRIAL_SCALE_KW_THRESHOLD = 100  # above this, needs a full engineering assessment

# ── PV cost-effectiveness thresholds (residential only) ──────────
# Source for 400: guidance from a professional client in the solar field.
# 350 and 450 are the team's own tolerance margins, not from the
# professional — 350 gives a borderline band instead of a flat no right at
# the cutoff, 450 is how far above it a "worthwhile" verdict stops needing
# the "close to the minimum" caveat at all.
#
# Residential only. Commercial/industrial are exempt from this check
# entirely — not because a different (e.g. higher) number applies to them,
# but because consumption this low is rare for a commercial/industrial
# account in the first place (same professional's guidance), so the check
# simply doesn't apply. See assess_suitability() below.
MIN_KWH_RESIDENTIAL             = 400  # worthwhile at or above this
MIN_KWH_RESIDENTIAL_BORDERLINE  = 350  # borderline from here up to just below MIN_KWH_RESIDENTIAL
MIN_KWH_RESIDENTIAL_COMFORTABLE = 450  # below this, a worthwhile verdict still carries the "close to minimum" note


def assess_suitability(kwh_monthly: float | None, property_type: str | None) -> dict:
    """Deterministic cost-effectiveness verdict — no AI involved, same
    "numbers never come from the model" principle as compute() itself.

    kwh_monthly: the customer's resolved monthly consumption. If only a
    bill amount is known, the CALLER converts it via ELECTRICITY_RATE
    before calling this — kept out of here so these bands stay expressed in
    kWh (actual usage), independent of whatever the rate TODO resolves to.
    A rate change shifts which band a given PESO bill lands in, never the
    bands themselves.

    property_type: "residential" / "commercial" / "industrial", or
    None/"" if not collected yet. Normalized (stripped + lowercased) here
    defensively — every current write path (chat extraction's schema
    enum, the form's radio buttons) already only ever produces one of
    these three lowercase values, confirmed directly against the live DB
    too, but the DB column itself has no CHECK constraint enforcing that,
    so this doesn't assume it stays that way forever.

    Returns {"verdict", "kwh", "note"}:
      verdict: "unknown_type"   — property_type not given (or kwh_monthly
                                   isn't either, though callers should
                                   normally already have it by the time
                                   they call this).
               "not_applicable" — commercial/industrial; the minimum-
                                   consumption check doesn't apply to them.
               "not_worth" / "borderline" / "worthwhile" — residential only.
      note: True only for "worthwhile" in the 400–449 kWh band.
    """
    ptype = (property_type or "").strip().lower()
    if not ptype:
        return {"verdict": "unknown_type", "kwh": kwh_monthly, "note": False}
    if ptype != "residential":
        return {"verdict": "not_applicable", "kwh": kwh_monthly, "note": False}
    if kwh_monthly is None:
        return {"verdict": "unknown_type", "kwh": None, "note": False}

    kwh = float(kwh_monthly)
    if kwh < MIN_KWH_RESIDENTIAL_BORDERLINE:
        return {"verdict": "not_worth", "kwh": kwh, "note": False}
    if kwh < MIN_KWH_RESIDENTIAL:
        return {"verdict": "borderline", "kwh": kwh, "note": False}
    if kwh < MIN_KWH_RESIDENTIAL_COMFORTABLE:
        return {"verdict": "worthwhile", "kwh": kwh, "note": True}
    return {"verdict": "worthwhile", "kwh": kwh, "note": False}


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
    establishment_type: str = "residential",
    grid_connection: str = "grid_tie",
) -> dict:

    off_grid = grid_connection == "off_grid"

    bill_php = float(bill_php or 0)
    kwh_monthly = float(kwh_monthly or 0)

    # An off-grid site has no utility bill to derive consumption from —
    # only the entered kWh figure is meaningful.
    if not off_grid and bill_php > 0:
        estimated_kwh = bill_php / ELECTRICITY_RATE

        if kwh_monthly <= 0 or kwh_monthly < 50:
            kwh_monthly = estimated_kwh

        # auto-correct if user entered unrealistic value
        elif abs(kwh_monthly - estimated_kwh) > (estimated_kwh * 0.60):
            kwh_monthly = estimated_kwh

    if kwh_monthly <= 0:
        raise ValueError("Monthly consumption or bill is required.")

    # Off-grid must cover the full load — there's no grid to draw the rest from.
    ratio = 1.0 if off_grid else _target_ratio(target_savings)

    daily_kwh = kwh_monthly / 30
    target_daily_kwh = daily_kwh * ratio

    # system size
    design_margin = OFFGRID_DESIGN_MARGIN if off_grid else 1.0
    system_kw = (target_daily_kwh * design_margin) / (PEAK_SUN_HOURS * SYSTEM_EFFICIENCY)
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

    # energy yield — what the actual sized system generates (post rounding/
    # margin), not just the raw consumption target it was sized against
    daily_yield_kwh = round(system_kw * PEAK_SUN_HOURS * SYSTEM_EFFICIENCY, 2)
    estimated_monthly_yield_kwh = round(daily_yield_kwh * 30, 1)
    estimated_annual_yield_kwh  = round(daily_yield_kwh * 365, 1)

    # cost
    cost_min = round(system_kw * COST_MIN_PER_KWP)
    cost_max = round(system_kw * COST_MAX_PER_KWP)

    battery_kwh_capacity = None
    if off_grid:
        battery_kwh_capacity = round((target_daily_kwh * AUTONOMY_DAYS) / BATTERY_DOD, 1)
        cost_min += round(battery_kwh_capacity * BATTERY_COST_MIN_PER_KWH)
        cost_max += round(battery_kwh_capacity * BATTERY_COST_MAX_PER_KWH)

    cost_avg = (cost_min + cost_max) / 2

    # savings — meaningless off-grid, since there's no utility bill to offset
    if off_grid:
        monthly_savings = 0.0
        annual_savings  = 0.0
        roi_years       = None
    else:
        monthly_savings = round(kwh_monthly * ratio * ELECTRICITY_RATE, 2)
        annual_savings  = monthly_savings * 12

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
        off_grid or
        night_pct > 25 or
        target_savings == "100"
    )

    system_type = "off-grid" if off_grid else ("hybrid" if battery_recommended else "grid-tie")

    phase_note = ""
    if electrical_phase == "three":
        phase_note = (
            "Three-phase supply detected — "
            "three-phase inverter recommended."
        )

    # out-of-scope — industrial sites and any system beyond the residential/
    # commercial scale this tool is calibrated for need a full site
    # assessment, not this simplified formula. Still computed and returned
    # (indicative only) rather than blocked outright, but clearly flagged.
    out_of_scope = establishment_type == "industrial" or system_kw > INDUSTRIAL_SCALE_KW_THRESHOLD
    out_of_scope_reason = None
    if establishment_type == "industrial":
        out_of_scope_reason = (
            "Industrial sites need a full engineering site assessment — "
            "this figure is indicative only, not a substitute for one."
        )
    elif out_of_scope:
        out_of_scope_reason = (
            f"A {system_kw:g} kWp system exceeds this tool's supported scale "
            f"(residential/commercial, up to {INDUSTRIAL_SCALE_KW_THRESHOLD} kWp) "
            "and needs advanced BESS engineering beyond this estimate."
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
        "estimated_monthly_yield_kwh": estimated_monthly_yield_kwh,
        "estimated_annual_yield_kwh": estimated_annual_yield_kwh,
        "grid_connection": grid_connection,
        "battery_kwh_capacity": battery_kwh_capacity,
        "out_of_scope": out_of_scope,
        "out_of_scope_reason": out_of_scope_reason,
        # Echoes back the *effective* target-savings percentage actually
        # used (post _target_ratio() normalization, not the raw input) so
        # callers can state the assumption behind monthly_savings/roi_years
        # inline instead of silently defaulting to 100% and letting the
        # number read as an unconditional promise. None off-grid, where
        # there's no bill to offset a percentage of.
        "target_savings_pct": None if off_grid else round(ratio * 100),
    }
