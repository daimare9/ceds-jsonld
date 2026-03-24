"""Tests for ConceptValueMatcher — deterministic concept-value matching."""

from __future__ import annotations

from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.concept_matcher import ConceptValueMatcher, MatchCandidate
from ceds_jsonld.wizard.profiler import ColumnProfile


def _make_profile(name: str, distinct: list[str], **kw) -> ColumnProfile:
    """Helper to build a ColumnProfile."""
    return ColumnProfile(
        name=name,
        normalized=name.lower(),
        sample_values=distinct[:10],
        distinct_values=distinct,
        **kw,
    )


def _make_target(name: str, parent: str, concept_values: list[str], **kw) -> TargetProperty:
    """Helper to build a TargetProperty."""
    return TargetProperty(
        name=name,
        path=f"ceds:{name}",
        parent_shape=parent,
        concept_values=concept_values,
        **kw,
    )


class TestConceptValueMatcher:
    """ConceptValueMatcher scoring tests."""

    def test_direct_match(self) -> None:
        col = _make_profile("GENDER", ["Male", "Female"])
        target = _make_target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is not None
        assert result.confidence >= 0.9
        assert "direct" in result.strategy

    def test_prefixed_match(self) -> None:
        col = _make_profile(
            "Type",
            ["PersonIdentifierType_PersonIdentifier", "PersonIdentifierType_StaffMemberIdentifier"],
        )
        target = _make_target(
            "hasPersonIdentifierType",
            "PersonIdentification",
            ["PersonIdentifier", "StaffMemberIdentifier"],
        )

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is not None
        assert result.confidence >= 0.9

    def test_abbreviation_match(self) -> None:
        col = _make_profile("Sex", ["M", "F"])
        target = _make_target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is not None
        assert result.confidence >= 0.7

    def test_no_match(self) -> None:
        col = _make_profile("FirstName", ["Jane", "John", "Alice"])
        target = _make_target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is None

    def test_empty_distinct_values_no_match(self) -> None:
        col = _make_profile("Name", [], inferred_type="string")
        target = _make_target("hasSex", "PersonSexGender", ["Male", "Female"])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is None

    def test_empty_concept_values_no_match(self) -> None:
        col = _make_profile("Gender", ["Male", "Female"])
        target = _make_target("FirstName", "PersonName", [])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is None

    def test_match_candidate_fields(self) -> None:
        c = MatchCandidate(
            source_column="GENDER",
            target_property="hasSex",
            target_shape="PersonSexGender",
            confidence=0.95,
            reasons=["concept_direct_match"],
            strategy="concept_direct",
            suggested_transform=None,
        )
        assert c.source_column == "GENDER"
        assert c.target_property == "hasSex"
