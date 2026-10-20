# System Sizing — How It Works

## The general idea

A solar system is sized to produce roughly as much energy as the property needs, adjusted for how much of the bill the customer wants offset (their target savings percentage) and how much roof area is actually available. Bigger consumption or a higher savings target calls for a larger array; limited roof space caps how large a system can practically go.

## What sizing depends on

- **Monthly electricity consumption** (in kWh, or derived from a peso bill amount) — the starting point for everything else.
- **Target savings percentage** — 100% aims to offset the whole bill, 75% or 50% aim for a smaller array and lower upfront cost.
- **Available roof area** — determines whether the ideal array actually fits; a shortfall is flagged as limited or unfeasible roof space rather than silently downsized.
- **Electrical phase** (single vs three-phase) — affects inverter selection; three-phase supply typically points to a three-phase inverter, common for commercial/industrial loads.
- **Grid connection type** — grid-tied, hybrid, or off-grid sizing logic differs meaningfully; see `grid-tied-vs-off-grid-vs-hybrid.md`. Off-grid systems in particular are deliberately oversized because there's no grid to fall back on for a shortfall, and need battery storage sized for at least a day of autonomous operation.
- **Night-time usage share** — a property that uses a lot of power after sunset benefits more from battery storage, since a plain grid-tied array only generates during daylight.

## Panels, in general terms

Residential systems are typically built from monocrystalline panels (see `panels.md` for the tradeoffs against other panel types). The specific wattage-per-panel assumption EnergyWize sizes against is a configured value inside the sizing engine, not a fixed industry number — don't state a specific watt figure unless it's supplied in a CALCULATIONS block.

## When solar may not be cost-effective

Solar isn't the right fit for every property. EnergyWize screens for a handful of concerns during initial consultation; a site triggering one of these is flagged as marginal, unfeasible, or out of scope — numbers for any of these, where they matter at all, come from the CALCULATIONS block or `solar_engine.py`, never stated here as a fixed figure:

- **Extreme shading** — significant shading from dense foliage, taller neighboring buildings, or structural obstructions that blocks a large share of peak daylight hours stretches the payback period well beyond what's reasonable.
- **Low consumption** — households with very light monthly electricity usage may find a system doesn't pay for itself within a reasonable timeframe, since the upfront cost takes too long to recover against a small bill. This concern is mainly relevant to households; a commercial or industrial property using that little electricity is uncommon in practice, so sizing for those properties proceeds normally.
- **Property tenancy or ownership disputes** — renters, short-term leaseholders, or building units lacking a clean title, a notarized long-term lessor consent form, or clear corporate/HOA structural-modification clearance generally can't proceed regardless of the economics.
- **Imminent relocation plans** — customers planning to sell, transfer, or move away from the property in the near term may not stay long enough to recover the upfront cost through savings, even though the system itself keeps working for whoever owns the property next.

None of this is a hard rule applied by a formula — the EnergyWize team makes the actual call during consultation based on the property's specifics.

## Scope limits

Very large systems (roughly industrial scale) and industrial-establishment sites need a full engineering site assessment rather than the standard sizing approach — EnergyWize's estimate for those is explicitly flagged as indicative only, not a substitute for that assessment.

## What this file deliberately does not say

No specific system size, panel count, cost, or savings figure belongs here — those are only ever correct for one customer's actual inputs, computed live. If a customer asks "how big a system would I need," the answer comes from the CALCULATIONS block (built from their actual consumption), not from this document.
