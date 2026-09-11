# -*- coding: utf-8 -*-
"""
Static site generator for EnergyWize Solutions.

    python build.py

Writes plain HTML next to assets/. No runtime dependencies, no framework —
the output is the deliverable, this file is just how it stays consistent.
"""

import html
import json
import os
import re

from content import (
    SITE, REGISTRATIONS, CREDENTIALS, NAV,
    CAPABILITIES, PROGRAMS, SCHEDULES,
    HOME, ABOUT, CONTACT,
    PRIVACY_POLICY, LEGAL_NOTICE, TERMS_CONDITIONS,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
CSS_VER = "1"

# ===========================================================================
# ICONS — ultra-light strokes, one geometry language
# ===========================================================================
def _svg(body, box="0 0 24 24", w="1.25"):
    # Explicit width/height matter: an inline SVG with only a viewBox has no
    # intrinsic size, so before the stylesheet applies it balloons to fill its
    # container. Sizing it in the markup keeps a slow first paint harmless.
    side = box.split()[-1]
    return (
        f'<svg viewBox="{box}" width="{side}" height="{side}" fill="none" '
        f'stroke="currentColor" stroke-width="{w}" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )


ICONS = {
    "audit": _svg(
        '<path d="M3 20.5h18"/><path d="M6 20.5V13"/><path d="M10 20.5V9.5"/>'
        '<path d="M14 20.5v-4.5"/><circle cx="17.6" cy="7.4" r="3.4"/>'
        '<path d="m20.1 9.9 2.4 2.4"/>'
    ),
    "ems": _svg(
        '<rect x="2.5" y="4" width="19" height="12.5"/><path d="M8 20.5h8"/>'
        '<path d="M12 16.5v4"/><path d="M6 10.2h2.6L10.2 6.6l2.2 7 1.6-3.4H18"/>'
    ),
    "solar": _svg(
        '<path d="M2.6 16.4h18.8l-2.3-8.2H4.9z"/><path d="M8.6 8.2 7 16.4"/>'
        '<path d="M15.4 8.2 17 16.4"/><path d="M4.1 12.3h15.8"/>'
        '<path d="M8 20.4h8"/><path d="M12 16.4v4"/>'
        '<circle cx="12" cy="3.6" r="1.5"/><path d="M12 .8v.7M8.9 1.9l.4.6M15.1 1.9l-.4.6"/>'
    ),
    "mepf": _svg(
        '<path d="M2.5 7.5h6.2a2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h8.8"/>'
        '<circle cx="10.7" cy="7.5" r="2.1"/><path d="M10.7 5.4V2.9"/>'
        '<path d="M17.4 2.9v4.4M15.2 5.1h4.4"/>'
        '<path d="M21.5 13.4c0 1.5-1 2.6-2.1 2.6s-2.1-1.1-2.1-2.6 2.1-3.7 2.1-3.7 2.1 2.2 2.1 3.7z"/>'
    ),
    "training": _svg(
        '<path d="M2.6 7 12 3.2 21.4 7 12 10.8z"/>'
        '<path d="M6.6 8.6v5c0 1.9 2.4 3.3 5.4 3.3s5.4-1.4 5.4-3.3v-5"/>'
        '<path d="M21.4 7v5.6"/><path d="M21.4 15.6v3.2"/>'
    ),
    "arrow": _svg('<path d="M4.5 11.5 11.5 4.5"/><path d="M5.6 4.5h5.9v5.9"/>', box="0 0 16 16", w="1.6"),
    "facebook": _svg('<path d="M13.5 6.5h2.2V3.6h-2.6c-2.2 0-3.6 1.4-3.6 3.6v2H7.2v3h2.3v8.2h3.1v-8.2h2.5l.5-3h-3v-1.5c0-.7.3-1.2.9-1.2z"/>', w="1.3"),
    "instagram": _svg('<rect x="3.2" y="3.2" width="17.6" height="17.6" rx="5"/><circle cx="12" cy="12" r="4.1"/><circle cx="17.1" cy="6.9" r=".9"/>', w="1.3"),
    "youtube": _svg('<rect x="2.4" y="5.6" width="19.2" height="12.8" rx="4"/><path d="m10.2 9.4 5.2 2.6-5.2 2.6z"/>', w="1.3"),
    "x": _svg('<path d="m4 4 7.2 9.4L4.4 20"/><path d="m20 20-7.2-9.4L19.6 4"/>', w="1.3"),
    "linkedin": _svg('<rect x="3.2" y="3.2" width="17.6" height="17.6"/><path d="M7.4 10.4v6.6M7.4 7.4v.1"/><path d="M11.6 17v-6.6M11.6 13.2c0-1.6 1-2.8 2.5-2.8s2.5 1.2 2.5 2.8V17"/>', w="1.3"),
}


# ===========================================================================
# SMALL HELPERS
# ===========================================================================
def e(t):
    return html.escape(str(t), quote=True)


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", str(t).lower()).strip("-")


def btn(label, href, kind="", magnetic=True, icon="arrow"):
    cls = "btn" + (f" {kind}" if kind else "")
    mag = ' data-magnetic' if magnetic else ""
    return (
        f'<a class="{cls}" href="{e(href)}"{mag}>'
        f'<span class="btn__label">{e(label)}</span>'
        f'<span class="btn__pip" aria-hidden="true">{ICONS[icon]}</span></a>'
    )


def tlink(label, href):
    return (
        f'<a class="tlink" href="{e(href)}"><span>{e(label)}</span>'
        f'{ICONS["arrow"]}</a>'
    )


def lines(items, cls="display display--hero", underline=None):
    """Mask-revealed display type, one masked line per string."""
    out = []
    for i, ln in enumerate(items):
        inner = e(ln)
        if underline is not None and i == underline:
            inner = f'<span class="ul-draw">{inner}</span>'
        out.append(f'<span class="reveal-line" style="--i:{i}"><span>{inner}</span></span>')
    return f'<span class="{cls}">' + "".join(out) + "</span>"


def cap_card(c, wide=False, side=None, blurb_key="blurb"):
    """One capability tile. The wide variant carries a second column so the
    full-width slot in the bento never reads as a dead slab."""
    specs = "".join(f'<span class="mono">{e(s)}</span>' for s in c.get("specs", []))
    main = f"""<p class="cap__no">{e(c["no"])}</p>
      <div class="cap__ico">{ICONS[c["icon"]]}</div>
      <h3 class="d3"><a class="stretch" href="{c["slug"]}.html">{e(c["title"])}</a></h3>
      <p>{e(c[blurb_key])}</p>
      {f'<div class="cap__spec">{specs}</div>' if specs else ""}"""

    if not wide:
        return f"""<article class="cap" data-reveal>
      <span class="cap__go" aria-hidden="true">{ICONS["arrow"]}</span>
      {main}
    </article>"""

    items = "".join(
        f'<li><a href="{e(href)}"><b>{e(code)}</b><span>{e(label)}</span></a></li>'
        for code, label, href in (side or [])
    )
    return f"""<article class="cap cap--wide" data-reveal>
      <div class="cap__main">
        <span class="cap__go" aria-hidden="true">{ICONS["arrow"]}</span>
        {main}
      </div>
      <div class="cap__side">
        <p class="mono mono--fg">Programs under this line</p>
        <ul>{items}</ul>
      </div>
    </article>"""


PROGRAM_SIDE = [(p["code"], p["title"], p["slug"] + ".html") for p in PROGRAMS]


def shead(no, label, title_html, aside_html=""):
    return f"""<header class="shead" data-reveal-group>
  <div class="shead__idx" data-reveal><b>{e(no)}</b><span>{e(label)}</span></div>
  <div class="shead__title" data-reveal>{title_html}</div>
  <div class="shead__aside" data-reveal>{aside_html}</div>
</header>"""


def rule():
    return '<div class="rule" data-reveal></div>'


def sched_table(key, caption=True):
    s = SCHEDULES[key]
    head = "".join(f"<th scope=\"col\">{e(c)}</th>" for c in s["cols"])
    body = "".join(
        "<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>"
        for row in s["rows"]
    )
    cap = f'<caption class="mono">{e(s["note"])}</caption>' if caption else ""
    meta = "" if s.get("meta_last") is False else " sched--meta"
    return f"""<div class="sched__wrap" data-reveal>
  <table class="sched{meta}">{cap}
    <thead><tr>{head}</tr></thead>
    <tbody>{body}</tbody>
  </table>
</div>"""


# ===========================================================================
# CHROME
# ===========================================================================
def nav_html(active):
    items = "".join(
        f'<a class="nav__item" href="{e(href)}"'
        + (' aria-current="page"' if href == active else "")
        + f">{e(label)}</a>"
        for label, href in NAV
    )
    return f"""<nav class="nav" aria-label="Primary">
  <a class="nav__brand" href="index.html">
    <span class="nav__seal"><img src="assets/img/ewize-seal.png" alt="" width="64" height="64"></span>
    <span class="nav__word"><b>ENERGYWIZE</b><span>Solutions</span></span>
  </a>
  <div class="nav__rail">
    <span class="nav__ind" aria-hidden="true"></span>
    {items}
    <a class="nav__item nav__cta" href="contact.html" style="color:var(--signal)">Contact</a>
  </div>
  <button class="nav__burger" type="button" aria-expanded="false" aria-controls="menu" aria-label="Open menu">
    <i></i><i></i><i></i>
  </button>
</nav>"""


def menu_html():
    primary = "".join(
        f'<li style="--i:{i}"><a href="{e(href)}">{e(label)}</a></li>'
        for i, (label, href) in enumerate(NAV + [("Contact", "contact.html")])
    )
    caps = "".join(
        f'<li style="--i:{i}"><a href="{c["slug"]}.html">{e(c["title"])}</a></li>'
        for i, c in enumerate(CAPABILITIES)
    )
    return f"""<div class="menu" id="menu" aria-hidden="true">
  <div class="shell">
    <div class="menu__group">
      <p class="mono menu__label">Navigate</p>
      <ul class="menu__list">{primary}</ul>
    </div>
    <div class="menu__group">
      <p class="mono menu__label">Capabilities</p>
      <ul class="menu__list menu__list--sub">{caps}</ul>
    </div>
    <div class="menu__foot">
      <p class="mono">{e(SITE["phones"][3])}</p>
      <p class="mono">{e(SITE["emails"][0][1])}</p>
      <p class="mono">Makati · NCR</p>
    </div>
  </div>
</div>"""


def footer_html():
    cap_links = "".join(
        f'<li><a href="{c["slug"]}.html">{e(c["title"])}</a></li>' for c in CAPABILITIES
    )
    prog_links = "".join(
        f'<li><a href="{p["slug"]}.html">{e(p["title"])}</a></li>' for p in PROGRAMS
    )
    social = "".join(
        f'<a href="{e(url)}" aria-label="{e(name)}" rel="noopener" target="_blank">{ICONS[ic]}</a>'
        for name, url, ic in SITE["social"]
    )
    addr = "<br>".join(e(l) for l in SITE["address_lines"])
    return f"""<footer class="foot">
  <div class="shell">
    <div class="foot__grid">
      <div>
        <div class="foot__lock">
          <span class="foot__seal"><img src="assets/img/ewize-seal.png" alt="{e(SITE['legal'])} seal" width="96" height="96"></span>
          <div>
            <p class="d4">{e(SITE["legal"])}</p>
            <p class="mono" style="margin-top:.5rem">{e(SITE["tagline"])}</p>
          </div>
        </div>
        <address style="font-style:normal;margin-top:1.75rem;color:var(--fg-dim);font-size:.9rem;line-height:1.7">{addr}</address>
        <div class="social">{social}</div>
      </div>
      <div class="foot__col">
        <h4 class="mono mono--fg">Capabilities</h4>
        <ul>{cap_links}</ul>
      </div>
      <div class="foot__col">
        <h4 class="mono mono--fg">Programs</h4>
        <ul>{prog_links}</ul>
      </div>
      <div class="foot__col">
        <h4 class="mono mono--fg">Contact</h4>
        <ul>
          <li><a href="mailto:{e(SITE["emails"][0][1])}">{e(SITE["emails"][0][1])}</a></li>
          <li><a href="mailto:{e(SITE["emails"][1][1])}">{e(SITE["emails"][1][1])}</a></li>
          <li><a href="tel:{e(SITE["phones"][3].replace(" ", ""))}">{e(SITE["phones"][3])}</a></li>
          <li><a href="tel:{e(SITE["phones"][1].replace(" ", ""))}">{e(SITE["phones"][1])}</a></li>
          <li><a href="about.html">Company</a></li>
          <li><a href="contact.html">Enquiries</a></li>
        </ul>
      </div>
    </div>
    <p class="foot__word" aria-hidden="true">ENERGYWIZE</p>
    <div class="foot__legal">
      <p class="mono">© 2026 {e(SITE["legal"])} · All rights reserved</p>
      <nav aria-label="Legal">
        <a class="mono" href="legal-notice.html">Legal notice</a>
        <a class="mono" href="privacy-policy.html">Privacy policy</a>
        <a class="mono" href="terms-and-conditions.html">Terms &amp; conditions</a>
      </nav>
    </div>
  </div>
</footer>"""


def cta_band(line, sub, primary=("Start an enquiry", "contact.html#enquiry"),
             secondary=("View capabilities", "capabilities.html")):
    return f"""<section class="cta band">
  <div class="cta__glow" aria-hidden="true"></div>
  <div class="shell">
    <div class="grid" data-reveal-group>
      <div class="c7">
        <p class="mono mono--signal" data-reveal>Next step</p>
        <h2 class="cta__big" style="margin-block:1.5rem 1.75rem" data-reveal>{e(line)}</h2>
        <p class="lead" data-reveal>{e(sub)}</p>
        <div class="btnrow" style="margin-top:2.5rem" data-reveal>
          {btn(primary[0], primary[1])}
          {btn(secondary[0], secondary[1], "btn--ghost")}
        </div>
      </div>
      <div class="c4 start9" data-reveal>
        <div class="panel">
          <div class="panel__core">
            <p class="mono mono--fg">Direct lines</p>
            <ul style="margin-top:1.1rem;display:grid;gap:.65rem">
              {"".join(f'<li class="mono" style="color:var(--fg-dim)"><a href="tel:{e(p.replace(" ", ""))}">{e(p)}</a></li>' for p in SITE["phones"])}
            </ul>
            <p class="mono" style="margin-top:1.25rem;padding-top:1rem;border-top:1px solid var(--line)">
              <a href="mailto:{e(SITE["emails"][0][1])}" style="color:var(--signal)">{e(SITE["emails"][0][1])}</a>
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>"""


def marquee():
    strip = "".join(f"<span>{e(c)}</span>" for c in CREDENTIALS)
    return f"""<div class="marquee" aria-hidden="true">
  <div class="marquee__track"><div>{strip}</div><div>{strip}</div></div>
</div>"""


# ===========================================================================
# PAGE SHELL
# ===========================================================================
def render(filename, title, description, body, active="", jsonld=None):
    ld = ""
    if jsonld:
        ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>'

    rails = "".join(f'<span style="--i:{i}"></span>' for i in range(12))

    doc = f"""<!doctype html>
<html lang="en-PH">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<meta name="theme-color" content="#071009">
<link rel="canonical" href="{SITE['url']}/{filename}">
<link rel="icon" href="assets/img/ewize-seal.png" type="image/png">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{e(SITE['legal'])}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{SITE['url']}/{filename}">
<meta property="og:image" content="{SITE['url']}/assets/img/ewize-seal.png">
<meta name="twitter:card" content="summary">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900&family=JetBrains+Mono:wght@300;400;500&display=swap">
<link rel="stylesheet" href="assets/css/ewize.css?v={CSS_VER}">
{ld}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<div class="rails" aria-hidden="true"><div class="rails__inner">{rails}</div></div>
<div class="curtain" aria-hidden="true"></div>
{nav_html(active)}
{menu_html()}
<main id="main">
{body}
</main>
{footer_html()}
<div class="grain" aria-hidden="true"></div>
<script src="assets/js/ewize.js" defer></script>
</body>
</html>"""

    with open(os.path.join(ROOT, filename), "w", encoding="utf-8") as f:
        f.write(doc)
    return filename


# ===========================================================================
# PAGES
# ===========================================================================
def build_home():
    creds = "".join(f'<p class="mono">{e(c)}</p>' for c in CREDENTIALS[:4])

    hero = f"""<section class="hero">
  <div class="hero__field" data-field aria-hidden="true"></div>
  <div class="hero__glow" aria-hidden="true"></div>
  <div class="hero__glow hero__glow--b" aria-hidden="true"></div>
  <div class="shell">
    <div class="grid is-in" data-reveal-group>
      <div class="hero__type c9">
        <p class="tag">DOE-Recognized Training Institution · Registered ESCO</p>
        <h1>{lines(HOME["hero_lines"], underline=HOME["hero_underline"])}</h1>
        <p class="lead hero__sub" data-reveal>{e(HOME["hero_sub"])}</p>
        <div class="btnrow" data-reveal>
          {btn("Request an energy audit", "contact.html#enquiry")}
          {btn("Get a solar PV quote", "contact.html#enquiry", "btn--amber")}
          {btn("2026 training schedule", "programs.html#schedule", "btn--ghost")}
        </div>
      </div>
    </div>
    <div class="hero__rail">
      <div class="hero__creds">{creds}</div>
      <div class="scrollcue"><i aria-hidden="true"></i><span class="mono">Scroll</span></div>
    </div>
  </div>
</section>"""

    mandate_rows = "".join(
        f"""<div class="spec__row" data-reveal>
      <div class="spec__n">{e(n)}</div>
      <div class="spec__k">{e(k)}</div>
      <div class="spec__v">{e(v)}</div>
    </div>"""
        for n, k, v in HOME["mandate_rows"]
    )

    stats = "".join(
        f"""<div class="stat" data-reveal>
      <p class="stat__val"><span data-count="{e(val)}">0</span>{sup}</p>
      <p class="mono stat__lab">{e(lab)}</p>
      <p class="stat__note">{e(note)}</p>
    </div>"""
        for val, sup, lab, note in HOME["stats"]
    )

    mandate = f"""<section class="band band--edge" id="mandate">
  <div class="shell">
    {shead("01", "The mandate",
           f'<h2 class="d1">{lines(HOME["mandate_title"], cls="d1")}</h2>',
           f'<p class="prose">{e(HOME["mandate_aside"])}</p>')}
    {rule()}
    <div class="spec" style="margin-top:var(--sp-block)">{mandate_rows}</div>
    <div class="stats" style="margin-top:var(--sp-block)">{stats}</div>
  </div>
</section>"""

    doors = "".join(
        f"""<article class="door" style="--door-hue:{d["hue"]}">
      <p class="door__no">{e(d["no"])}</p>
      <p class="mono mono--fg" style="margin-top:1.5rem">{e(d["kicker"])}</p>
      <h3 class="d2">{e(d["title"])}</h3>
      <p class="prose" style="max-width:38ch">{e(d["body"])}</p>
      <ul class="door__list">
        {"".join(f"<li><b>{e(code)}</b><span>{e(txt)}</span></li>" for code, txt in d["list"])}
      </ul>
      <div class="door__cta">{tlink(d["cta"][0], d["cta"][1])}</div>
    </article>"""
        for d in HOME["doors"]
    )

    pathways = f"""<section class="band band--edge" id="pathways">
  <div class="shell">
    {shead("02", "Two ways in",
           '<h2 class="d1">Two audiences.<br>One body of expertise.</h2>',
           '<p class="prose">Organisations buy outcomes. Professionals buy credentials. '
           'EnergyWize is registered to deliver both, and each one keeps the other honest.</p>')}
    <div class="doors" data-reveal>{doors}</div>
  </div>
</section>"""

    caps = "".join(
        cap_card(c, wide=(i == 4), side=PROGRAM_SIDE)
        for i, c in enumerate(CAPABILITIES)
    )

    capabilities = f"""<section class="band band--edge" id="capabilities">
  <div class="shell">
    {shead("03", "Capabilities",
           '<h2 class="d1">Everything between<br>the meter and the roof.</h2>',
           '<p class="prose">Five service lines under one DOE registration, so accountability does not '
           'change hands halfway through a project.</p>')}
    <div class="bento" data-reveal-group>{caps}</div>
  </div>
</section>"""

    steps = "".join(
        f"""<div class="step" data-reveal>
      <p class="step__no">{e(no)}</p>
      <h3 class="d3">{e(name)}</h3>
      <p>{e(desc)}</p>
      <p class="step__out">{e(out)}</p>
    </div>"""
        for no, name, desc, out in HOME["method"]
    )

    method = f"""<section class="band band--edge" id="method">
  <div class="shell">
    {shead("04", "Method",
           '<h2 class="d1">Assess. Model.<br>Implement. Verify.</h2>',
           f'<p class="prose">{e(HOME["commitment"])}</p>')}
    <div class="method" data-reveal-group>{steps}</div>
  </div>
</section>"""

    sched = f"""<section class="band band--paper band--edge" id="schedule">
  <div class="shell">
    {shead("05", "2026 calendar",
           '<h2 class="d1">Printed once.<br>Booked quickly.</h2>',
           '<p class="prose">Thirty scheduled runs across five DOE-recognised programs. '
           'Batches close when the room is full — the calendar is the whole story.</p>')}
    {sched_table("cemcea")}
    <div class="btnrow" style="margin-top:2.5rem" data-reveal>
      {btn("All programs and dates", "programs.html", "btn--ghost")}
    </div>
  </div>
</section>"""

    regs = "".join(
        f"""<div class="spec__row" data-reveal>
      <div class="spec__n">R-0{i + 1}</div>
      <div class="spec__k">{e(name)}</div>
      <div class="spec__v"><span class="mono mono--signal">{e(code)}</span><br>{e(kind)}</div>
    </div>"""
        for i, (name, code, kind) in enumerate(REGISTRATIONS)
    )

    credentials = f"""<section class="band band--edge" id="credentials">
  <div class="shell">
    {shead("06", "On the record",
           '<h2 class="d1">Five registrations,<br>printed on the seal.</h2>',
           '<p class="prose">Every program we run is recognised by the Department of Energy under its own '
           'registration number. Verify any of them before you enrol.</p>')}
    <div class="spec">{regs}</div>
  </div>
</section>
{marquee()}"""

    jsonld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": SITE["legal"],
        "alternateName": SITE["dba"],
        "url": SITE["url"],
        "logo": SITE["url"] + "/assets/img/ewize-seal.png",
        "description": "DOE-Recognized Training Institution and registered Energy Service Company "
                       "providing energy audits, energy management systems, solar PV, MEPF solutions, "
                       "and DOE certification training in the Philippines.",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "10F Tower 1, Paseo de Roces, Chino Roces Avenue, Pio del Pilar",
            "addressLocality": "Makati",
            "addressRegion": "NCR",
            "postalCode": "1230",
            "addressCountry": "PH",
        },
        "email": SITE["emails"][0][1],
        "telephone": SITE["phones"][3],
    }

    return render(
        "index.html",
        "EnergyWize Solutions — Energy audits, management systems & DOE certification",
        "DOE-Recognized Training Institution and registered ESCO in Makati. Level 1–3 energy audits, "
        "ISO 50001 energy management systems, solar PV, MEPF, and CEM / CEA / GEMP certification training.",
        hero + mandate + pathways + capabilities + method + sched + credentials
        + cta_band(HOME["cta_line"], HOME["cta_sub"]),
        active="index.html",
        jsonld=jsonld,
    )


