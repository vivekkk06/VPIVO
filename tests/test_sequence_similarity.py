from __future__ import annotations

from procmine.process_discovery.sequence_similarity import (
    jaccard_similarity,
    lcs_length,
    lcs_similarity,
    levenshtein_distance,
    normalized_levenshtein_similarity,
)


# --- levenshtein -------------------------------------------------------

def test_levenshtein_identical_sequences_is_zero():
    assert levenshtein_distance(("A", "B", "C"), ("A", "B", "C")) == 0


def test_levenshtein_one_substitution():
    assert levenshtein_distance(("A", "B", "C"), ("A", "X", "C")) == 1


def test_levenshtein_one_insertion():
    assert levenshtein_distance(("A", "B"), ("A", "X", "B")) == 1


def test_levenshtein_against_empty_sequence():
    assert levenshtein_distance((), ("A", "B")) == 2
    assert levenshtein_distance(("A", "B"), ()) == 2
    assert levenshtein_distance((), ()) == 0


def test_normalized_levenshtein_similarity_identical_is_one():
    assert normalized_levenshtein_similarity(("A", "B"), ("A", "B")) == 1.0


def test_normalized_levenshtein_similarity_both_empty_is_one():
    assert normalized_levenshtein_similarity((), ()) == 1.0


def test_normalized_levenshtein_similarity_completely_different():
    # two single-token sequences that share nothing -> distance 1, max len 1 -> sim 0
    assert normalized_levenshtein_similarity(("A",), ("B",)) == 0.0


def test_normalized_levenshtein_similarity_matches_hr_dominant_vs_word_detour_example():
    # mirrors the assignment's own worked example: dominant path vs a
    # single-word-detour variant of the same underlying process
    dominant = ("HR", "note", "paste", "confirm")
    detour = ("HR", "Word", "copy", "note", "paste", "confirm")
    sim = normalized_levenshtein_similarity(dominant, detour)
    assert 0.0 < sim < 1.0  # related but not identical


# --- LCS -----------------------------------------------------------------

def test_lcs_length_identical_sequences():
    assert lcs_length(("A", "B", "C"), ("A", "B", "C")) == 3


def test_lcs_length_subsequence_match():
    assert lcs_length(("A", "B", "C", "D"), ("A", "C", "D")) == 3


def test_lcs_similarity_identical_is_one():
    assert lcs_similarity(("A", "B"), ("A", "B")) == 1.0


def test_lcs_similarity_both_empty_is_one():
    assert lcs_similarity((), ()) == 1.0


def test_lcs_similarity_one_empty_is_zero():
    assert lcs_similarity((), ("A",)) == 0.0
    assert lcs_similarity(("A",), ()) == 0.0


def test_lcs_similarity_hr_dominant_vs_word_detour():
    dominant = ("HR", "note", "paste", "confirm")
    detour = ("HR", "Word", "copy", "note", "paste", "confirm")
    sim = lcs_similarity(dominant, detour)
    # all 4 dominant-path tokens appear, in order, inside the detour trace
    assert lcs_length(dominant, detour) == 4
    assert sim == 2 * 4 / (4 + 6)


# --- Jaccard ---------------------------------------------------------------

def test_jaccard_similarity_identical_sets():
    assert jaccard_similarity(("A", "B"), ("B", "A")) == 1.0  # order-insensitive


def test_jaccard_similarity_disjoint_sets():
    assert jaccard_similarity(("A",), ("B",)) == 0.0


def test_jaccard_similarity_partial_overlap():
    assert jaccard_similarity(("A", "B"), ("B", "C")) == 1 / 3


def test_jaccard_similarity_both_empty_is_none_not_zero():
    assert jaccard_similarity((), ()) is None


def test_jaccard_ignores_repetition_unlike_levenshtein_and_lcs():
    a = ("A", "A", "A")
    b = ("A",)
    assert jaccard_similarity(a, b) == 1.0  # same set {"A"}
    assert normalized_levenshtein_similarity(a, b) < 1.0  # different sequence length/content
