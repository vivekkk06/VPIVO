"""Resolves which "business system" an event belongs to.

Dataset B's own evidence (`reports/day3/dataset_b_profile.md` section 5)
found three named browser-based systems, plus non-browser work in
Word, Excel, Notepad, and a terminal. The first implementation of this
function used `browser_domain` (host:port) as the primary browser
signal, since Dataset A's Stage 5 found port-level granularity
mattered there. Running the boundary comparison against real Dataset B
data (`scripts/discover_executions_dataset_b.py`) showed that was
wrong for THIS dataset: `active_browser_tab.url` (and therefore
`browser_domain`) is frequently null even while `active_app
.window_title` clearly names one of the three known systems -- of the
~4,700 Edge events with no resolved `browser_domain`, the large
majority still carry one of the three systems' names directly in the
window title. So `window_title` is the more reliable signal here and
is checked first; `browser_domain` is kept only as a fallback for real
sites that aren't one of the three named systems (the dataset's one
`app.slack.com` case). This is the kind of "measure on this dataset's
own evidence, don't assume the earlier dataset's answer transfers"
check the project has applied throughout -- the first version of this
function was itself an unverified assumption, caught by testing it
against real data rather than trusted on first write.

The three system-name substrings below are literal strings observed in
Dataset B's own window titles (see the profile report) -- not invented
labels. A window title containing one of them is treated as that
system regardless of how many other tabs are open alongside it (Edge's
"X and N more pages" titles all still contain the front tab's name).

Browser-chrome states that are not a real business page (a restore-
session prompt, a permission dialog, an untitled/blank tab) are
excluded the same way the recording agent's own windows are --
`None` ("no system evidence"), never treated as a distinct system.

This module makes no assumption carried over from Dataset A's
segmentation architecture (V1/V2/Design 2/Combined are not imported
here) -- it only reuses the generic, dataset-agnostic `CanonicalEvent`
representation.
"""

from __future__ import annotations

from procmine.segmentation.canonical import CanonicalEvent

NOISE_APPLICATIONS = frozenset({"procmine-desktop-agent", "prl_cc"})

# Literal substrings observed in Dataset B's own window titles
# (reports/day3/dataset_b_profile.md section 5) -- not invented names.
KNOWN_SYSTEM_TITLE_MARKERS = (
    "HR人事給与システム",
    "財務会計システム",
    "受発注在庫管理システム",
)

# Browser UI states observed in Dataset B that are not a real page --
# also literal strings from the data, not guessed.
BROWSER_CHROME_NOISE_TITLES = frozenset({
    "Restore pages",
    "Turn off extensions in developer mode",
    "Translate page from Japanese?",
})


def system_identity(event: CanonicalEvent) -> str | None:
    """A single string identifying the active "system." Checks, in
    order: (1) one of the three known system names inside the window
    title, (2) known browser-chrome noise (returns `None`), (3) the
    browser domain if present (covers any other real site), (4) the
    application name otherwise. `None` for events with no active
    application, a known recording/VM noise application, or a
    browser-chrome state with no real page behind it -- `None` means
    "no system evidence," never "same system as before," so callers
    must not treat two `None`s as matching."""
    if event.application is None:
        return None
    if event.application in NOISE_APPLICATIONS:
        return None

    title = event.window_title
    if title:
        for marker in KNOWN_SYSTEM_TITLE_MARKERS:
            if marker in title:
                return f"system:{marker}"
        if title in BROWSER_CHROME_NOISE_TITLES or title.startswith("Untitled"):
            return None

    if event.browser_domain:
        return f"browser:{event.browser_domain}"
    return f"app:{event.application}"


def fill_forward(ids: list[str | None]) -> list[str | None]:
    """Replaces each `None` with the nearest preceding non-`None` value
    (a leading `None` run stays `None`, since there is nothing to carry
    forward yet). Found necessary, not assumed: measured directly on
    Dataset B that 20 of 508 no-evidence events (a recording-agent
    window, a browser dialog) sit physically between two DIFFERENT real
    systems -- without this fill, `system_change_boundaries` would
    compare each side only to the `None` in between (never a change, by
    `system_identity_changed`'s own conservative rule) and silently miss
    all 20 of those real switches. Boundary functions should call this
    once per session before comparing consecutive identities, rather
    than comparing raw `system_identity(...)` output directly."""
    filled: list[str | None] = list(ids)
    last: str | None = None
    for i, v in enumerate(filled):
        if v is None:
            filled[i] = last
        else:
            last = v
    return filled


def system_identity_changed(before: str | None, after: str | None) -> bool:
    """True only when both sides have evidence and they differ. Two
    `None`s (no evidence on either side) are NOT a "no change" --
    they're "no evidence," so this returns False for that case too
    (conservative: never claim a change without evidence), matching the
    same insufficient-evidence-defaults-to-no-boundary convention
    Design 2's Rule 4 used for Dataset A."""
    if before is None or after is None:
        return False
    return before != after