def masthead(crumb, label, title_lines, lede, meta=()):
    """Interior-page header. `meta` is a list of (label, value) readouts that
    fill the right column with something worth reading."""
    crumbs = "".join(
        f'<a class="mono" href="{e(h)}">{e(t)}</a><span class="mono">/</span>'
        for t, h in crumb
    )
    readouts = "".join(
        f'<div class="readout"><p class="mono">{e(k)}</p>'
        f'<p class="readout__v">{e(v)}</p></div>'
        for k, v in meta
    )
    return f"""<section class="masthead">
  <div class="masthead__glow" aria-hidden="true"></div>
  <div class="shell">
    <div class="grid is-in" data-reveal-group>
      <div class="c7">
        <div class="crumbs">{crumbs}<span class="mono mono--signal">{e(label)}</span></div>
        <h1 class="d1" style="margin-block:1.75rem 1.5rem">{lines(title_lines, cls="d1")}</h1>
        <p class="lead" data-reveal>{e(lede)}</p>
      </div>
      <div class="c4 start9" data-reveal>
        <div class="readouts">{readouts}</div>
      </div>
    </div>
  </div>
</section>"""


def build_capabilities():
    caps = "".join(
        cap_card(c, wide=(i == 4), side=PROGRAM_SIDE)
        for i, c in enumerate(CAPABILITIES)
    )

    body = masthead(
        [("Home", "index.html")], "Capabilities",
        ["Everything between", "the meter", "and the roof"],
        "Five service lines delivered under one Department of Energy registration. You can buy any one of "
        "them on its own — most clients start with an audit because it tells them which of the others is "
        "worth the money.",
        meta=[("Service lines", "Five"),
              ("Standing", "DOE-Registered ESCO"),
              ("Standards applied", "ISO 50001 · ISO 50002 · RA 11285")],
    )

    body += f"""<section class="band band--tight">
  <div class="shell"><div class="bento" data-reveal-group>{caps}</div></div>
</section>"""

    steps = "".join(
        f"""<div class="step" data-reveal>
      <p class="step__no">{e(no)}</p>
      <h3 class="d3">{e(name)}</h3>
      <p>{e(desc)}</p>
      <p class="step__out">{e(out)}</p>
    </div>"""
        for no, name, desc, out in HOME["method"]
    )

    body += f"""<section class="band band--edge">
  <div class="shell">
    {shead("C-M", "How work runs",
           '<h2 class="d1">One sequence,<br>whatever you buy.</h2>',
           '<p class="prose">Projects fail at the handovers. Keeping assessment, delivery, and verification '
           'inside one registered ESCO removes most of them.</p>')}
    <div class="method" data-reveal-group>{steps}</div>
  </div>
</section>
{marquee()}"""

    body += cta_band(
        "Scope it before you buy it.",
        "Tell us the floor area, the fuel mix, and what your last twelve months of bills looked like. "
        "We will tell you which audit level answers your question.",
        secondary=("View programs", "programs.html"),
    )

    return render(
        "capabilities.html",
        "Capabilities — Energy audits, EnMS, solar & MEPF | EnergyWize Solutions",
        "Level 1–3 energy audits, ISO 50001 energy management systems, solar PV, MEPF solutions, and "
        "DOE-recognised technical training from a registered Philippine ESCO.",
        body, active="capabilities.html",
    )


