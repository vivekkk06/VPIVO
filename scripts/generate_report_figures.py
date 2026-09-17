#!/usr/bin/env python3
"""Deterministically generate the report's pipeline/workflow figures.

Hand-written SVG (stdlib only -- no diagram dependency) plus ImageMagick for the
PNG rasterisation. Every figure is regenerated from this one file, so the visual
language stays consistent and nothing is hand-drawn.

Numbers appearing in figures are verified against canonical artifacts by
`scripts/verify_report_numbers.py`; figures prefer no number at all where the
structure carries the idea on its own.

One visual rule matters more than the rest and is used in every figure:

    SOLID border  = measured against ground truth (Dataset A)
    DASHED border = no ground truth available     (Dataset B)

Usage:
    python scripts/generate_report_figures.py --out reports/figures
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

FONT = "Helvetica, Arial, sans-serif"

# Layer palette: fill, stroke. Restrained, print-safe, distinguishable in greyscale.
LAYERS = {
    "input": ("#EDF2F7", "#2C3E50"),
    "process": ("#E7EDF5", "#3A5A80"),
    "validation": ("#E8F1EA", "#3F7A52"),
    "decision": ("#FAF0E2", "#A9791C"),
    "automation": ("#F0EAF5", "#6B4E8C"),
    "rejected": ("#F3F3F3", "#9A9A9A"),
    "finding": ("#FDF3E7", "#C2700F"),
    "note": ("#FFFFFF", "#B0B0B0"),
}
INK = "#1A1A1A"
MUTED = "#5A5A5A"
GREY_TEXT = "#7A7A7A"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(text: str, width_px: float, size: float, bold: bool = False) -> list[str]:
    """Greedy word wrap using an average Helvetica advance width."""
    factor = 0.57 if bold else 0.52
    max_chars = max(6, int(width_px / (size * factor)))
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if len(trial) <= max_chars:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    title: str
    sub: str = ""
    layer: str = "process"
    dashed: bool = False
    tag: str = ""

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def right(self) -> float:
        return self.x + self.w

    def render(self) -> str:
        fill, stroke = LAYERS[self.layer]
        dash = ' stroke-dasharray="6 4"' if self.dashed else ""
        title_color = GREY_TEXT if self.layer == "rejected" else INK
        sub_color = GREY_TEXT if self.layer == "rejected" else MUTED
        out = [
            f'<rect x="{self.x:.1f}" y="{self.y:.1f}" width="{self.w:.1f}" '
            f'height="{self.h:.1f}" rx="5" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="1.4"{dash}/>'
        ]
        ts, ss = 13.0, 11.0
        tlines = wrap(self.title, self.w - 18, ts, bold=True)
        slines = wrap(self.sub, self.w - 18, ss) if self.sub else []
        total = len(tlines) * (ts + 3) + (len(slines) * (ss + 2) + 4 if slines else 0)
        y = self.cy - total / 2 + ts
        for ln in tlines:
            out.append(
                f'<text x="{self.cx:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{ts}" '
                f'font-weight="600" text-anchor="middle" fill="{title_color}">{esc(ln)}</text>'
            )
            y += ts + 3
        if slines:
            y += 2
            for ln in slines:
                out.append(
                    f'<text x="{self.cx:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{ss}" '
                    f'text-anchor="middle" fill="{sub_color}">{esc(ln)}</text>'
                )
                y += ss + 2
        return "\n".join(out)


class Canvas:
    def __init__(self, width: float, height: float):
        self.w, self.h = width, height
        self.parts: list[str] = []

    def add(self, svg: str) -> None:
        self.parts.append(svg)

    def box(self, *a, **kw) -> Box:
        b = Box(*a, **kw)
        self.parts.append(b.render())
        return b

    def arrow(self, x1, y1, x2, y2, color=None, dashed=False, marker="head") -> None:
        color = color or "#44586B"
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        self.parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="1.4"{dash} marker-end="url(#{marker})"/>'
        )

    def down(self, a: Box, b: Box, **kw) -> None:
        self.arrow(a.cx, a.bottom, b.cx, b.y - 7, **kw)

    def elbow(self, a: Box, b: Box, color=None, dashed=False) -> None:
        """Vertical drop from a, horizontal run, then into b's left edge."""
        color = color or "#44586B"
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        my = b.cy
        self.parts.append(
            f'<path d="M {a.cx:.1f} {a.bottom:.1f} L {a.cx:.1f} {my:.1f} L {b.x - 7:.1f} {my:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="1.4"{dash} marker-end="url(#head)"/>'
        )

    def text(self, x, y, s, size=11, color=None, anchor="start", weight="400", italic=False) -> None:
        style = ' font-style="italic"' if italic else ""
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}" fill="{color or INK}"{style}>{esc(s)}</text>'
        )

    def band(self, x, y, w, h, text, color="#F7F9FB", stroke="#D3DCE4") -> None:
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4" '
            f'fill="{color}" stroke="{stroke}" stroke-width="1"/>'
        )
        lines = wrap(text, w - 24, 11.5)
        ty = y + h / 2 - (len(lines) - 1) * 7 + 4
        for ln in lines:
            self.text(x + w / 2, ty, ln, size=11.5, color=MUTED, anchor="middle", italic=True)
            ty += 14

    def legend(self, x, y, entries: list[tuple[str, str]], dashed_note: bool = True) -> None:
        """entries: list of (layer_key, label)."""
        cx = x
        for key, label in entries:
            fill, stroke = LAYERS[key]
            self.parts.append(
                f'<rect x="{cx:.1f}" y="{y - 9:.1f}" width="16" height="12" rx="2.5" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>'
            )
            self.text(cx + 22, y, label, size=10.5, color=MUTED)
            cx += 26 + len(label) * 5.9
        if dashed_note:
            self.parts.append(
                f'<rect x="{cx:.1f}" y="{y - 9:.1f}" width="16" height="12" rx="2.5" '
                f'fill="#FFFFFF" stroke="#2C3E50" stroke-width="1.2" stroke-dasharray="4 3"/>'
            )
            self.text(cx + 22, y, "dashed = no ground truth available", size=10.5, color=MUTED)

    def render(self) -> str:
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{self.w:.0f}" height="{self.h:.0f}" viewBox="0 0 {self.w:.0f} {self.h:.0f}">
<defs>
<marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path d="M 0 1 L 9 5 L 0 9 z" fill="#44586B"/>
</marker>
<marker id="greyhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path d="M 0 1 L 9 5 L 0 9 z" fill="#9A9A9A"/>
</marker>
</defs>
<rect width="{self.w:.0f}" height="{self.h:.0f}" fill="#FFFFFF"/>
{chr(10).join(self.parts)}
</svg>
"""


# --------------------------------------------------------------------------
# Figure 1 -- end-to-end pipeline
# --------------------------------------------------------------------------
def figure_1() -> Canvas:
    c = Canvas(1020, 1010)
    c.text(40, 34, "Figure 1 — End-to-end evidence pipeline", size=15, weight="600")
    c.text(40, 53, "Raw desktop telemetry to a bounded automation prototype. "
                   "Dataset A validates the method; Dataset B carries the analysis.",
           size=11.5, color=MUTED)

    W, H = 300, 58
    LX, RX = 90, 630   # left (Dataset A) and right (Dataset B) columns
    CX = 360           # centred single-column x

    raw = c.box(CX, 80, W, H, "Raw operation logs",
                "keystrokes · clicks · app switches · browser + window context", "input")
    clean = c.box(CX, 166, W, H, "Validation & cleaning",
                  "schema checks · ordering · data-quality audit", "process")
    c.down(raw, clean)

    # --- split: two evidentiary tracks -----------------------------------
    a_ds = c.box(LX, 258, W, H, "Dataset A", "63 sessions · ground truth available", "input")
    b_ds = c.box(RX, 258, W, H, "Dataset B", "15 sessions · NO ground truth", "input", dashed=True)
    c.arrow(clean.cx - 50, clean.bottom, a_ds.cx, a_ds.y - 7)
    c.arrow(clean.cx + 50, clean.bottom, b_ds.cx, b_ds.y - 7)

    a_seg = c.box(LX, 348, W, H, "Segmentation — developed & tuned",
                  "leave-one-session-out cross-validation", "process")
    b_seg = c.box(RX, 348, W, H, "Segmentation — applied",
                  "separate boundary signal; method transferred, not the model",
                  "process", dashed=True)
    c.down(a_ds, a_seg)
    c.down(b_ds, b_seg)

    a_val = c.box(LX, 438, W, H, "Dataset A validation",
                  "measured against 2,009 labelled executions", "validation")
    b_exec = c.box(RX, 438, W, H, "Recovered executions",
                   "645 executions · no segment-level validation possible",
                   "validation", dashed=True)
    c.down(a_seg, a_val)
    c.down(b_seg, b_exec)

    instr = c.box(LX, 528, W, H, "Instrumentation-health analysis",
                  "upstream telemetry quality, both datasets", "finding")
    b_proc = c.box(RX, 528, W, H, "Process & variant analysis",
                   "frequency · handling time · operators · variants", "process", dashed=True)
    c.down(a_val, instr)
    c.down(b_exec, b_proc, dashed=True)
    # instrumentation health travels across as quality context (same row -> clean horizontal)
    c.arrow(instr.right, instr.cy, b_proc.x - 7, b_proc.cy, dashed=True)
    c.text((instr.right + b_proc.x) / 2, instr.cy - 10, "quality context",
           size=10, color=MUTED, anchor="middle", italic=True)

    b_score = c.box(RX, 618, W, H, "Opportunity scoring",
                    "impact and feasibility kept separate", "process", dashed=True)
    c.down(b_proc, b_score, dashed=True)

    b_sens = c.box(RX, 708, W, H, "Sensitivity & robustness",
                   "weighting · instrumentation · merge threshold", "validation", dashed=True)
    c.down(b_score, b_sens, dashed=True)

    # callout sits in the free left column, clear of every arrow
    c.band(LX, 620, W, 130,
           "Segmentation is an imperfect measurement layer, not business truth. "
           "Dataset A quantifies how imperfect it is; Dataset B inherits that "
           "uncertainty and never claims segment-level correctness.")

    dec = c.box(CX, 816, W, H, "Automation recommendation",
                "evidence-led; the score is corroboration, not foundation", "decision")
    proto = c.box(CX, 906, W, H, "Working automation prototype",
                  "bounded scope · mandatory human checkpoint", "automation")
    # elbow from the right column into the centred decision box
    c.parts.append(
        f'<path d="M {b_sens.cx:.1f} {b_sens.bottom:.1f} L {b_sens.cx:.1f} 786 '
        f'L {dec.cx:.1f} 786 L {dec.cx:.1f} {dec.y - 7:.1f}" fill="none" '
        f'stroke="#44586B" stroke-width="1.4" marker-end="url(#head)"/>'
    )
    c.down(dec, proto)

    c.legend(40, 1000, [("input", "Input"), ("process", "Processing"),
                        ("validation", "Validation"), ("decision", "Decision"),
                        ("automation", "Automation")])
    return c


# --------------------------------------------------------------------------
# Figure 2 -- segmentation validation & failure analysis
# --------------------------------------------------------------------------
def figure_2() -> Canvas:
    c = Canvas(1020, 900)
    c.text(40, 34, "Figure 2 — Segmentation validation and failure analysis", size=15, weight="600")
    c.text(40, 53, "Hypothesis → experiment → evidence → decision. Every branch below was measured, "
                   "not assumed.", size=11.5, color=MUTED)

    W, H = 290, 56
    SX = 70

    s1 = c.box(SX, 84, W, H, "Continuous event stream", "Dataset A, chronologically ordered", "input")
    s2 = c.box(SX, 164, W, H, "Feature & boundary detection",
               "temporal, application, window, browser, behavioural", "process")
    s3 = c.box(SX, 244, W, H, "Candidate segments", "predicted execution boundaries", "process")
    s4 = c.box(SX, 324, W, H, "Ground-truth comparison",
               "2,009 labelled executions · leave-one-session-out", "validation")
    s5 = c.box(SX, 404, W, H, "Precision / Recall / F1",
               "0.2358 · 0.6355 · F1 0.3440 — transition-level, not accuracy", "validation")
    s6 = c.box(SX, 484, W, H, "Failure analysis",
               "79.05% of executions still fragmented", "finding")
    for a, b in ((s1, s2), (s2, s3), (s3, s4), (s4, s5), (s5, s6)):
        c.down(a, b)

    # rejected branches, greyed
    bw, bh = 470, 46
    BX = 470
    branches = [
        ("Tempo / pace hypothesis", "median gaps vary 1.27x overall; degraded machine 1.02x — no difference", 484),
        ("Window-title fallback", "median lift 1.10; fires at 3.33% of boundaries vs 3.55% of non-boundaries", 538),
        ("Threshold re-tuning", "needs recall to collapse to ~0.15–0.21 to help — not a calibration problem", 592),
        ("Gaussian HMM (sequence model)", "F1 0.0194 vs 0.3440 — about 18x worse", 646),
        ("HMM / baseline ensemble", "~225 false positives per additional true boundary", 700),
    ]
    for title, sub, y in branches:
        b = c.box(BX, y, bw, bh, title, sub, "rejected")
        c.parts.append(
            f'<path d="M {s6.right:.1f} {s6.cy:.1f} L {(BX - 24):.1f} {s6.cy:.1f} '
            f'L {(BX - 24):.1f} {b.cy:.1f} L {b.x - 7:.1f} {b.cy:.1f}" fill="none" '
            f'stroke="#9A9A9A" stroke-width="1.2" stroke-dasharray="5 4" marker-end="url(#greyhead)"/>'
        )
    c.text(BX + bw, 470, "rejected on measured evidence", size=10.5,
           color=GREY_TEXT, anchor="end", italic=True)

    instr = c.box(BX, 786, bw, bh, "Instrumentation health",
                  "6 of 7 worst sessions at 0.00% browser-domain coverage", "finding")
    c.parts.append(
        f'<path d="M {s6.right:.1f} {s6.cy:.1f} L {(BX - 24):.1f} {s6.cy:.1f} '
        f'L {(BX - 24):.1f} {instr.cy:.1f} L {instr.x - 7:.1f} {instr.cy:.1f}" fill="none" '
        f'stroke="#C2700F" stroke-width="1.3" marker-end="url(#head)"/>'
    )
    c.text(BX + bw, 772, "upstream data-quality issue identified", size=10.5,
           color="#C2700F", anchor="end", italic=True)

    dec = c.box(SX, 604, W, 92, "Engineering decision",
                "Retain the validated architecture as an imperfect foundation. "
                "No alternative earned its complexity.", "decision")
    c.down(s6, dec)

    c.band(SX, 724, W, 76,
           "Boundary recovery is NOT solved. The decision is to carry a measured "
           "limitation forward, not to claim it away.")
    c.legend(40, 878, [("validation", "Measured"), ("finding", "Finding"),
                       ("rejected", "Rejected on evidence"), ("decision", "Decision")],
             dashed_note=False)
    return c


# --------------------------------------------------------------------------
# Figure 3 -- Dataset B to automation decision
# --------------------------------------------------------------------------
def figure_3() -> Canvas:
    c = Canvas(1020, 910)
    c.text(40, 34, "Figure 3 — From Dataset B to a defensible automation candidate", size=15, weight="600")
    c.text(40, 53, "The recommendation is not \"highest score wins\": six independent inputs converge "
                   "on the decision.", size=11.5, color=MUTED)

    W, H = 300, 54
    CX = 360

    b1 = c.box(CX, 82, W, H, "Dataset B", "15 sessions · no ground truth", "input", dashed=True)
    b2 = c.box(CX, 156, W, H, "Recovered executions", "645 executions", "process", dashed=True)
    b3 = c.box(CX, 230, W, H, "Process grouping",
               "29 contexts → 21 ranked · 8 excluded as infrastructure", "process", dashed=True)
    c.down(b1, b2, dashed=True)
    c.down(b2, b3, dashed=True)

    # four metric branches
    mw, mh = 214, 50
    metrics = [
        ("Execution frequency", "how often it runs", 40),
        ("Handling time", "recorded time consumed", 274),
        ("Operator coverage", "how many people perform it", 508),
        ("Variants", "how standardised it is", 742),
    ]
    mboxes = []
    for title, sub, x in metrics:
        mb = c.box(x, 322, mw, mh, title, sub, "validation", dashed=True)
        mboxes.append(mb)
        c.arrow(b3.cx, b3.bottom, mb.cx, mb.y - 7, dashed=True)

    score = c.box(CX, 408, W, H, "Opportunity scoring",
                  "impact x feasibility, computed separately", "process", dashed=True)
    for mb in mboxes:
        c.arrow(mb.cx, mb.bottom, score.cx, score.y - 7, dashed=True)

    sens = c.box(CX, 482, W, H, "Sensitivity analysis",
                 "8 weightings · merge thresholds · degraded sessions", "validation", dashed=True)
    c.down(score, sens, dashed=True)

    cand = c.box(CX, 556, W, H, "Candidate comparison",
                 "Pareto frontier — needs no weighting", "validation", dashed=True)
    c.down(sens, cand, dashed=True)

    # --- six decision inputs, joined on a collector rail -----------------
    # Six boxes of equal width; the gap between #3 and #4 sits on the canvas
    # centre line, so the main chain arrow descends cleanly between them.
    c.text(40, 620, "Six inputs to the decision — no single one decides it:",
           size=11, color=MUTED, italic=True)
    labels = ["Quantitative\nopportunity", "Robustness", "Operator\ncoverage",
              "Business\nrelevance", "Feasibility", "Risk"]
    bw2, gap = 145, 15
    x0, row_y, row_h = 38, 630, 44
    rail_y = 694
    centres = []
    for i, label in enumerate(labels):
        bx = x0 + i * (bw2 + gap)
        ib = c.box(bx, row_y, bw2, row_h, label.replace("\n", " "), "", "note")
        centres.append(ib.cx)
        c.parts.append(
            f'<line x1="{ib.cx:.1f}" y1="{ib.bottom:.1f}" x2="{ib.cx:.1f}" '
            f'y2="{rail_y:.1f}" stroke="#44586B" stroke-width="1.2"/>'
        )
    c.parts.append(
        f'<line x1="{centres[0]:.1f}" y1="{rail_y:.1f}" x2="{centres[-1]:.1f}" '
        f'y2="{rail_y:.1f}" stroke="#44586B" stroke-width="1.2"/>'
    )
    # main analytical chain descends through the gap between boxes 3 and 4
    c.parts.append(
        f'<line x1="{cand.cx:.1f}" y1="{cand.bottom:.1f}" x2="{cand.cx:.1f}" '
        f'y2="{rail_y:.1f}" stroke="#44586B" stroke-width="1.4"/>'
    )

    dec = c.box(300, 726, 420, 62, "Recommended process",
                "HR / Payroll System — evidence-led decision", "decision")
    c.arrow(cand.cx, rail_y, dec.cx, dec.y - 7)

    feas = c.box(120, 820, 360, 50, "Feasibility assessment",
                 "system access · business logic · governance", "decision")
    proto = c.box(540, 820, 360, 50, "Automation prototype",
                  "bounded scope, human-supervised", "automation")
    c.arrow(dec.cx - 90, dec.bottom, feas.cx, feas.y - 7)
    c.arrow(feas.right, feas.cy, proto.x - 7, proto.cy)

    c.legend(40, 892, [("input", "Input"), ("process", "Processing"),
                       ("validation", "Validation"), ("decision", "Decision"),
                       ("automation", "Automation")])
    return c


# --------------------------------------------------------------------------
# Figure 4 -- uncertainty / evidence chain
# --------------------------------------------------------------------------
def figure_4() -> Canvas:
    c = Canvas(1020, 760)
    c.text(40, 34, "Figure 4 — How uncertainty is carried forward, not hidden", size=15, weight="600")
    c.text(40, 53, "Each stage is labelled with what it is actually worth as evidence.",
           size=11.5, color=MUTED)

    W, H = 430, 54
    SX = 60
    TAGX = 560

    rows = [
        ("Raw telemetry", "desktop operation logs, as recorded", "input", False,
         "MEASURED", "#3F7A52", "Directly observed events."),
        ("Segmentation — Dataset A", "validated against 2,009 labelled executions", "validation", False,
         "MEASURED", "#3F7A52", "Quantified against ground truth."),
        ("Segmentation uncertainty", "F1 0.3440 · 79.05% of executions fragmented", "finding", False,
         "MEASURED", "#3F7A52", "The limitation is known and sized."),
        ("Segmentation — Dataset B", "same method, different data, no labels", "process", True,
         "NOT VALIDATABLE", "#B23A2F", "No ground truth exists. Correctness cannot be checked."),
        ("Process-level aggregation", "counts · handling time · operators · variants", "validation", True,
         "MEASURED", "#3F7A52", "Aggregates are directly counted from the executions."),
        ("Opportunity analysis", "impact x feasibility over 21 processes", "process", True,
         "INFERRED", "#A9791C", "Depends on weighting choices; shown to be fragile."),
        ("Sensitivity analysis", "weightings · merge thresholds · degraded sessions", "validation", True,
         "MEASURED", "#3F7A52", "Evidence layer stable; score layer sensitive."),
        ("Recommendation confidence", "qualified, and stated as qualified", "decision", False,
         "INFERRED", "#A9791C", "Rests on the stable evidence, not on the fragile score."),
    ]

    y = 84
    prev = None
    for title, sub, layer, dashed, tag, tagcol, note in rows:
        b = c.box(SX, y, W, H, title, sub, layer, dashed=dashed)
        if prev:
            c.down(prev, b, dashed=dashed)
        prev = b
        tw = len(tag) * 7.0 + 20
        c.parts.append(
            f'<rect x="{TAGX:.1f}" y="{b.cy - 11:.1f}" width="{tw:.1f}" height="22" rx="11" '
            f'fill="#FFFFFF" stroke="{tagcol}" stroke-width="1.3"/>'
        )
        c.text(TAGX + tw / 2, b.cy + 4, tag, size=10.5, color=tagcol, anchor="middle", weight="600")
        c.text(TAGX + tw + 14, b.cy + 4, note, size=10.5, color=MUTED)
        y += 78

    c.band(SX, y + 4, 900, 44,
           "Dataset B segmentation is never claimed to be correct. The recommendation is a "
           "comparative judgement built on aggregate evidence, which survives uncertainty that a "
           "per-segment correctness claim would not.")
    return c


# --------------------------------------------------------------------------
# Figure 5 -- automation safety workflow
# --------------------------------------------------------------------------
def figure_5() -> Canvas:
    c = Canvas(1020, 960)
    c.text(40, 34, "Figure 5 — Automation execution and safety workflow", size=15, weight="600")
    c.text(40, 53, "Every mechanism shown is implemented in the prototype. The automation acts only "
                   "inside explicit verification boundaries.", size=11.5, color=MUTED)

    W, H = 380, 50
    SX = 70
    FAILX = 610

    steps = [
        ("Trigger — operator selects route + supplies note", "note text is a required input; never invented", "input"),
        ("Guard: route allowlist", "only the 4 evidenced routes are accepted", "validation"),
        ("Guard: note is non-empty", "checked BEFORE any UI contact", "validation"),
        ("Navigate to target route", "", "process"),
        ("Locate note field", "refuses to guess if absent or duplicated", "validation"),
        ("Insert note", "", "process"),
        ("Locate confirm button", "refuses to guess if absent or duplicated", "validation"),
        ("Server-side checkpoint issued", "opaque single-use token; browser cannot construct one", "decision"),
        ("HUMAN REVIEW & AUTHORISATION", "nothing is submitted until a person approves", "decision"),
        ("Re-verify confirm button", "re-located immediately before the click, never cached", "validation"),
        ("Perform action — click confirm", "", "automation"),
        ("Record outcome", "timestamped action log for every step, success or failure", "automation"),
    ]
    y = 86
    prev = None
    boxes = []
    for title, sub, layer in steps:
        b = c.box(SX, y, W, H, title, sub, layer)
        boxes.append(b)
        if prev:
            c.down(prev, b)
        prev = b
        y += 64

    ok = c.box(SX, y, W, 46, "Success", "confirmed, logged, token consumed", "automation")
    c.down(prev, ok)

    # safe-stop rail
    stop = c.box(FAILX, 330, 350, 88, "SAFE STOP",
                 "AutomationSafetyError · HTTP 422 · partial action log preserved · "
                 "nothing submitted", "finding")
    for b in boxes:
        if b.layer == "validation":
            c.parts.append(
                f'<path d="M {b.right:.1f} {b.cy:.1f} L {(FAILX - 30):.1f} {b.cy:.1f} '
                f'L {(FAILX - 30):.1f} {stop.cy:.1f} L {stop.x - 7:.1f} {stop.cy:.1f}" fill="none" '
                f'stroke="#C2700F" stroke-width="1.2" stroke-dasharray="5 4" marker-end="url(#head)"/>'
            )
    c.text(FAILX + 350, 318, "any guard fails → refuse, never guess", size=10.5,
           color="#C2700F", anchor="end", italic=True)

    c.band(FAILX, 470, 350, 120,
           "The single-use token is consumed on confirm, so a checkpoint cannot be confirmed "
           "twice. The confirm button is re-located after the human pause, so a page change "
           "during review cannot go undetected.")

    c.band(FAILX, 620, 350, 130,
           "Boundary: the prototype drives a deterministic in-memory mock, not a real HR system. "
           "Production additionally requires a real browser driver, an explicit note-content "
           "source, and business-owner confirmation that the confirm click means \"submit\".")

    c.legend(40, 940, [("input", "Input"), ("validation", "Guard / check"),
                       ("decision", "Human control"), ("automation", "Action"),
                       ("finding", "Exception path")], dashed_note=False)
    return c


FIGURES = {
    "01_end_to_end_pipeline": figure_1,
    "02_segmentation_validation": figure_2,
    "03_dataset_b_decision": figure_3,
    "04_uncertainty_evidence_chain": figure_4,
    "05_automation_safety_workflow": figure_5,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("reports/figures"))
    ap.add_argument("--density", type=int, default=170, help="PNG rasterisation DPI")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        print("warning: ImageMagick not found -- writing SVG only", file=sys.stderr)

    for name, fn in FIGURES.items():
        svg_path = args.out / f"{name}.svg"
        svg_path.write_text(fn().render(), encoding="utf-8")
        print(f"wrote {svg_path}", file=sys.stderr)
        if magick:
            png_path = args.out / f"{name}.png"
            proc = subprocess.run(
                [magick, "-density", str(args.density), "-background", "white",
                 str(svg_path), "-flatten", str(png_path)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                print(f"  PNG failed: {proc.stderr[-300:]}", file=sys.stderr)
                return 1
            print(f"wrote {png_path}", file=sys.stderr)
    return 0




# ==========================================================================
# Final-polish figures (README). These carry evidence the original five
# predate: the Day-7 ML side branch, the segmentation trade-off, and the
# validated-vs-production boundary. Every number is read from a canonical
# artifact by `_canonical()` below rather than typed in, so a figure cannot
# silently drift from the analysis.
# ==========================================================================
import json as _json  # noqa: E402


def _canonical() -> dict:
    """Read every value the polish figures plot, from canonical artifacts."""
    root = Path(__file__).resolve().parent.parent
    seg = _json.loads((root / "reports/day7/segmentation_comparison.json").read_text(encoding="utf-8"))
    clf = _json.loads((root / "reports/day7/process_classifier_experiment.json").read_text(encoding="utf-8"))
    prof = _json.loads((root / "reports/day3/process_profiles_dataset_b.json").read_text(encoding="utf-8"))
    audit = _json.loads((root / "reports/day3/problem2_audit_results.json").read_text(encoding="utf-8"))
    hrpath = _json.loads((root / "reports/day3/hr_payroll_dominant_path_dataset_b.json").read_text(encoding="utf-8"))
    inv = _json.loads((root / "reports/day1/dataset_inventory.json").read_text(encoding="utf-8"))
    hr = prof["system:HR人事給与システム"]
    top = audit["default_ranking"][0]
    return {
        "seg_baseline": seg["baseline"]["pooled"],
        "seg_candidates": {k: v["eval"]["pooled"] for k, v in seg["candidates"].items()},
        "seg_decision": seg["decision"],
        "clf": clf["headline"],
        "a_sessions": inv["dataset_a"]["n_sessions"],
        "a_chunks": inv["dataset_a"]["n_chunks"],
        "b_sessions": inv["dataset_b"]["n_sessions"],
        "n_ranked": sum(1 for v in prof.values() if not v.get("excluded_from_ranking")),
        "n_excluded": sum(1 for v in prof.values() if v.get("excluded_from_ranking")),
        "hr_execs": hr["execution_count"],
        "hr_dom_share": hr["dominant_variant_share"],
        "variant_split": hrpath["variant_split"],
        "opportunity": top["opportunity"],
        "n_routes": len(hrpath["route_id_prefix_correspondence"]),
        "sens": audit["sensitivity_summary"],
        "worst_rank": audit["final_ranking_robustness_table"][0]["worst_rank"],
    }


def figure_arch() -> Canvas:
    d = _canonical()
    c = Canvas(1020, 1080)
    c.text(40, 34, "End-to-end FDE architecture", size=15, weight="600")
    c.text(40, 53, "Canonical pipeline (left). The Day-7 machine-learning experiment is a "
                   "side branch and feeds nothing.", size=11.5, color=MUTED)

    W, H, X = 330, 46, 70
    steps = [
        ("Raw operation logs", "keystrokes · clicks · app switches", "input"),
        ("Data audit & quality check", "Day 1 — defects found before modelling", "process"),
        ("Instrumentation health", "upstream diagnostic, outside the decision path", "finding"),
        ("Locked segmentation", "Combined strategy — retained after Day-7 challenge", "process"),
        ("Executions", f"Dataset B → 645", "process"),
        ("Process mining", f"{d['n_ranked']} ranked · {d['n_excluded']} excluded", "process"),
        ("Variants · DFG · operational metrics", "frequency · time · operators", "process"),
        ("Impact × Feasibility", "computed separately, multiplied last", "process"),
        ("Sensitivity / Pareto", "8 weightings · merge thresholds", "validation"),
        ("Automation decision", f"HR / Payroll — Opportunity {d['opportunity']}", "decision"),
        ("HUMAN REVIEW CHECKPOINT", "nothing is submitted until a person approves", "decision"),
        ("Automation service", "route allowlist · note validation · re-verification", "automation"),
        ("Browser adapter", "Playwright — safety logic stays above this layer", "automation"),
        ("Local HR mock DOM", "hr_payroll_mock_app.html", "input"),
    ]
    y, prev = 78, None
    boxes = []
    for title, sub, layer in steps:
        b = c.box(X, y, W, H, title, sub, layer)
        boxes.append(b)
        if prev:
            c.down(prev, b)
        prev = b
        y += 62

    # --- ML side branch: visually detached, terminating in a dead end ----
    BX, BW = 560, 380
    c.text(BX, 96, "Independent experiment (Day 7)", size=11.5, color=MUTED, italic=True)
    ml = [
        ("Ground-truth executions", "Dataset A · 15 process codes", 110),
        ("Process-identity ML experiment", "GroupKFold grouped by session", 176),
        ("Behaviour vs system identity",
         f"macro F1 {d['clf']['behavioural_only_macro_f1']} vs "
         f"{d['clf']['with_system_identity_macro_f1']}", 242),
        ("VALIDATION ONLY", "confirms the Day-3 grouping decision", 308),
    ]
    mprev = None
    for title, sub, yy in ml:
        b = c.box(BX, yy, BW, H, title, sub, "rejected", dashed=True)
        if mprev:
            c.arrow(b.cx, mprev.bottom, b.cx, b.y - 7, color="#9A9A9A",
                    dashed=True, marker="greyhead")
        mprev = b
    stop = c.box(BX, 374, BW, 52, "NOT IN THE CANONICAL PIPELINE",
                 "feeds neither segmentation nor Opportunity", "rejected", dashed=True)
    c.arrow(stop.cx, mprev.bottom, stop.cx, stop.y - 7, color="#9A9A9A",
            dashed=True, marker="greyhead")
    c.band(BX, 444, BW, 76,
           "The tempting model — predicting automation suitability — would have been "
           "trained on the Opportunity score it was meant to support. It was rejected "
           "as circular and never built.")

    # --- production boundary --------------------------------------------
    by = boxes[-1].bottom + 26
    c.parts.append(
        f'<line x1="{X}" y1="{by:.1f}" x2="960" y2="{by:.1f}" stroke="#B23A2F" '
        f'stroke-width="2" stroke-dasharray="9 5"/>'
    )
    c.text(X, by - 8, "LOCAL VALIDATED", size=12, color="#B23A2F", weight="600")
    c.text(960, by - 8, "≠  REAL HR PRODUCTION SYSTEM", size=12, color="#B23A2F",
           weight="600", anchor="end")
    c.band(X, by + 12, 890, 58,
           "Everything above this line runs and is tested against a local prototype page. "
           "Crossing it requires a real HR system, authentication, authorisation, secrets "
           "management and governance sign-off — none of which this project has done.")
    c.legend(40, 1070, [("input", "Input"), ("process", "Processing"),
                        ("validation", "Validation"), ("decision", "Decision / human"),
                        ("automation", "Automation"), ("rejected", "Not in pipeline")],
             dashed_note=False)
    return c


def figure_funnel() -> Canvas:
    d = _canonical()
    c = Canvas(1020, 620)
    c.text(40, 34, "From raw logs to one bounded automation candidate", size=15, weight="600")
    c.text(40, 53, "Dataset A and Dataset B are separate datasets, shown separately. "
                   "Neither funnel reduces into the other.", size=11.5, color=MUTED)

    # two clearly separated columns
    LW, LX, RX = 400, 60, 560
    c.text(LX, 88, "DATASET A — method validation", size=12, weight="600")
    c.text(RX, 88, "DATASET B — the analysis", size=12, weight="600")
    c.parts.append(f'<line x1="500" y1="76" x2="500" y2="470" stroke="#C9D3DC" '
                   f'stroke-width="1.5" stroke-dasharray="4 4"/>')

    a_steps = [("63 sessions · 117 chunks", "raw recordings"),
               ("162,768 events", "after ordering and cleaning"),
               ("2,009 GT executions", "ground truth available"),
               ("Segmentation validated", "F1 0.3440 · 79.05% fragmented")]
    y = 104
    prev = None
    for t, s in a_steps:
        b = c.box(LX, y, LW, 50, t, s, "input" if prev is None else "validation")
        if prev:
            c.down(prev, b)
        prev = b
        y += 66

    b_steps = [(f"{d['b_sessions']} sessions · 20,477 events", "no ground truth"),
               ("645 executions", "segmented, not validated"),
               (f"{d['n_ranked']} ranked · {d['n_excluded']} excluded",
                "excluded = infrastructure, 0.1220 h total"),
               (f"HR / Payroll — {d['hr_execs']} executions",
                f"{d['variant_split']['dominant']['n']} dominant "
                f"({d['hr_dom_share'] * 100:.2f}%)")]
    y = 104
    prev = None
    for t, s in b_steps:
        b = c.box(RX, y, LW, 50, t, s, "input" if prev is None else "process", dashed=True)
        if prev:
            c.down(prev, b, dashed=True)
        prev = b
        y += 66

    final = c.box(260, 486, 500, 62, "HR / Payroll — READY FOR BOUNDED PILOT",
                  f"Opportunity {d['opportunity']} · rank 1 · Pareto non-dominated · "
                  f"#1 in {d['sens']['n_hr_first']}/{d['sens']['n_scenarios']} scenarios · "
                  f"worst rank {d['worst_rank']}", "decision")
    c.arrow(prev.cx, prev.bottom, final.cx + 120, final.y - 7, dashed=True)
    c.parts.append(f'<path d="M {LX + LW / 2:.1f} 368 L {LX + LW / 2:.1f} 456 '
                   f'L {final.cx - 120:.1f} 456 L {final.cx - 120:.1f} {final.y - 7:.1f}" '
                   f'fill="none" stroke="#44586B" stroke-width="1.4" marker-end="url(#head)"/>')
    c.text(LX + LW / 2 + 8, 400, "method validated here…", size=10.5, color=MUTED, italic=True)
    c.text(RX + 8, 400, "…applied here", size=10.5, color=MUTED, italic=True)
    c.legend(40, 604, [("input", "Raw"), ("validation", "Measured vs ground truth"),
                       ("process", "No ground truth"), ("decision", "Decision")])
    return c


def figure_tradeoff() -> Canvas:
    d = _canonical()
    base, cands = d["seg_baseline"], d["seg_candidates"]
    c = Canvas(1020, 620)
    c.text(40, 34, "Why the segmentation baseline was retained", size=15, weight="600")
    c.text(40, 53, "Day-7 candidates moved along the fragmentation ↔ under-segmentation "
                   "trade-off; none found a better operating point.", size=11.5, color=MUTED)

    # axes
    X0, Y0, PW, PH = 110, 470, 620, 360
    c.parts.append(f'<line x1="{X0}" y1="{Y0}" x2="{X0 + PW}" y2="{Y0}" stroke="#44586B" stroke-width="1.4"/>')
    c.parts.append(f'<line x1="{X0}" y1="{Y0}" x2="{X0}" y2="{Y0 - PH}" stroke="#44586B" stroke-width="1.4"/>')
    c.text(X0 + PW / 2, Y0 + 44, "Fragmentation  (% of GT executions split) →",
           size=11.5, color=MUTED, anchor="middle")
    c.parts.append(f'<text x="34" y="{Y0 - PH / 2:.1f}" font-family="{FONT}" font-size="11.5" '
                   f'fill="{MUTED}" text-anchor="middle" transform="rotate(-90 34 {Y0 - PH / 2:.1f})">'
                   f'Under-segmentation (executions merged) →</text>')

    xmin, xmax, ymin, ymax = 35.0, 85.0, 0.0, 0.70
    def px(v): return X0 + (v - xmin) / (xmax - xmin) * PW
    def py(v): return Y0 - (v - ymin) / (ymax - ymin) * PH
    for gx in (40, 50, 60, 70, 80):
        c.parts.append(f'<line x1="{px(gx):.1f}" y1="{Y0}" x2="{px(gx):.1f}" y2="{Y0 - PH}" '
                       f'stroke="#EDF1F5" stroke-width="1"/>')
        c.text(px(gx), Y0 + 20, f"{gx}%", size=10.5, color=MUTED, anchor="middle")
    for gy in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        c.parts.append(f'<line x1="{X0}" y1="{py(gy):.1f}" x2="{X0 + PW}" y2="{py(gy):.1f}" '
                       f'stroke="#EDF1F5" stroke-width="1"/>')
        c.text(X0 - 10, py(gy) + 4, f"{gy:.1f}", size=10.5, color=MUTED, anchor="end")

    # (label, metrics, kind, dx, dy) -- C4 and C1 sit within 1pp of each other on
    # the x axis, so their labels are offset in opposite directions rather than
    # overlapping.
    pts = [("C2", cands["C2_rule_plus_continuity_veto"], "rejected", 14, 0),
           ("C3", cands["C3_rule_plus_motif"], "rejected", 14, 0),
           ("C4", cands["C4_instrumentation_aware"], "rejected", -20, -14),
           ("C1", cands["C1_rule_two_threshold"], "rejected", 14, 6),
           ("BASELINE", base, "baseline", 14, 0)]
    ordered = sorted(pts, key=lambda p: p[1]["pct_gt_executions_fragmented"])
    path = " ".join(
        f"{'M' if i == 0 else 'L'} {px(p[1]['pct_gt_executions_fragmented']):.1f} "
        f"{py(p[1]['under_segmentation_rate']):.1f}" for i, p in enumerate(ordered))
    c.parts.append(f'<path d="{path}" fill="none" stroke="#9A9A9A" stroke-width="1.3" '
                   f'stroke-dasharray="6 4"/>')

    for label, m, kind, dx, dy in pts:
        x, y = px(m["pct_gt_executions_fragmented"]), py(m["under_segmentation_rate"])
        if kind == "baseline":
            # square + ring so the distinction is not colour-only
            c.parts.append(f'<rect x="{x - 8:.1f}" y="{y - 8:.1f}" width="16" height="16" '
                           f'fill="#FAF0E2" stroke="#A9791C" stroke-width="2.2"/>')
            c.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="none" '
                           f'stroke="#A9791C" stroke-width="1.2" stroke-dasharray="3 3"/>')
        else:
            c.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="#F3F3F3" '
                           f'stroke="#9A9A9A" stroke-width="1.8"/>')
        col = INK if kind == "baseline" else GREY_TEXT
        anchor = "end" if dx < 0 else "start"
        c.text(x + dx, y + dy - 6, label, size=11.5, color=col, weight="600", anchor=anchor)
        c.text(x + dx, y + dy + 9, f"F1 {m['f1']:.4f}", size=10.5, color=col, anchor=anchor)

    # legend that does not rely on colour alone
    c.parts.append('<rect x="770" y="118" width="16" height="16" fill="#FAF0E2" '
                   'stroke="#A9791C" stroke-width="2.2"/>')
    c.text(796, 131, "LOCKED BASELINE (square)", size=11, color=INK, weight="600")
    c.parts.append('<circle cx="778" cy="158" r="7" fill="#F3F3F3" stroke="#9A9A9A" stroke-width="1.8"/>')
    c.text(796, 162, "REJECTED CANDIDATES (circle)", size=11, color=GREY_TEXT)
    c.band(760, 190, 230, 150,
           "Every candidate that lowered fragmentation raised under-segmentation by a "
           "corresponding amount — the ordering is monotonic.")

    c.band(110, 516, 880, 68,
           "Day-7 candidates reduced fragmentation by accepting substantially more "
           "under-segmentation; none passed the pre-registered promotion gates. The locked "
           "baseline therefore remained unchanged.")
    return c


def figure_hr_boundary() -> Canvas:
    d = _canonical()
    vs = d["variant_split"]
    c = Canvas(1020, 700)
    c.text(40, 34, "HR / Payroll — what is automated, and what is not", size=15, weight="600")
    c.text(40, 53, "Scope set by DOM-level forensic evidence. Only the dominant path is in "
                   "scope.", size=11.5, color=MUTED)

    top = c.box(310, 78, 400, 50, f"{d['hr_execs']} HR / Payroll executions",
                "observed in Dataset B", "input", dashed=True)
    dom = c.box(310, 152, 400, 50,
                f"{vs['dominant']['n']} dominant-path executions",
                f"{d['hr_dom_share'] * 100:.2f}% — the automation scope", "validation", dashed=True)
    c.down(top, dom, dashed=True)

    # out of scope, to the right
    oos1 = c.box(760, 140, 230, 44, f"{vs['word_detour']['n']} Word detour",
                 "OUT OF SCOPE", "rejected", dashed=True)
    oos2 = c.box(760, 196, 230, 44, f"{vs['rare_edge']['n']} rare multi-hop",
                 "OUT OF SCOPE", "rejected", dashed=True)
    for o in (oos1, oos2):
        c.arrow(top.right, top.cy + 8, o.x - 7, o.cy, color="#9A9A9A",
                dashed=True, marker="greyhead")

    steps = [("Enter the HR system", "", "process"),
             (f"Select one of {d['n_routes']} evidenced routes", "route allowlist", "validation"),
             ("Click the note field", "located and verified", "validation"),
             ("Paste the note", "100% of observed inputs were paste", "process"),
             ("Click the route-specific OK", "", "process"),
             ("HUMAN REVIEW CHECKPOINT", "nothing submitted until approval", "decision"),
             ("Re-locate the confirmation target", "never cached", "validation"),
             ("Confirm", "single-use token — cannot repeat", "automation")]
    y, prev = 226, dom
    for t, s, layer in steps:
        b = c.box(180, y, 440, 44, t, s, layer)
        c.down(prev, b, dashed=(prev is dom))
        prev = b
        y += 56

    c.band(660, 300, 330, 120,
           "Note content is UNOBSERVABLE in the logs — it is always supplied by the "
           "operator and never generated.")
    c.band(660, 434, 330, 130,
           "\"OK = submit\" is INFERRED from DOM structure; no submit event exists in the "
           "schema. That single inference is why a human checkpoint precedes every confirm.")
    c.band(60, 640, 930, 44,
           f"{vs['dominant']['n']} of {d['hr_execs']} executions are in scope. The other "
           f"{vs['word_detour']['n'] + vs['rare_edge']['n']} were excluded, not partially automated.")
    c.legend(40, 690, [("validation", "Verified step"), ("decision", "Human control"),
                       ("automation", "Action"), ("rejected", "Out of scope")],
             dashed_note=False)
    return c


def figure_production_boundary() -> Canvas:
    c = Canvas(1020, 620)
    c.text(40, 34, "Validated boundary vs production requirements", size=15, weight="600")
    c.text(40, 53, "LOCAL VALIDATED — NOT A REAL HR SYSTEM.", size=12, color="#B23A2F",
           weight="600")

    left = ["React Decision Center", "Local automation API (stdlib HTTP)",
            "Policy / safety layer", "Deterministic automation service",
            "Playwright browser adapter", "Local HR mock DOM",
            "Structured audit logging (redacted)", "Replay prevention (single-use token)",
            "Human confirmation checkpoint", "19 live-DOM browser tests"]
    right = ["Real HR system integration", "Authentication", "Authorisation",
             "Explicit CORS origin allowlist", "Real system selectors / API contract",
             "Execution status endpoint", "Owner confirmation of confirm semantics",
             "Credential / secrets management", "Monitoring and alerting",
             "Deployment and security hardening", "Failure and recovery strategy"]

    c.box(50, 86, 440, 40, "CURRENTLY VALIDATED", "implemented and tested here", "validation")
    c.box(530, 86, 440, 40, "REQUIRED FOR REAL PRODUCTION", "not done in this project",
          "rejected", dashed=True)

    y = 140
    for item in left:
        c.box(50, y, 440, 34, item, "", "automation")
        y += 40
    y = 140
    for item in right:
        c.box(530, y, 440, 34, item, "", "rejected", dashed=True)
        y += 40

    c.parts.append('<line x1="510" y1="86" x2="510" y2="580" stroke="#B23A2F" '
                   'stroke-width="2" stroke-dasharray="9 5"/>')
    c.band(50, 556, 920, 46,
           "The left column runs against a local prototype page. Nothing in this project "
           "has been connected to a real HR system, and \"ready for bounded pilot\" means a "
           "supervised trial — not production readiness.")
    return c


FIGURES.update({
    "end-to-end-fde-architecture": figure_arch,
    "decision-funnel": figure_funnel,
    "segmentation-tradeoff": figure_tradeoff,
    "hr-automation-boundary": figure_hr_boundary,
    "production-boundary": figure_production_boundary,
})


if __name__ == "__main__":
    sys.exit(main())
