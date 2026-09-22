# Solar Panels

## Panel types

- **Monocrystalline:** made from a single silicon crystal, the most space-efficient and highest-efficiency common panel type, generally the default for residential and commercial roofs where space is at a premium. Typically the most expensive per-panel, but the best output per square meter.
- **Polycrystalline:** made from multiple silicon fragments melted together; historically cheaper but slightly less efficient per square meter than monocrystalline. Less common in new residential installs now that monocrystalline pricing has come down.
- **Thin-film:** flexible, lightweight, tolerant of partial shading and high heat, but noticeably lower efficiency per square meter — needs much more roof area for the same output, so it's a poor fit where roof space is the constraint. Sometimes used for specialty applications (curved surfaces, portable systems) rather than standard rooftop installs.

## What "wattage" means

A panel's wattage rating (e.g. its nameplate figure) is its rated output under standardized lab test conditions (full, direct sunlight, specific temperature) — actual real-world output is usually somewhat lower and varies through the day and year with weather and sun angle. EnergyWize's sizing engine uses a specific wattage assumption for its residential panel calculations; state that number only when it's supplied in a CALCULATIONS block, never as a general fact.

## Durability and degradation

Panels are built to withstand years of outdoor exposure and typically carry a manufacturer performance warranty guaranteeing output stays above a defined percentage of the original rating for a set number of years, with output declining gradually (a small percentage per year) rather than dropping suddenly.

## Warranty

Solar panel warranties are divided into product warranties, which cover physical defects and hardware failures for 12 to 25 years, and performance warranties, which guarantee long-term power output over 25 to 30 years. Because solar panels naturally degrade, performance warranties account for an expected annual degradation rate of up to 1% (often lower, around 0.4% to 0.55% on premium modules), ensuring the total power retention stays above roughly 84% to 87.4% by Year 25. Although product warranties cover a shorter duration, they remain critical for handling physical hardware replacements and environmental damage if a panel fails completely.

## Mounting and wind resistance

Panels need to be mounted at a proper tilt and securely fastened for wind loads — this matters especially in a typhoon-prone country. Mounting should account for the local PAGASA wind zone rating; see `installation-and-maintenance.md`.

## Choosing panel count and roof fit

How many panels a system needs, and whether they fit the available roof, is a computed result (from consumption, target savings, and roof area), not a general fact — see `system-sizing.md` and rely on the CALCULATIONS block for any specific customer.
