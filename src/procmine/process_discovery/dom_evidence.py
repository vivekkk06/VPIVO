"""Deep-dive DOM/URL evidence extraction for the HR/Payroll dominant-path
forensic analysis (`scripts/analyze_hr_payroll_dominant_path.py`).

Separate from `system_identity.py`/`document_identity.py`, which
classify *which* system/document is active from `CanonicalEvent`'s
already-summarized fields. This module goes one level deeper, reading
the *raw* event dict's own payload -- the hash-route URL fragment
(`#/payroll-items`) and the clicked/filled DOM element's `id`/`class`
-- because the coarse pipeline never needed page-level detail and
`CanonicalEvent` deliberately doesn't carry it. Every field extracted
here is read directly from the schema's own documented payload shape;
nothing is inferred or invented.
"""

from __future__ import annotations

from urllib.parse import urlparse

# The four HR/Payroll routes with a *confirmed* 1:1-or-near-1:1
# note-field/confirm-button pattern (see
# reports/day3/hr_payroll_dominant_path_analysis.md, section 7): 69/69,
# 32/32, 11/11, and 27/26. Two further routes were observed
# (`#/resident-tax`, `#/dashboard`, 4 and 2 occurrences respectively)
# but with no confirmed note/confirm pattern -- deliberately excluded
# here and from the Step-3 automation scope. The two-letter prefix is
# read directly from the data (each route's own note-field/button ids
# share it), not invented.
KNOWN_ROUTE_PREFIXES: dict[str, str] = {
    "#/payroll-items": "pi", "#/leave-applications": "la",
    "#/onboarding": "ob", "#/social-insurance": "si",
}


def url_route(url: str | None) -> str | None:
    """The hash-fragment route of a URL, e.g.
    `http://127.0.0.1:5132/#/payroll-items` -> `#/payroll-items`.
    `None` if there is no URL or no fragment (e.g. the bare root
    `http://127.0.0.1:5132/`)."""
    if not url:
        return None
    frag = urlparse(url).fragment
    return f"#{frag}" if frag else None


def click_target(raw_event: dict) -> dict | None:
    """For a `browser_click` raw event, the clicked DOM element's `id`
    and `class` (the two attributes Dataset B's own data showed
    carrying real, stable identifiers -- see
    `reports/day3/hr_payroll_dominant_path_analysis.md`). `None` if
    the event has no element payload at all (e.g. a `mouse_click`,
    which is OS-level and carries no DOM target) or the element has
    neither attribute set."""
    element = (raw_event.get("payload") or {}).get("element") or {}
    attrs = element.get("attributes") or {}
    el_id, el_class = attrs.get("id"), attrs.get("class")
    if el_id is None and el_class is None:
        return None
    return {"id": el_id, "class": el_class}


def click_context_route(raw_event: dict) -> str | None:
    """The URL route active at the moment of a click, read from
    `context.active_browser_tab.url` (the click payload itself does not
    carry the URL; the surrounding context does)."""
    tab = (raw_event.get("context") or {}).get("active_browser_tab") or {}
    return url_route(tab.get("url"))


def form_field_info(raw_event: dict) -> dict | None:
    """For a `browser_form_input` raw event: the field's `id`, its
    placeholder/label text (the field's own DOM content, not a human's
    typed text), its `input_type`, how the value was entered
    (`input_method` -- Dataset B's own data showed this is exclusively
    `"paste"` within the HR system, never `"type"`), and the URL route
    the input happened on. The actual entered `value` is not exposed
    here because Dataset B's own payload carries `null` for it (masked/
    not captured at the source) -- this function does not attempt to
    guess or backfill it."""
    payload = raw_event.get("payload") or {}
    field = payload.get("field") or {}
    if not field:
        return None
    return {
        "id": field.get("id"), "label": field.get("label"), "input_type": field.get("input_type"),
        "input_method": payload.get("input_method"), "url_route": url_route(payload.get("url")),
    }


def navigation_route_change(raw_event: dict) -> dict | None:
    """For a `browser_navigation` raw event: the route transition
    (`from` -> `to`), read directly from `payload.previous_url`/`url`.
    `None` if either side is missing."""
    payload = raw_event.get("payload") or {}
    prev, cur = url_route(payload.get("previous_url")), url_route(payload.get("url"))
    if prev is None and cur is None:
        return None
    return {"from": prev, "to": cur, "navigation_type": payload.get("navigation_type")}
