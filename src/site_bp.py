"""Public marketing site.

Renders the EnergyWize brochure pages from site_content.py using the shared
design system in static/ewize.css. Batch dates are read from the `batches`
table so the published calendar and the registration forms never disagree.

The `/` and `/programs` routes stay on registration_bp (a lot of the app links
to those endpoints); they render templates from this package via the helpers
below.
"""

from datetime import datetime

from flask import Blueprint, abort, jsonify, render_template, url_for
from markupsafe import Markup

import site_content as C
from site_icons import ICONS
from db import get_public_schedule

site_bp = Blueprint("site", __name__)

# Batch type in `batches` -> how it is presented on the public calendar.
SCHEDULE_GROUPS = [
    ("training", "CEM & CEA",
     "Certified Energy Manager / Certified Energy Auditor."),
    ("gemp_training", "GEMP",
     "Government Energy Management Program, for government agencies and LGUs."),
    ("renewal", "Recertification",
     "Renewal training for accredited Energy Managers and Energy Auditors."),
]

PROGRAM_BY_CODE = {p["code"].lower(): p for p in C.PROGRAMS}
CAPABILITY_BY_SLUG = {c["slug"]: c for c in C.CAPABILITIES}


def _schedule():
    """Batches from the database, keyed by type. Never raises — a database
    hiccup should degrade the calendar, not take the brochure site down."""
    try:
        return get_public_schedule()
    except Exception:
        return {key: [] for key, _, _ in SCHEDULE_GROUPS}


@site_bp.app_context_processor
def _site_context():
    return {
        "SITE": C.SITE,
        "NAV": C.NAV,
        "CAPABILITIES": C.CAPABILITIES,
        "PROGRAMS": C.PROGRAMS,
        "REGISTRATIONS": C.REGISTRATIONS,
        "CREDENTIALS": C.CREDENTIALS,
        "HOME": C.HOME,
        "ABOUT": C.ABOUT,
        "CONTACT": C.CONTACT,
        "icon": lambda name: Markup(ICONS.get(name, "")),
        "year": datetime.now().year,
        "has_auth": True,
        "active": None,
    }


# ---------------------------------------------------------------------------
# Pages owned by registration_bp — rendered here to keep the markup together
# ---------------------------------------------------------------------------
def render_home():
    schedule = _schedule()
    batch_count = sum(len(v) for v in schedule.values())
    stats = [
        ("5", "DOE registrations",
         "Recognized Training Institution across CEM, CEA, GEMP, and both recertification tracks."),
        ("3", "Audit levels",
         "Walk-through, detailed, and investment-grade — scoped to the decision you need to make."),
        ("2", "ISO standards applied",
         "ISO 50001 for management systems, ISO 50002 for audits."),
        (str(batch_count), "Batches on the calendar",
         "Published training runs currently open across all five certification programs."),
    ]
    org_jsonld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": C.SITE["legal"],
        "alternateName": C.SITE["dba"],
        "url": C.SITE["url"],
        "description": "DOE-Recognized Training Institution and registered Energy Service "
                       "Company providing energy audits, energy management systems, solar PV, "
                       "MEPF solutions, and DOE certification training in the Philippines.",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "10F Tower 1, Paseo de Roces, Chino Roces Avenue, Pio del Pilar",
            "addressLocality": "Makati",
            "addressRegion": "NCR",
            "postalCode": "1230",
            "addressCountry": "PH",
        },
        "email": C.SITE["emails"][0][1],
        "telephone": C.SITE["phones"][3],
    }
    return render_template(
        "site/home.html",
        active="registration.index",
        schedule=schedule,
        stats=stats,
        org_jsonld=org_jsonld,
    )


def render_programs():
    schedule = _schedule()
    return render_template(
        "site/programs.html",
        active="registration.programs",
        schedule=schedule,
        schedule_groups=SCHEDULE_GROUPS,
        batch_count=sum(len(v) for v in schedule.values()),
    )


# ---------------------------------------------------------------------------
# Pages owned by this blueprint
# ---------------------------------------------------------------------------
@site_bp.route("/capabilities")
def capabilities():
    return render_template("site/capabilities.html", active="site.capabilities")


@site_bp.route("/capabilities/<slug>")
def capability(slug):
    c = CAPABILITY_BY_SLUG.get(slug)
    if not c:
        abort(404)
    related = [x for x in C.CAPABILITIES if x["slug"] != slug][:4]
    # Training is the one capability whose call to action is a program, not an enquiry.
    cta_href = (url_for("registration.programs") if c["slug"] == "technical-training"
                else url_for("site.contact") + "#enquiry")
    return render_template(
        "site/capability.html",
        active="site.capabilities",
        c=c, related=related, cta_href=cta_href,
    )


@site_bp.route("/programs/<code>")
def program(code):
    p = PROGRAM_BY_CODE.get(code.lower())
    if not p:
        abort(404)
    rows = _schedule().get(p["batch_type"], [])
    note = next((n for k, _, n in SCHEDULE_GROUPS if k == p["batch_type"]), "")
    course_jsonld = {
        "@context": "https://schema.org",
        "@type": "Course",
        "name": p["title"],
        "description": p["blurb"],
        "provider": {"@type": "Organization", "name": C.SITE["legal"], "url": C.SITE["url"]},
        "identifier": p["reg"],
    }
    return render_template(
        "site/program.html",
        active="registration.programs",
        p=p, rows=rows, note=note, course_jsonld=course_jsonld,
    )


@site_bp.route("/about")
def about():
    return render_template("site/about.html", active="site.about")


@site_bp.route("/contact")
def contact():
    return render_template(
        "site/contact.html",
        active="site.contact",
        solar_url=url_for("solar.solar_form"),
    )


@site_bp.route("/privacy-policy")
def privacy_policy():
    return render_template("site/legal.html", active="site.privacy_policy", doc=C.PRIVACY_POLICY)


@site_bp.route("/legal-notice")
def legal_notice():
    return render_template("site/legal.html", active="site.legal_notice", doc=C.LEGAL_NOTICE)


@site_bp.route("/terms-and-conditions")
def terms_conditions():
    return render_template("site/legal.html", active="site.terms_conditions", doc=C.TERMS_CONDITIONS)


# Legal docs the registration forms open in a modal, keyed by the same slug as
# their public URL so the link's href (the no-JS fallback) and the modal fetch
# can't point at different documents.
LEGAL_DOCS = {
    "privacy-policy": C.PRIVACY_POLICY,
    "legal-notice": C.LEGAL_NOTICE,
    "terms-and-conditions": C.TERMS_CONDITIONS,
}


@site_bp.route("/api/legal/<slug>")
def legal_doc(slug):
    """A legal doc as HTML, so the multi-step forms can show it without
    navigating away and losing the wizard's state and uploaded files."""
    doc = LEGAL_DOCS.get(slug)
    if doc is None:
        abort(404)
    return jsonify(
        title=doc["title"],
        effective=doc.get("effective_date", ""),
        version=doc.get("version") or "",
        html=render_template("site/_legal_body.html", doc=doc, reveal=False),
    )
