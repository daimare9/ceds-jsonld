"""Tests for HeuristicMatcher — deterministic name+type matching."""

from __future__ import annotations

from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.heuristic import HeuristicMatcher
from ceds_jsonld.wizard.profiler import ColumnProfile


def _col(name: str, inferred_type: str = "string", **kw) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        normalized=name.lower().replace("_", "").replace(" ", "").replace("-", ""),
        inferred_type=inferred_type,
        **kw,
    )


def _target(name: str, datatype: str | None = None, **kw) -> TargetProperty:
    dt = f"http://www.w3.org/2001/XMLSchema#{datatype}" if datatype else None
    return TargetProperty(
        name=name,
        path=f"ceds:{name}",
        parent_shape="TestShape",
        datatype=dt,
        **kw,
    )


class TestHeuristicMatcher:
    def test_exact_name_match(self) -> None:
        col = _col("FirstName")
        target = _target("FirstName", "string")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.confidence >= 0.6
        assert "exact_name_match" in result.reasons

    def test_normalized_name_match(self) -> None:
        col = _col("first_name")
        target = _target("FirstName", "string")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.confidence >= 0.4
        assert "exact_name_match" in result.reasons

    def test_fuzzy_substring_match(self) -> None:
        col = _col("LAST_NM")  # normalized: "lastnm"
        target = _target("LastOrSurname", "string")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        # "last" substring should match
        assert result.confidence > 0.0

    def test_type_compatible_boost(self) -> None:
        col = _col("DOB", inferred_type="date")
        target = _target("Birthdate", "date")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert any("type_compatible" in r for r in result.reasons)

    def test_type_incompatible_no_boost(self) -> None:
        col = _col("Name", inferred_type="string")
        target = _target("Birthdate", "date")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert all("type_compatible" not in r for r in result.reasons)

    def test_zero_score_unrelated(self) -> None:
        col = _col("XYZ_UNKNOWN")
        target = _target("FirstName", "string")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.confidence < 0.3

    def test_date_transform_suggestion(self) -> None:
        col = _col("DOB", inferred_type="date", value_pattern="YYYY-MM-DD")
        target = _target("Birthdate", "date")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.suggested_transform == "date_format"

    def test_integer_transform_suggestion(self) -> None:
        col = _col("SSN", inferred_type="integer")
        target = _target("PersonIdentifier", "token")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.suggested_transform == "int_clean"
