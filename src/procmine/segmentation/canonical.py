"""Canonical event representation for the segmentation engine.

Design choice, stated explicitly: this wraps `procmine.models.Event` rather
than extending it in place. `Event` is the adapter-layer output (one per
raw JSON record, dataset-agnostic already, built by `loaders/events.py`);
`CanonicalEvent` is a segmentation-specific derived view that adds fields
no other part of the project needs (interaction category, window title,
browser domain/URL). Keeping them separate means the loader layer doesn't
grow segmentation-specific fields it has no other use for, and a future
Dataset C only ever needs a loader that produces `Event` objects — nothing
about `CanonicalEvent` construction is dataset-specific, since every field
it derives comes from names in DATA_SCHEMA.md's own documented event
structure, not from Dataset A/B-specific values.

Interaction category taxonomy: derived directly from
`audit.KNOWN_EVENT_TYPES_BY_LAYER` (the DATA_SCHEMA-sourced event-type
list already used for schema validation) rather than re-declared, so the
two stay in sync. The category groupings themselves (which event types
count as "input" vs. "pointer" vs. "navigation" etc.) are one reasonable
taxonomy, not the only possible one — kept in one place
(`INTERACTION_CATEGORY_BY_EVENT_TYPE`) specifically so it's easy to revise
without touching the conversion logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from procmine.audit import KNOWN_EVENT_TYPES_BY_LAYER
from procmine.models import Event

INTERACTION_CATEGORY_BY_EVENT_TYPE: dict[str, str] = {
    # navigation: the user moved to a different application/page/tab
    "app_switch": "navigation",
    "browser_navigation": "navigation",
    "browser_tab_event": "navigation",
    # input: the user typed or invoked a shortcut
    "keystroke": "input",
    "shortcut": "input",
    "text_input_complete": "input",
    "browser_form_input": "input",
    # pointer: mouse-driven interaction
    "mouse_click": "pointer",
    "mouse_double_click": "pointer",
    "mouse_scroll": "pointer",
    "mouse_drag_drop": "pointer",
    "browser_click": "pointer",
    # clipboard
    "clipboard_change": "clipboard",
    # ui_state: something about the window/dialog changed, not direct input
    "window_title_change": "ui_state",
    "window_state_change": "ui_state",
    "dialog_opened": "ui_state",
    "dialog_closed": "ui_state",
    "browser_alert": "ui_state",
    "browser_error": "ui_state",
    # capture: the recording agent itself
    "screenshot_smart": "capture",
    # system: agent lifecycle, not user activity
    "session_start": "system",
    "session_end": "system",
    "extension_connected": "system",
    "extension_disconnected": "system",
    "upload_started": "system",
    "upload_completed": "system",
    "upload_failed": "system",
}

# Built from the same source table used for schema validation, so an event
# type known to DATA_SCHEMA but not yet categorized here fails loudly in a
# test rather than silently falling through to "unknown" forever.
_ALL_KNOWN_EVENT_TYPES = {t for types in KNOWN_EVENT_TYPES_BY_LAYER.values() for t in types}


def interaction_category(event_type: str) -> str:
    """Never raises on an unrecognized event_type — future datasets may
    introduce types this project has never seen. Falls back to "unknown"
    rather than crashing or guessing; callers must not treat "unknown" as
    evidence of anything (see module docstring)."""
    return INTERACTION_CATEGORY_BY_EVENT_TYPE.get(event_type, "unknown")


@dataclass
class CanonicalEvent:
    """One event, in the representation the segmentation engine operates
    on. Every field that is not always present is Optional and set to
    None when absent — None means "not observed," never "boundary
    evidence." Nothing here should be interpreted as a signal by itself;
    that's the feature-extraction layer's job (Stage 4), not this one.
    """

    event_id: str
    session_id: str
    timestamp_ms: int
    event_type: str
    layer: str
    interaction_category: str

    application: str | None
    window_title: str | None
    browser_domain: str | None
    browser_url: str | None
    has_extracted_text: bool

    chunk_id: str | None
    sequence_number: int | None

    source_event: Event  # provenance: full original Event, .raw included

    @classmethod
    def from_event(cls, event: Event) -> "CanonicalEvent":
        context = event.raw.get("context") or {}
        active_app = context.get("active_app") or {}
        window_title = active_app.get("window_title")

        browser_tab = context.get("active_browser_tab") or {}
        url = browser_tab.get("url")
        domain = None
        if url:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc or None
            except ValueError:
                domain = None

        extracted_text = context.get("extracted_text")
        has_text = bool(isinstance(extracted_text, dict) and extracted_text.get("text"))

        return cls(
            event_id=event.event_id,
            session_id=event.session_id,
            timestamp_ms=event.timestamp_ms,
            event_type=event.event_type,
            layer=event.layer,
            interaction_category=interaction_category(event.event_type),
            application=event.active_app,
            window_title=window_title,
            browser_domain=domain,
            browser_url=url,
            has_extracted_text=has_text,
            chunk_id=event.chunk_id,
            sequence_number=event.sequence_number,
            source_event=event,
        )


def to_canonical_stream(events: list[Event]) -> list[CanonicalEvent]:
    """Order-preserving conversion. Callers are expected to pass an
    already-chronologically-sorted stream (i.e. `load_session_events`'s
    output) — this function does not re-sort, to keep it a pure,
    side-effect-free mapping with no hidden dependency on timestamp
    ordering being correct."""
    return [CanonicalEvent.from_event(e) for e in events]
