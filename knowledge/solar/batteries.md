# Battery Storage

## What batteries are for

Solar panels only generate while the sun is up. Without storage, a grid-tied system simply draws from the utility grid whenever demand exceeds what the panels are producing at that moment — perfectly fine for many customers, but it means no backup power during a grid outage, and no way to "save" daytime surplus for night-time use beyond what net metering credits provide.

## Common chemistry

Modern residential/commercial solar battery storage is typically LiFePO4 (lithium iron phosphate) — valued for cycle life, thermal stability, and safety relative to older lithium chemistries. 

## Depth of discharge and autonomy

A battery's usable capacity is less than its rated capacity — batteries are generally not run all the way to empty, both for longevity and because most have a manufacturer-recommended usable "depth of discharge." "Autonomy" describes how many days a battery bank can cover a property's essential load without any solar input or grid draw at all — relevant mainly for off-grid design, where the battery has to carry the property through cloudy stretches with zero backup. The specific depth-of-discharge and autonomy assumptions EnergyWize's sizing engine uses are configured values, not general facts — don't state a number unless it's in a CALCULATIONS block.

## When battery storage tends to make sense

- The property is **off-grid** — batteries aren't optional there, they're the only overnight power source.
- A meaningful share of the property's usage happens **at night**, after solar generation has stopped for the day.
- The customer's **target savings is 100%** of their bill — without storage, a grid-tied system still can't offset the portion of usage that happens outside sunlight hours as cleanly.
- The area has **frequent brownouts or unreliable grid supply** — a battery-backed (hybrid) system keeps critical loads running through an outage that would otherwise take a plain grid-tied system down with the grid.

## What this file doesn't say

Whether a specific customer should add a battery, and how large it should be, is a computed recommendation from their actual profile (grid connection type, night usage share, target savings) — see `grid-tied-vs-off-grid-vs-hybrid.md` and the CALCULATIONS block for any specific customer.
