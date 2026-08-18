"""SVG icon set for the public site. Ultra-light strokes, one geometry
language. Rendered through the `icon()` Jinja global in site_bp.py."""


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
