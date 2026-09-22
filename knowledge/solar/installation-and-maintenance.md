# Installation and Maintenance

## General installation flow

1. **Consultation and site details** — property type, ownership, electrical phase, consumption, roof area, and goals are gathered (this is what the Solara chat and the solar request form both do).
2. **Site assessment** — a specialist evaluates the roof condition, orientation, shading, structural suitability, and electrical setup in person before anything is finalized. Anything generated before this step (including Solara's estimate) is preliminary, not a final quotation.
3. **Design and proposal/quotation** — system size, equipment, and pricing are finalized based on the site assessment, and reviewed by a specialist before being sent to the customer.
4. **Permitting and utility coordination** — including net metering application to the distribution utility where relevant (see `net-metering-philippines.md`).
5. **Installation** — mounting, wiring, inverter and (if applicable) battery installation, by licensed technicians.
6. **Commissioning and utility sign-off** — the system is tested and, for grid-tied/hybrid systems, connected in coordination with the utility.

TODO: confirm current typical installation timeline before ever stating one to a customer — the existing system prompt already treats this as a non-negotiable ("never invent an installation timeline"), and this file should not undermine that by supplying an unverified figure either.

## Maintenance

- **Panel cleaning:** dust, pollen, and grime reduce output over time; how often cleaning is needed depends on the site's environment (dusty/industrial areas need it more often than others).
- **Inverter monitoring:** most modern inverters report performance data; a sudden drop in output is usually the first sign of a fault worth investigating (a failed string, a shading change, an inverter fault).
- **Wind/typhoon resilience:** mounting has to be rated for the local wind exposure — this matters across most of the Philippines, and installations should be designed to the applicable PAGASA wind zone rather than a generic assumption.
- **Battery maintenance (where applicable):** batteries have their own monitoring needs and a finite cycle life; see `batteries.md`.

## Smart monitoring

Real-time monitoring lets performance be verified against expectation rather than assumed — useful for catching a developing fault (partial shading from new construction, a degrading panel, an inverter issue) before it meaningfully affects output.

## Safety

Unsafe DIY high-voltage work, tampering with or bypassing a meter, or circumventing utility/permit requirements are all firmly out of scope — that work needs a licensed electrician or has to go through the distribution utility properly.
