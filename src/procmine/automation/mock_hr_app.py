"""A self-contained, in-memory mock HR/Payroll demo application.

Explicitly a PROTOTYPE/DEMO environment — this is NOT the production
system observed in Dataset B, and does not claim to be. It reproduces
only the DOM structure the forensic analysis actually evidenced
(`reports/day3/hr_payroll_dominant_path_analysis.md`): four routes,
each with one route-specific note `<textarea>` (id `"<prefix>-note"`,
class `"input"`) and one confirm `<button>` (id `"btn-<prefix>-ok"`,
class `"btn success"`) — the exact ids and classes recurring in the
real recorded data, not invented ones.

The route set and their id-prefixes are read from
`procmine.process_discovery.dom_evidence.KNOWN_ROUTE_PREFIXES` (the
same evidence-derived constant the forensic analysis itself uses) —
reused here rather than re-declared, so the automation layer can never
silently drift from what was actually observed.

Supports deliberate fault injection (a missing field, a duplicated
element, a route that fails to navigate) so the automation layer's
required safe-failure paths (Step 3, section 5) can be exercised
against realistic anomalies without needing a real, unpredictable
target application.
"""

from __future__ import annotations

from dataclasses import dataclass

from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES


@dataclass
class MockElement:
    element_id: str
    element_type: str  # "textarea" | "button"
    css_class: str
    value: str | None = None
    clicked: bool = False


@dataclass
class RouteConfig:
    """One route's element set. `None` (the default) for either list
    means "use exactly what Dataset B's dominant path evidenced" (one
    note field, one confirm button); pass an explicit list to inject a
    fault instead -- `[]` = missing element, 2+ entries = an ambiguous
    duplicate, an element with an unexpected id = "DOM structure
    differs". `None` and `[]` are deliberately distinct here (unlike
    plain truthiness) so "not specified, use the default" and
    "intentionally empty" can never be confused with each other."""
    route: str
    note_elements: list[MockElement] | None = None
    confirm_elements: list[MockElement] | None = None
    navigation_fails: bool = False

    def __post_init__(self) -> None:
        prefix = KNOWN_ROUTE_PREFIXES[self.route]
        if self.note_elements is None:
            self.note_elements = [MockElement(f"{prefix}-note", "textarea", "input")]
        if self.confirm_elements is None:
            self.confirm_elements = [MockElement(f"btn-{prefix}-ok", "button", "btn success")]


class MockHRApplication:
    """In-memory model of the demo app's current DOM state.
    `current_route` is `None` until `navigate` succeeds."""

    def __init__(self, route_configs: dict[str, RouteConfig] | None = None):
        self._routes = route_configs if route_configs is not None else {
            r: RouteConfig(route=r) for r in KNOWN_ROUTE_PREFIXES
        }
        self.current_route: str | None = None

    def navigate(self, route: str) -> None:
        """Raises `KeyError` for a route this mock has no configuration
        for at all (a defensive fallback -- the automation layer is
        expected to reject unknown routes before ever calling this),
        or `RuntimeError` if this route's config simulates a navigation
        failure."""
        if route not in self._routes:
            raise KeyError(f"unknown route: {route!r}")
        config = self._routes[route]
        if config.navigation_fails:
            raise RuntimeError(f"navigation to {route!r} failed")
        self.current_route = route

    def find_note_field(self) -> list[MockElement]:
        self._require_navigated()
        return list(self._routes[self.current_route].note_elements)

    def find_confirm_button(self) -> list[MockElement]:
        self._require_navigated()
        return list(self._routes[self.current_route].confirm_elements)

    def set_note_value(self, element_id: str, value: str) -> None:
        for el in self.find_note_field():
            if el.element_id == element_id:
                el.value = value
                return
        raise KeyError(f"no note field with id {element_id!r} on {self.current_route!r}")

    def click(self, element_id: str) -> None:
        for el in self.find_confirm_button():
            if el.element_id == element_id:
                el.clicked = True
                return
        raise KeyError(f"no confirm button with id {element_id!r} on {self.current_route!r}")

    def _require_navigated(self) -> None:
        if self.current_route is None:
            raise RuntimeError("not navigated to any route yet")


_ROUTE_LABELS = {
    "#/payroll-items": "Payroll Items", "#/leave-applications": "Leave Applications",
    "#/onboarding": "Onboarding", "#/social-insurance": "Social Insurance",
}


def _route_panel_html(route: str, prefix: str, label: str) -> str:
    panel_id = f"panel-{prefix}"
    return f"""<section class="route-panel" id="{panel_id}" data-route="{route}" hidden>
  <h3>{label} ({route})</h3>
  <textarea id="{prefix}-note" class="input" placeholder="note"></textarea>
  <br>
  <button id="btn-{prefix}-ok" class="btn success">OK</button>
</section>"""


def render_demo_html() -> str:
    """A real, standalone static HTML/JS page reproducing the mock
    app's structure, for a human to open in a browser and visually
    confirm the same routes/ids the Python automation layer targets.
    All four routes' elements are present directly in the page's own
    markup (not injected only at runtime via a JS template) so the ids
    are visible in the source itself, matching what was directly
    observed in Dataset B. This page is NOT wired to the Python
    automation (no shared process) -- it exists for visual/manual
    observability only, clearly labeled as a prototype throughout,
    never presented as the real HR system."""
    panels = "\n".join(
        _route_panel_html(route, prefix, _ROUTE_LABELS[route])
        for route, prefix in KNOWN_ROUTE_PREFIXES.items()
    )
    nav_links = "\n  ".join(
        f'<a href="{route}">{_ROUTE_LABELS[route]}</a>' for route in KNOWN_ROUTE_PREFIXES
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>HR/Payroll Automation Prototype -- DEMO ONLY</title>
<style>
  body {{ font-family: sans-serif; max-width: 640px; margin: 2em auto; }}
  .banner {{ background: #fff3cd; border: 1px solid #d4a017; padding: 0.75em 1em; margin-bottom: 1.5em; }}
  nav a {{ margin-right: 1em; }}
  textarea {{ width: 100%; height: 5em; }}
  button {{ padding: 0.5em 1em; margin-top: 0.5em; }}
  .btn.success {{ background: #2e7d32; color: white; border: none; }}
  .route-panel {{ border: 1px solid #ccc; padding: 1em; margin-top: 1em; }}
</style>
</head>
<body>
<div class="banner"><strong>PROTOTYPE / DEMO ENVIRONMENT</strong> -- this is a
mock UI built to demonstrate an automation opportunity discovered from
Dataset B. It is NOT the production HR/Payroll system and does not
reproduce any real business logic beyond the DOM structure that was
directly observed.</div>
<nav>
  {nav_links}
</nav>
<p id="no-route-message">Select a route above.</p>
{panels}
<script>
function render() {{
  const route = location.hash || "";
  document.querySelectorAll(".route-panel").forEach(function (panel) {{
    panel.hidden = (panel.dataset.route !== route);
  }});
  document.getElementById("no-route-message").hidden = !!route;
}}
window.addEventListener("hashchange", render);
render();
</script>
</body>
</html>
"""