def build_capability(c):
    rows = "".join(
        f"""<div class="spec__row" data-reveal>
      <div class="spec__n">{i + 1:02d}</div>
      <div class="spec__k">{e(k)}</div>
      <div class="spec__v">{e(v)}{
          ("<ul>" + "".join(f"<li>{e(b)}</li>" for b in bullets) + "</ul>") if bullets else ""
      }</div>
    </div>"""
        for i, (k, v, bullets) in enumerate(c["rows"])
    )

    prose = "".join(f'<p class="prose" data-reveal>{e(p)}</p>' for p in c["body"])
    others = [x for x in CAPABILITIES if x["slug"] != c["slug"]][:4]
    related = "".join(cap_card(o, blurb_key="kicker") for o in others)

    body = masthead(
        [("Home", "index.html"), ("Capabilities", "capabilities.html")],
        c["title"], c["hero_lines"], c["lede"],
        meta=[("Reference", c["no"]),
              ("Delivered by", "DOE-Registered ESCO"),
              ("Scope", " · ".join(c["specs"]))],
    )

    body += f"""<section class="band band--tight band--edge">
  <div class="shell">
    <div class="grid">
      <div class="c6 start2" data-reveal-group>{prose}</div>
      <div class="c3 start9" data-reveal>
        <div class="panel"><div class="panel__core">
          <p class="mono mono--fg">Scope tags</p>
          <div style="display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1rem">
            {"".join(f'<span class="mono" style="border:1px solid var(--line-mid);padding:.35rem .6rem">{e(s)}</span>' for s in c["specs"])}
          </div>
          <div style="margin-top:1.5rem;padding-top:1.1rem;border-top:1px solid var(--line)">
            {tlink(c["cta"][0], c["cta"][1])}
          </div>
        </div></div>
      </div>
    </div>
  </div>
</section>

<section class="band">
  <div class="shell">
    {shead(c["no"], "What is included",
           f'<h2 class="d1">{e(c["kicker"])}</h2>',
           '<p class="prose">Each line below is a deliverable, not a capability statement. '
           'Ask for any of them individually.</p>')}
    <div class="spec">{rows}</div>
  </div>
</section>

<section class="band band--edge">
  <div class="shell">
    {shead("→", "Also from EnergyWize", '<h2 class="d2">Related capabilities</h2>')}
    <div class="bento" data-reveal-group>{related}</div>
  </div>
</section>"""

    body += cta_band(
        c["cta"][0] + ".",
        "Send us the building, the process, or the fleet. We will come back with scope, duration, and what "
        "the deliverable actually contains.",
        primary=(c["cta"][0], c["cta"][1]),
    )

    return render(
        c["slug"] + ".html",
        f"{c['title']} — {c['kicker']} | EnergyWize Solutions",
        c["blurb"],
        body, active="capabilities.html",
    )


