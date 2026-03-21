"""Tests for MatchingEngine — three-phase matching orchestrator."""

from __future__ import annotations

from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.engine import MatchingEngine
from ceds_jsonld.wizard.profiler import ColumnProfile


def _col(
    name: str,
    distinct: list[str] | None = None,
    inferred_type: str = "string",
    **kw,
) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        normalized=name.lower().replace("_", "").replace(" ", "").replace("-", ""),
        inferred_type=inferred_type,
        distinct_values=distinct or [],
        sample_values=distinct[:5] if distinct else [],
        **kw,
    )


def _target(
    name: str,
    parent: str,
    concept_values: list[str] | None = None,
    datatype: str | None = None,
) -> TargetProperty:
    dt = f"http://www.w3.org/2001/XMLSchema#{datatype}" if datatype else None
    return TargetProperty(
        name=name,
        path=f"ceds:{name}",
        parent_shape=parent,
        concept_values=concept_values or [],
        datatype=dt,
    )


class TestMatchingEngine:
    def test_concept_phase_resolves_first(self) -> None:
        columns = [_col("GENDER", ["Male", "Female"])]
        targets = [
            _target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"]),
            _target("FirstName", "PersonName", datatype="string"),
        ]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert len(matches) == 1
        assert matches[0].target_property == "hasSex"
        assert matches[0].strategy.startswith("concept")

    def test_heuristic_phase_for_name_match(self) -> None:
        columns = [_col("FirstName", inferred_type="string")]
        targets = [
            _target("FirstName", "PersonName", datatype="string"),
            _target("Birthdate", "PersonBirth", datatype="date"),
        ]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert len(matches) == 1
        assert matches[0].target_property == "FirstName"
        assert matches[0].strategy == "heuristic"

    def test_unmatched_columns_returned(self) -> None:
        columns = [_col("XYZ_UNKNOWN_COL")]
        targets = [_target("FirstName", "PersonName", datatype="string")]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert len(matches) == 0
        assert "XYZ_UNKNOWN_COL" in unmatched_cols

    def test_unmatched_targets_returned(self) -> None:
        columns = [_col("FirstName")]
        targets = [
            _target("FirstName", "PersonName", datatype="string"),
            _target("Birthdate", "PersonBirth", datatype="date"),
        ]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert "Birthdate" in unmatched_targets

    def test_multi_column_matching(self) -> None:
        columns = [
            _col("FirstName"),
            _col("GENDER", ["Male", "Female"]),
            _col("DOB", inferred_type="date", value_pattern="YYYY-MM-DD"),
        ]
        targets = [
            _target("FirstName", "PersonName", datatype="string"),
            _target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"]),
            _target("Birthdate", "PersonBirth", datatype="date"),
        ]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert len(matches) == 3
        assert len(unmatched_cols) == 0
        assert len(unmatched_targets) == 0

    def test_confidence_threshold(self) -> None:
        columns = [_col("X")]  # Very short name, weak match
        targets = [_target("FirstName", "PersonName", datatype="string")]
        engine = MatchingEngine(use_llm=False, heuristic_threshold=0.5)
        matches, unmatched_cols, _ = engine.match(columns, targets)

        assert len(matches) == 0
        assert "X" in unmatched_cols
