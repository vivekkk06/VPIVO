"""Extracts a normalized document name from a Word/Excel window title.

Dataset B's own titles (`reports/day3/dataset_b_profile.md` section 5)
name real business documents directly -- e.g.
`keiyaku_kaijo_tetsuzuki  -  Compatibility Mode - Word` ("contract
termination procedure"). Word alone uses two different suffix formats
for the same "Compatibility Mode" state (` -  Compatibility Mode - Word`
and ` [Compatibility Mode] - Word`), both observed directly in the raw
data -- this function normalizes both to the same document key so the
same document isn't counted as two different ones. Transient,
non-document titles ("Resume Reading", "Opening") are excluded (`None`)
the same way browser-chrome noise is excluded from `system_identity`.
"""

from __future__ import annotations

import re

_WORD_SUFFIX_RE = re.compile(r"\s*(\[Compatibility Mode\]|-\s*Compatibility Mode)?\s*-\s*Word$")
_EXCEL_SUFFIX_RE = re.compile(r"\s*-\s*Excel$")
_NOTEPAD_SUFFIX_RE = re.compile(r"\s*-\s*Notepad$")

_TRANSIENT_TITLES = frozenset({"Resume Reading", "Opening", "Untitled", "Notepad"})

_DOCUMENT_APPS = {
    "Microsoft Word": _WORD_SUFFIX_RE,
    "Microsoft Excel": _EXCEL_SUFFIX_RE,
    "Notepad": _NOTEPAD_SUFFIX_RE,
}


def document_key(application: str | None, window_title: str | None) -> str | None:
    """`None` if there is no document identity to extract -- not a
    document-bearing application (Word/Excel/Notepad), a missing title,
    or a transient loading/reading-mode/untitled-buffer state rather
    than an actual open document. Notepad's leading `*` (its own
    unsaved-changes marker) is stripped along with the app suffix."""
    if not window_title or window_title in _TRANSIENT_TITLES:
        return None
    suffix_re = _DOCUMENT_APPS.get(application)
    if suffix_re is None:
        return None
    name = suffix_re.sub("", window_title).lstrip("*").strip()
    return name if name and name not in _TRANSIENT_TITLES else None
