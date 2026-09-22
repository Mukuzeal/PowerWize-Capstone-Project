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

Solar isn't the right fit for every property. Common cases EnergyWize flags as marginal or unfavorable during consultation: a heavily shaded roof (trees, taller neighboring buildings, or other structures blocking sun for most of the day, stretching payback well beyond what's reasonable), very low existing electricity consumption (less bill to offset, so a small system's upfront cost takes longer to recover), planning to move or sell soon (may not stay long enough to recover the upfront cost through savings), no ownership or authority to modify the roof (renters, or owners without clear authority over a shared or heritage-restricted building), and a roof in poor or end-of-life condition (should generally be replaced before or alongside installation, not have panels mounted on top of it). TODO: verify this list against EnergyWize's actual consultation screening criteria — the items above are the commonly-cited PV go/no-go factors, not yet confirmed as EnergyWize's specific checklist.

None of this is a hard rule — the EnergyWize team makes the actual call during consultation based on the property's specifics, and a "marginal" case can still make sense depending on what the customer is trying to achieve (e.g. outage backup, not just bill savings).

## Scope limits

Very large systems (roughly industrial scale) and industrial-establishment sites need a full engineering site assessment rather than the standard sizing approach — EnergyWize's estimate for those is explicitly flagged as indicative only, not a substitute for that assessment.

## What this file deliberately does not say

No specific system size, panel count, cost, or savings figure belongs here — those are only ever correct for one customer's actual inputs, computed live. If a customer asks "how big a system would I need," the answer comes from the CALCULATIONS block (built from their actual consumption), not from this document.