def build_programs():
    cards = "".join(
        f"""<article class="cap" data-reveal>
      <p class="cap__no">{e(p["no"])} · {e(p["code"])}</p>
      <span class="cap__go" aria-hidden="true">{ICONS["arrow"]}</span>
      <div class="cap__ico">{ICONS["training"]}</div>
      <h3 class="d3"><a class="stretch" href="{p["slug"]}.html">{e(p["title"])}</a></h3>
      <p>{e(p["blurb"])}</p>
      <div class="cap__spec">
        <span class="mono">{e(p["length"])}</span>
        <span class="mono mono--signal">{e(p["reg"])}</span>
      </div>
    </article>"""
        for p in PROGRAMS
    )

    tables = "".join(
        f"""<div style="margin-top:var(--sp-block)">
      <h3 class="d3" data-reveal>{e(SCHEDULES[k]["label"])}</h3>
      <div style="margin-top:1.5rem">{sched_table(k)}</div>
    </div>"""
        for k in ("cemcea", "gemp", "rcem", "rcea")
    )

    body = masthead(
        [("Home", "index.html")], "Programs",
        ["Get certified.", "Stay certified."],
        "EnergyWize Solutions is a DOE-Recognized Training Institution. Completing our programs qualifies "
        "participants to apply to the Department of Energy for certification — and our recertification "
        "tracks keep existing credentials current.",
        meta=[("Programs", "Five"),
              ("Scheduled runs, 2026", "Thirty"),
              ("Training desk", SITE["emails"][1][1])],
    )

    body += f"""<section class="band band--tight">
  <div class="shell"><div class="bento" data-reveal-group>{cards}</div></div>
</section>

<section class="band band--paper band--edge" id="schedule">
  <div class="shell">
    {shead("P-CAL", "2026 calendar",
           '<h2 class="d1">Every run,<br>every date.</h2>',
           '<p class="prose">Thirty scheduled runs across five programs. Registration closes when the room '
           'fills; email the training desk to hold a slot.</p>')}
    {tables}
    <div class="btnrow" style="margin-top:3rem" data-reveal>
      {btn("Register for a batch", "contact.html#enquiry")}
      <span class="mono">{e(SITE["emails"][1][1])}</span>
    </div>
  </div>
</section>
{marquee()}"""

    body += cta_band(
        "Name the batch. We will hold the slot.",
        "Tell us the program, the batch, and how many people you are sending. Group bookings and in-house "
        "delivery are available for organisations.",
        primary=("Register now", "contact.html#enquiry"),
        secondary=("View capabilities", "capabilities.html"),
    )

    return render(
        "programs.html",
        "Training programs & 2026 schedule — CEM, CEA, GEMP | EnergyWize Solutions",
        "DOE-recognised CEM, CEA, GEMP and recertification training in the Philippines. Full 2026 batch "
        "schedule with thirty scheduled runs.",
        body, active="programs.html",
    )


