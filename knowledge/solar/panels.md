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

TODO: this section is a placeholder — fill in with verified figures before relying on it. Distinguish **performance warranty** (guaranteed output stays above X% of rated capacity through year Y) from **product/materials warranty** (defects, workmanship, shorter term) — they're different numbers and customers sometimes conflate them. Source typical ranges from actual manufacturer datasheets for the brands EnergyWize installs, not from memory or industry-generic figures, and note that exact terms depend on the specific brand/model installed for a given customer.

## Mounting and wind resistance

Panels need to be mounted at a proper tilt and securely fastened for wind loads — this matters especially in a typhoon-prone country. Mounting should account for the local PAGASA wind zone rating; see `installation-and-maintenance.md`.

## Choosing panel count and roof fit

How many panels a system needs, and whether they fit the available roof, is a computed result (from consumption, target savings, and roof area), not a general fact — see `system-sizing.md` and rely on the CALCULATIONS block for any specific customer.
