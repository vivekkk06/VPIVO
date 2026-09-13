"""Problem 2 investigation: Directly-Follows Graph (DFG) over trace
abstractions.

`count(a -> b)` and `P(b | a) = count(a -> b) / count(a)`, computed by
pooling every consecutive pair within every trace passed in -- the
standard, minimal DFG construction (Directly-Follows relation) used as
a complement to (not a replacement for) the exact-match variant
grouping `variant_analysis.variant_signature` already provides: the
DFG reveals branch/loop/detour structure *across* variants that a
purely exact-match grouping can't show (e.g., how often a process
"loops" on itself, or which activity most often follows a detour).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass
class DFGEdge:
    source: str
    target: str
    count: int
    probability: float  # P(target | source) = count / count(source as origin)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def build_dfg(traces: list[tuple]) -> list[DFGEdge]:
    """One edge per distinct (source, target) pair observed as
    consecutive tokens in any trace, sorted by descending count (the
    most common transitions first). An empty or single-token trace
    contributes no edges."""
    edge_counts: Counter = Counter()
    source_counts: Counter = Counter()
    for trace in traces:
        for i in range(len(trace) - 1):
            a, b = trace[i], trace[i + 1]
            edge_counts[(a, b)] += 1
            source_counts[a] += 1
    edges = [
        DFGEdge(source=a, target=b, count=count, probability=count / source_counts[a])
        for (a, b), count in edge_counts.items()
    ]
    edges.sort(key=lambda e: (-e.count, e.source, e.target))
    return edges


def self_loops(edges: list[DFGEdge]) -> list[DFGEdge]:
    """Edges where source == target -- a token directly followed by
    itself (rework/repetition within the same activity)."""
    return [e for e in edges if e.source == e.target]


def start_activities(traces: list[tuple]) -> Counter:
    return Counter(t[0] for t in traces if t)


def end_activities(traces: list[tuple]) -> Counter:
    return Counter(t[-1] for t in traces if t)


def dominant_successor(edges: list[DFGEdge], source: str) -> DFGEdge | None:
    """The single highest-probability outgoing edge from `source`, or
    `None` if `source` has no outgoing edges in this DFG."""
    outgoing = [e for e in edges if e.source == source]
    if not outgoing:
        return None
    return max(outgoing, key=lambda e: e.probability)
