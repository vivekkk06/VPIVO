from __future__ import annotations

from procmine.process_discovery.directly_follows_graph import (
    build_dfg,
    dominant_successor,
    end_activities,
    self_loops,
    start_activities,
)


def test_build_dfg_counts_transitions_across_traces():
    traces = [("A", "B", "C"), ("A", "B", "D")]
    edges = build_dfg(traces)
    by_pair = {(e.source, e.target): e for e in edges}
    assert by_pair[("A", "B")].count == 2
    assert by_pair[("B", "C")].count == 1
    assert by_pair[("B", "D")].count == 1


def test_build_dfg_probability_is_conditional_on_source():
    traces = [("A", "B"), ("A", "B"), ("A", "C")]
    edges = build_dfg(traces)
    by_pair = {(e.source, e.target): e for e in edges}
    assert by_pair[("A", "B")].probability == 2 / 3
    assert by_pair[("A", "C")].probability == 1 / 3


def test_build_dfg_sorted_by_descending_count():
    traces = [("A", "B"), ("A", "B"), ("A", "C")]
    edges = build_dfg(traces)
    assert edges[0].count >= edges[1].count


def test_build_dfg_empty_and_single_token_traces_contribute_no_edges():
    traces = [(), ("A",), ("A", "B")]
    edges = build_dfg(traces)
    assert len(edges) == 1
    assert (edges[0].source, edges[0].target) == ("A", "B")


def test_self_loops_detects_a_directly_repeated_token():
    traces = [("A", "A", "B")]
    edges = build_dfg(traces)
    loops = self_loops(edges)
    assert len(loops) == 1
    assert loops[0].source == loops[0].target == "A"


def test_self_loops_empty_when_no_repetition():
    traces = [("A", "B", "C")]
    edges = build_dfg(traces)
    assert self_loops(edges) == []


def test_start_and_end_activities():
    traces = [("A", "B", "C"), ("A", "D")]
    assert start_activities(traces) == {"A": 2}
    ends = end_activities(traces)
    assert ends["C"] == 1 and ends["D"] == 1


def test_start_end_activities_skip_empty_traces():
    traces = [(), ("A", "B")]
    assert start_activities(traces) == {"A": 1}
    assert end_activities(traces) == {"B": 1}


def test_dominant_successor_picks_highest_probability_edge():
    traces = [("A", "B"), ("A", "B"), ("A", "C")]
    edges = build_dfg(traces)
    dom = dominant_successor(edges, "A")
    assert dom.target == "B"


def test_dominant_successor_none_for_unknown_source():
    edges = build_dfg([("A", "B")])
    assert dominant_successor(edges, "Z") is None


def test_dfg_reflects_hr_dominant_vs_detour_structure():
    # 3 dominant-path traces (pure HR), 1 word-detour trace
    traces = [("HR",), ("HR",), ("HR",), ("HR", "Word", "HR")]
    edges = build_dfg(traces)
    by_pair = {(e.source, e.target): e for e in edges}
    assert by_pair[("HR", "Word")].count == 1
    assert by_pair[("Word", "HR")].count == 1
    # HR is the overwhelmingly dominant start activity
    assert start_activities(traces)["HR"] == 4
