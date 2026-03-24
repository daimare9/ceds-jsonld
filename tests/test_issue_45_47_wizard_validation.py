"""Tests for wizard validation bugs — issues #45 and #47.

#45: LLM confidence values not clamped to [0,1]
#47: ColumnProfiler misclassifies NaN/Infinity strings as float type
"""

from __future__ import annotations

import math

import pytest

from ceds_jsonld.wizard.profiler import ColumnProfiler, _infer_type


# ---------------------------------------------------------------------------
# Issue #47 — NaN/Infinity type inference
# ---------------------------------------------------------------------------


class TestNaNInfinityTypeInference:
    """ColumnProfiler should classify NaN/Infinity strings as 'string', not 'float'."""

    def test_nan_only_column_is_string(self) -> None:
        assert _infer_type(["NaN", "NaN", "NaN"]) == "string"

    def test_infinity_only_column_is_string(self) -> None:
        assert _infer_type(["Infinity", "Infinity"]) == "string"

    def test_neg_infinity_only_column_is_string(self) -> None:
        assert _infer_type(["-Infinity", "-Infinity"]) == "string"

    def test_mixed_special_floats_is_string(self) -> None:
        assert _infer_type(["NaN", "Infinity", "-Infinity"]) == "string"

    def test_nan_case_insensitive(self) -> None:
        assert _infer_type(["nan", "NAN", "Nan"]) == "string"

    def test_inf_case_insensitive(self) -> None:
        assert _infer_type(["inf", "INF", "Inf"]) == "string"

    def test_neg_inf_case_insensitive(self) -> None:
        assert _infer_type(["-inf", "-INF", "-Inf"]) == "string"

    def test_real_floats_still_detected(self) -> None:
        """Normal float values should still be classified as float."""
        assert _infer_type(["1.5", "2.7", "3.14"]) == "float"

    def test_mixed_real_and_nan_is_float(self) -> None:
        """A column with mostly real floats and some NaN is still float."""
        # 80% real floats + 20% NaN should be float (common in data exports)
        values = ["1.5", "2.7", "3.14", "4.0", "NaN"]
        result = _infer_type(values)
        assert result == "float"

    def test_profiler_nan_column(self) -> None:
        """End-to-end: profiler should classify NaN-only column as string."""
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts([
            {"x": "NaN"}, {"x": "Infinity"}, {"x": "-Infinity"},
        ])
        assert profiles[0].inferred_type == "string"


# ---------------------------------------------------------------------------
# Issue #45 — LLM confidence clamping
# ---------------------------------------------------------------------------


class TestLLMConfidenceClamping:
    """LLM confidence values must be clamped to [0.0, 1.0]."""

    def test_overflow_confidence_clamped(self) -> None:
        from ceds_jsonld.wizard.llm_matcher import LLMMatcher
        from ceds_jsonld.wizard.concept_matcher import MatchCandidate

        # We can't easily call the full LLM path, so test the clamping
        # function directly. The fix should extract a helper or inline clamp.
        raw_conf = 999999999
        clamped = _clamp_confidence(raw_conf)
        assert clamped == 1.0

    def test_nan_confidence_becomes_zero(self) -> None:
        clamped = _clamp_confidence(float("nan"))
        assert clamped == 0.0

    def test_negative_confidence_clamped(self) -> None:
        clamped = _clamp_confidence(-0.5)
        assert clamped == 0.0

    def test_normal_confidence_unchanged(self) -> None:
        clamped = _clamp_confidence(0.85)
        assert clamped == 0.85

    def test_boundary_zero(self) -> None:
        assert _clamp_confidence(0.0) == 0.0

    def test_boundary_one(self) -> None:
        assert _clamp_confidence(1.0) == 1.0

    def test_string_nan_confidence(self) -> None:
        """float('NaN') -> should clamp to 0.0."""
        clamped = _clamp_confidence(float("NaN"))
        assert clamped == 0.0
        assert not math.isnan(clamped)


def _clamp_confidence(value: float) -> float:
    """Import the clamping function from llm_matcher."""
    from ceds_jsonld.wizard.llm_matcher import _clamp_confidence as clamp
    return clamp(value)