def build_program(p):
    topics = "".join(
        f"""<div class="spec__row" data-reveal>
      <div class="spec__n">{i + 1:02d}</div>
      <div class="spec__k">{e(k)}</div>
      <div class="spec__v">{e(v)}</div>
    </div>"""
        for i, (k, v) in enumerate(p["topics"])
    )

    benefits = "".join(
        f'<li style="display:flex;gap:1rem;padding-block:.9rem;border-top:1px solid var(--line)">'
        f'<span class="mono mono--signal">{i + 1:02d}</span>'
        f'<span style="color:var(--fg-dim);font-size:.95rem;line-height:1.6">{e(b)}</span></li>'
        for i, b in enumerate(p["benefits"])
    )

    body = masthead(
        [("Home", "index.html"), ("Programs", "programs.html")],
        p["code"], [p["title"]], p["lede"],
        meta=[("DOE registration", p["reg"]),
              ("Duration", p["length"]),
              ("Who it is for", p["audience"])],
    )

    body += f"""<section class="band band--edge">
  <div class="shell">
    {shead(p["no"], "Curriculum",
           '<h2 class="d1">Key topics<br>covered.</h2>',
           '<p class="prose">Delivered by practising energy professionals and certified instructors. '
           'Sessions combine classroom work with hands-on use of audit instrumentation.</p>')}
    <div class="spec">{topics}</div>
  </div>
</section>

<section class="band band--edge">
  <div class="shell">
    <div class="grid">
      <div class="c5" data-reveal>
        <p class="mono mono--signal">Certification &amp; benefits</p>
        <h2 class="d2" style="margin-block:1.5rem 1.25rem">What you walk out with.</h2>
        <p class="prose" style="max-width:34ch">Registered with the Department of Energy under
          <span class="mono mono--signal">{e(p["reg"])}</span>.</p>
        <div style="margin-top:2rem">{btn("Register for " + p["code"], "contact.html#enquiry")}</div>
      </div>
      <div class="c6 start7" data-reveal>
        <ul>{benefits}</ul>
      </div>
    </div>
  </div>
</section>

<section class="band band--paper band--edge" id="schedule">
  <div class="shell">
    {shead("CAL", "2026 dates",
           f'<h2 class="d1">{e(p["code"])} schedule.</h2>',
           '<p class="prose">Slots are held on confirmation. Email the training desk with your batch '
           'preference and headcount.</p>')}
    {sched_table(p["schedule_key"])}
  </div>
</section>"""

    jsonld = {
        "@context": "https://schema.org",
        "@type": "Course",
        "name": p["title"],
        "description": p["blurb"],
        "provider": {"@type": "Organization", "name": SITE["legal"], "url": SITE["url"]},
        "identifier": p["reg"],
    }

    body += cta_band(
        f"Reserve a {p['code']} slot.",
        "Confirm your batch with the training desk and we will send the registration pack, requirements, "
        "and payment details.",
        primary=("Register now", "contact.html#enquiry"),
        secondary=("All programs", "programs.html"),
    )

    return render(
        p["slug"] + ".html",
        f"{p['title']} ({p['code']}) — 2026 schedule | EnergyWize Solutions",
        p["blurb"],
        body, active="programs.html", jsonld=jsonld,
    )


