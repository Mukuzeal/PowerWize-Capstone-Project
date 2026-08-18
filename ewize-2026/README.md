# EnergyWize Solutions — 2026 site

A complete rebuild of e-wizesolutions.com. New information architecture, new
visual language, new interaction model. The only things carried over from the
old site are the brand, the company facts, and the service/program content.

> **This folder is the standalone static build.** The same design also runs
> inside the Flask app — `src/site_bp.py`, `src/site_content.py`,
> `templates/site/`, `static/ewize.css`, `static/ewize.js`. That version is the
> live one: it reads batch dates from the `batches` table and links every
> program to its real registration form. Edit there for the running product;
> edit here only if you still need the detached static deliverable, and keep the
> two content models in sync.

## Running it

The output is plain static HTML. Open `index.html`, or serve the folder:

```
python -m http.server 8000
```

To regenerate after editing content or templates:

```
python build.py
```

`build.py` writes the 15 HTML pages plus `sitemap.xml` and `robots.txt` into
this directory. There is no bundler, no framework, and no runtime dependency —
the browser loads one stylesheet, one script, and one image.

## Layout of the source

| Path | What it is |
|---|---|
| `content.py` | Every word, date, and registration number on the site |
| `build.py` | Components + page composition; renders the HTML |
| `assets/css/ewize.css` | The whole design system |
| `assets/js/ewize.js` | Motion engine (zero dependencies) |
| `assets/img/ewize-seal.png` | Corporate seal |

Facts in `content.py` — DOE registration numbers, 2026 batch dates, phone
numbers — are transcribed from EnergyWize's own published material. Treat them
as source data, not copy to be embellished.

## The design language

**"Instrument."** A tactical-telemetry substrate carrying editorial typography.
The organising idea is an engineering document: hairline rules do the work that
boxes and shadows usually do, and every label is a monospace readout.

**One rule you can see everywhere:** structural zones are square, controls are
round. Sections, tables, spec rows and cards have 90° corners. Buttons, the nav,
and status pips are fully round. Nothing sits in between, so the interface reads
as an instrument panel rather than a template.

**Substrate.** Committed dark (`#071009` — a green-black, never pure black),
with exactly one inversion: schedules render on paper (`#EFEDE6`). That is a
rule, not decoration — timetables are printed documents, so they look printed.

**Colour.** The brand green and gold, extended for a dark ground. `--signal`
(`#35C77C`) is the instrument green and the primary accent; `--amber`
(`#E9A93B`) is secondary; the logo red is reserved for the seal. Neutrals are
green-tinted rather than grey so the palette reads as one family.

**Type.** Two families. Archivo (variable, using its width axis) covers display
and body — width and weight carry the hierarchy contrast that a second display
face would normally provide. JetBrains Mono carries every label, index, code,
and readout.

**Structure.** A 12-column blueprint grid whose rails stay faintly visible down
the whole page, so the composition is legible as a system rather than implied.
Collapses to 4 columns under 900px.

## Motion

All of it is `transform` and `opacity`, driven by `IntersectionObserver` — there
are no scroll listeners. The pieces:

- **Irradiance field** — the hero canvas. A lattice of dots that bulges away
  from the cursor, drifts on a slow wave, and flares about 2% of its points.
  Pauses when off-screen or when the tab is hidden.
- **Line-mask reveals** — display type rises out of a clipped box, staggered.
- **Drawn rules and paths** — section rules scale in from the left; the load
  profile chart draws itself via `stroke-dashoffset`.
- **Sliding nav indicator** — a 2px bar that translates and scales between
  items. It animates a single transform; no layout property moves.
- **Spotlight cards** — pointer position written to CSS custom properties once
  per frame, warming the card's border rather than adding a glow.
- **Magnetic controls** — buttons lean toward the cursor on fine pointers only.
- **Curtain page transitions** — a wipe on internal navigation.

`prefers-reduced-motion` disables the canvas entirely and reduces everything
else to its resolved state.

## Information architecture

The old site listed its services twice on the home page and mixed two unrelated
audiences throughout. The rebuild splits them explicitly.

```
Home        hero → the RA 11285 mandate → two doors → capabilities →
            method → 2026 calendar → registrations → contact
Capabilities  index + 5 detail pages
Programs      index + 5 detail pages, each with its own batch table
Company       about, vision, mission, DOE registrations
Contact       enquiry form + office details
```

Two changes are worth calling out. **The mandate section leads**, because RA
11285 compliance is the actual reason organisations buy this, and the old site
buried it. **The 2026 schedule is real markup** — it was previously trapped in
JPEG posters, so it was invisible to search engines, screen readers, and
copy-paste.

## Accessibility & SEO

Semantic landmarks, a skip link, visible focus rings, labelled form fields with
inline error states, `aria-current` on the active nav item, and an escape-key
handler plus `aria-expanded` on the mobile menu. Every page carries a unique
title, meta description, canonical URL, and Open Graph tags; the home page
carries `Organization` structured data and each program page carries `Course`.

Verified with no horizontal overflow across 10 pages at 360/414/768/1024/1280/1440px.

## Notes for whoever picks this up

- The contact form validates inline but has no backend. Point it at your mail
  handler or a form service; `initForm` in `ewize.js` is where to wire it.
- Social links in `content.py` point at platform roots. Swap in the real
  profile URLs.
- Footer legal links currently resolve to the contact page — replace them when
  the legal notice, privacy policy, and terms pages exist.
- `--sp-section` and `--sp-block` drive the whole vertical rhythm. Change those
  two tokens before touching any individual section's padding.
