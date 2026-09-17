"""Guards for the report figures.

Figures are a communication layer, so these tests check that they stay honest and
stay wired up — not that they look a particular way. The specific risks worth
guarding: a figure drifting out of sync with the report's numbers, a figure file
being referenced but missing, and the Dataset A / Dataset B distinction being lost.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIGDIR = ROOT / "reports" / "figures"
REPORT = ROOT / "reports" / "final_report.md"
README = ROOT / "README.md"

NAMES = [
    "01_end_to_end_pipeline",
    "02_segmentation_validation",
    "03_dataset_b_decision",
    "04_uncertainty_evidence_chain",
    "05_automation_safety_workflow",
]


@pytest.mark.parametrize("name", NAMES)
def test_both_formats_exist_and_are_non_trivial(name):
    svg, png = FIGDIR / f"{name}.svg", FIGDIR / f"{name}.png"
    assert svg.exists() and png.exists(), f"missing output for {name}"
    assert svg.stat().st_size > 2000, f"{name}.svg looks truncated"
    assert png.stat().st_size > 10000, f"{name}.png looks truncated"


@pytest.mark.parametrize("name", NAMES)
def test_svg_is_well_formed(name):
    """A corrupt SVG still 'exists' — parse it rather than trusting the size."""
    import xml.etree.ElementTree as ET

    root = ET.parse(FIGDIR / f"{name}.svg").getroot()
    assert root.tag.endswith("svg")
    assert root.get("viewBox"), "missing viewBox — will not scale in a report"


@pytest.mark.parametrize("name", NAMES)
def test_every_figure_is_referenced_by_the_report(name):
    assert f"figures/{name}.png" in REPORT.read_text(encoding="utf-8")


def test_readme_shows_the_primary_architecture_figure():
    assert "reports/figures/01_end_to_end_pipeline.png" in README.read_text(encoding="utf-8")


def test_every_figure_has_a_caption():
    text = REPORT.read_text(encoding="utf-8")
    captions = re.findall(r"\*\*Figure \d+\.", text)
    assert len(captions) == len(NAMES), f"expected {len(NAMES)} captions, found {len(captions)}"


def test_figures_preserve_the_dataset_a_vs_b_distinction():
    """Dashed strokes encode 'no ground truth'. Figures covering Dataset B must use them."""
    for name in ("01_end_to_end_pipeline", "03_dataset_b_decision", "04_uncertainty_evidence_chain"):
        svg = (FIGDIR / f"{name}.svg").read_text(encoding="utf-8")
        assert "stroke-dasharray" in svg, f"{name} lost the no-ground-truth encoding"
        assert "Dataset B" in svg or "Recovered executions" in svg


def test_no_figure_claims_segmentation_is_solved():
    """A figure must never imply the boundary problem was fixed."""
    forbidden = ("segmentation accuracy", "solved the", "high accuracy", "accurate segmentation")
    for name in NAMES:
        svg = (FIGDIR / f"{name}.svg").read_text(encoding="utf-8").lower()
        for phrase in forbidden:
            assert phrase not in svg, f"{name} contains {phrase!r}"


def test_rejected_experiments_are_not_shown_as_successful():
    """Figure 2 carries the rejected alternatives; they must stay labelled as rejected."""
    svg = (FIGDIR / "02_segmentation_validation.svg").read_text(encoding="utf-8")
    assert "rejected on measured evidence" in svg
    assert "imperfect foundation" in svg
    assert "NOT solved" in svg


def test_figure_numbers_match_canonical_artifacts():
    """Numbers drawn into figures must be the same ones the report is checked against."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "verify_report_numbers", ROOT / "scripts" / "verify_report_numbers.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    fig2 = (FIGDIR / "02_segmentation_validation.svg").read_text(encoding="utf-8")
    fig4 = (FIGDIR / "04_uncertainty_evidence_chain.svg").read_text(encoding="utf-8")
    rendered = {c.claim: c.rendered for c in module.build_checks()}

    # Each of these appears in a figure and must match the artifact-derived value.
    assert rendered["boundary precision"] in fig2
    assert rendered["boundary recall"] in fig2
    assert rendered["boundary F1"] in fig2
    assert rendered["fragmentation %"] in fig2
    assert rendered["HMM best F1"] in fig2
    assert rendered["boundary F1"] in fig4
    assert rendered["fragmentation %"] in fig4


def test_safety_figure_only_claims_implemented_mechanisms():
    """Every mechanism named in Figure 5 must exist in the prototype or its API."""
    svg = (FIGDIR / "05_automation_safety_workflow.svg").read_text(encoding="utf-8")
    core = (ROOT / "src/procmine/automation/hr_payroll_automation.py").read_text(encoding="utf-8")
    api = (ROOT / "scripts/serve_hr_demo_api.py").read_text(encoding="utf-8")

    assert "SAFE STOP" in svg and "AutomationSafetyError" in core
    assert "single-use token" in svg and "_CHECKPOINTS.pop" in api
    assert "422" in svg and "422" in api
    # re-verification before the click, rather than a cached reference
    assert "never cached" in svg and "re-locate" in core.lower()