def build_about():
    prose = "".join(f'<p class="prose" data-reveal>{e(t)}</p>' for t in ABOUT["body"])
    closing = "".join(f'<p class="prose" data-reveal>{e(t)}</p>' for t in ABOUT["closing"])
    svc = "".join(
        f'<li style="display:flex;gap:1rem;padding-block:.9rem;border-top:1px solid var(--line)">'
        f'<span class="mono mono--signal">{i + 1:02d}</span>'
        f'<span style="color:var(--fg-dim);font-size:.95rem;line-height:1.6">{e(s)}</span></li>'
        for i, s in enumerate(ABOUT["services_list"])
    )
    regs = "".join(
        f"""<div class="spec__row" data-reveal>
      <div class="spec__n">R-0{i + 1}</div>
      <div class="spec__k">{e(name)}</div>
      <div class="spec__v"><span class="mono mono--signal">{e(code)}</span><br>{e(kind)}</div>
    </div>"""
        for i, (name, code, kind) in enumerate(REGISTRATIONS)
    )

    body = masthead(
        [("Home", "index.html")], "Company",
        ABOUT["hero_lines"], ABOUT["lede"],
        meta=[("Standing", "DOE-Recognized Training Institution"),
              ("Also registered as", "DOE-Registered ESCO"),
              ("Based in", "Makati, Metro Manila")],
    )

    body += f"""<section class="band band--tight band--edge">
  <div class="shell">
    <div class="grid">
      <div class="c6 start2" data-reveal-group>{prose}</div>
      <div class="c4 start9" data-reveal>
        <p class="mono mono--fg">Services under ESCO registration</p>
        <ul style="margin-top:1rem">{svc}</ul>
      </div>
    </div>
  </div>
</section>

<section class="band">
  <div class="shell">
    {shead("A-01", "Vision &amp; mission",
           '<h2 class="d1">Why the company<br>exists.</h2>')}
    <div class="grid" data-reveal-group>
      <div class="c5" data-reveal>
        <div class="panel"><div class="panel__core" style="padding:2rem">
          <p class="mono mono--signal">Vision</p>
          <p class="prose" style="margin-top:1.1rem;font-size:1.05rem">{e(ABOUT["vision"])}</p>
        </div></div>
      </div>
      <div class="c5 start7" data-reveal>
        <div class="panel"><div class="panel__core" style="padding:2rem">
          <p class="mono mono--amber">Mission</p>
          <p class="prose" style="margin-top:1.1rem;font-size:1.05rem">{e(ABOUT["mission"])}</p>
        </div></div>
      </div>
    </div>
    <div class="grid" style="margin-top:var(--sp-block)">
      <div class="c6 start2" data-reveal-group>{closing}</div>
    </div>
  </div>
</section>

<section class="band band--edge">
  <div class="shell">
    {shead("A-02", "On the record",
           '<h2 class="d1">DOE registrations.</h2>',
           '<p class="prose">Each program runs under its own Department of Energy registration number. '
           'These are printed on the corporate seal and can be verified with the DOE.</p>')}
    <div class="spec">{regs}</div>
  </div>
</section>
{marquee()}"""

    body += cta_band(
        "Work with a registered ESCO.",
        "Whether you need an audit, a management system, or a certified energy manager on staff, the "
        "conversation starts the same way.",
    )

    return render(
        "about.html",
        "Company — DOE-Recognized Training Institution & registered ESCO | EnergyWize Solutions",
        "EnergyWize Solutions Inc. is a DOE-Recognized Training Institution for CEM, CEA, AEA and GEMP "
        "courses, and a DOE-Registered Energy Service Company based in Makati, Philippines.",
        body, active="about.html",
    )


def build_contact():
    reasons = "".join(f'<option value="{e(r)}">{e(r)}</option>' for r in CONTACT["reasons"])
    phones = "".join(
        f'<li><a href="tel:{e(p.replace(" ", ""))}">{e(p)}</a></li>' for p in SITE["phones"]
    )
    emails = "".join(
        f'<div class="contacts__item"><span class="mono">{e(label)}</span>'
        f'<a href="mailto:{e(addr)}">{e(addr)}</a></div>'
        for label, addr in SITE["emails"]
    )
    addr = "<br>".join(e(l) for l in SITE["address_lines"])

    body = masthead(
        [("Home", "index.html")], "Contact",
        CONTACT["hero_lines"], CONTACT["lede"],
        meta=[("Office", "Makati, Metro Manila"),
              ("General enquiries", SITE["emails"][0][1]),
              ("Training desk", SITE["emails"][1][1])],
    )

    body += f"""<section class="band band--tight band--edge" id="enquiry">
  <div class="shell">
    <div class="grid">
      <div class="c7" data-reveal>
        <p class="mono mono--signal">Enquiry</p>
        <h2 class="d2" style="margin-block:1.25rem 2rem">Send us the details.</h2>
        <form class="form" data-form novalidate>
          <div class="form__grid">
            <div class="field">
              <label for="f-name">Name</label>
              <input id="f-name" name="name" type="text" required autocomplete="name" placeholder="Full name">
              <p class="field__err">Please enter your name.</p>
            </div>
            <div class="field">
              <label for="f-org">Organisation</label>
              <input id="f-org" name="organisation" type="text" autocomplete="organization" placeholder="Company, agency, or LGU">
              <p class="field__help">Optional — helps us scope the right audit level.</p>
            </div>
            <div class="field">
              <label for="f-email">Email</label>
              <input id="f-email" name="email" type="email" required autocomplete="email" placeholder="you@organisation.com">
              <p class="field__err">Please enter a valid email address.</p>
            </div>
            <div class="field">
              <label for="f-phone">Phone</label>
              <input id="f-phone" name="phone" type="tel" autocomplete="tel" placeholder="+63">
            </div>
          </div>
          <div class="field">
            <label for="f-reason">What is this about</label>
            <select id="f-reason" name="reason" required>{reasons}</select>
          </div>
          <div class="field">
            <label for="f-msg">Message</label>
            <textarea id="f-msg" name="message" required
              placeholder="Floor area, fuel mix, monthly consumption, or the training batch you want."></textarea>
            <p class="field__err">Please tell us a little about the enquiry.</p>
          </div>
          <label class="check">
            <input type="checkbox" name="terms" required>
            <span>I accept the terms and conditions and consent to EnergyWize Solutions contacting me about this enquiry.</span>
          </label>
          <div class="btnrow">
            <button class="btn" type="submit" data-magnetic>
              <span class="btn__label">Send enquiry</span>
              <span class="btn__pip" aria-hidden="true">{ICONS["arrow"]}</span>
            </button>
          </div>
          <p class="formnote" role="status"></p>
        </form>
      </div>

      <div class="c5 start8" data-reveal>
        <div class="contacts">
          <div class="contacts__row">
            <p class="mono mono--fg">Office</p>
            <address style="font-style:normal">{addr}</address>
          </div>
          <div class="contacts__row">
            <p class="mono mono--fg">Email</p>
            {emails}
          </div>
          <div class="contacts__row">
            <p class="mono mono--fg">Telephone</p>
            <ul style="display:grid;gap:.45rem">{phones}</ul>
          </div>
          <div class="contacts__row">
            <p class="mono mono--fg">Hours</p>
            <p>Monday to Friday, 8:00am — 5:00pm PHT.<br>Training runs 9:00am — 4:00pm.</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>
{marquee()}"""

    return render(
        "contact.html",
        "Contact — audits, quotations & training registration | EnergyWize Solutions",
        "Reach EnergyWize Solutions Inc. in Makati for energy audit scoping, solar PV quotations, MEPF "
        "packages, and CEM / CEA / GEMP training registration.",
        body, active="contact.html",
    )


def build_legal(doc, filename):
    """Generic renderer for the legal pages (Privacy Policy, Legal Notice,
    Terms & Conditions) — same {heading, paragraphs, list, closing} section
    shape as src/site_content.py's LEGAL_* dicts, so both builds stay in
    sync off the one set of mirrored text."""
    sub = f"Effective {doc['effective_date']}"
    if doc.get("version"):
        sub += f" · {doc['version']}"

    sections = ""
    for s in doc["sections"]:
        paras = "".join(f'<p class="prose" style="margin-bottom:1rem;white-space:pre-line">{e(p)}</p>'
                         for p in s.get("paragraphs", []))
        items = ""
        if s.get("list"):
            items = '<ul class="prose" style="margin:0 0 1rem 1.25rem;padding:0">' + "".join(
                f'<li style="margin-bottom:.5rem">{e(item)}</li>' for item in s["list"]
            ) + "</ul>"
        closing = "".join(f'<p class="prose" style="margin-bottom:1rem;white-space:pre-line">{e(p)}</p>'
                           for p in s.get("closing", []))
        sections += f"""<div style="margin-bottom:2.5rem" data-reveal>
      <h2 class="d3" style="margin-bottom:1.1rem">{e(s["heading"])}</h2>
      {paras}{items}{closing}
    </div>"""

    body = masthead([("Home", "index.html")], "Legal", [doc["title"]], sub)
    body += f"""<section class="band band--tight">
  <div class="shell">
    <div class="grid">
      <div class="c8 start2" data-reveal-group>{sections}</div>
    </div>
  </div>
</section>"""

    return render(
        filename,
        f"{doc['title']} — EnergyWize Solutions",
        f"{doc['title']} for EnergyWize Solutions Inc.",
        body,
    )


# ===========================================================================
def main():
    written = [build_home(), build_capabilities(), build_programs(),
               build_about(), build_contact()]
    written += [build_capability(c) for c in CAPABILITIES]
    written += [build_program(p) for p in PROGRAMS]
    written += [
        build_legal(PRIVACY_POLICY, "privacy-policy.html"),
        build_legal(LEGAL_NOTICE, "legal-notice.html"),
        build_legal(TERMS_CONDITIONS, "terms-and-conditions.html"),
    ]

    urls = "".join(
        f"<url><loc>{SITE['url']}/{f}</loc></url>" for f in written
    )
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + urls + "</urlset>")

    with open(os.path.join(ROOT, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE['url']}/sitemap.xml\n")

    print(f"Built {len(written)} pages:")
    for f in written:
        print("  " + f)


if __name__ == "__main__":
    main()
