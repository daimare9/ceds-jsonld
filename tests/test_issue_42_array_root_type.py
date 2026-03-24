"""Tests for Issue #42: Allow root @type to contain an array of values.

When a mapping config's ``type`` field is a list (e.g. ``["Organization",
"K12School"]``), the builder should emit ``@type`` as that list.  Single-string
values continue to produce a plain string ``@type``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.cosmos.prepare import prepare_for_cosmos
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeDefinition


# ---------------------------------------------------------------------------
# Helpers — build a minimal ShapeDefinition with a given type value
# ---------------------------------------------------------------------------


def _make_shape_def(
    type_value: str | list[str],
    *,
    properties: dict[str, Any] | None = None,
) -> ShapeDefinition:
    """Create a lightweight ShapeDefinition for builder tests."""
    config: dict[str, Any] = {
        "shape": "TestShape",
        "context_url": "https://example.org/context.json",
        "base_uri": "ex:test/",
        "id_source": "Id",
        "type": type_value,
        "properties": properties or {},
    }
    return ShapeDefinition(
        name="test",
        base_dir=None,  # type: ignore[arg-type]
        shacl_path=None,  # type: ignore[arg-type]
        context={},
        mapping_config=config,
    )


def _minimal_mapped_row() -> dict[str, Any]:
    """A mapped row with just the __id__ that build_one requires."""
    return {"__id__": "1"}


# ---------------------------------------------------------------------------
# Tests — single-string type (existing behaviour must not regress)
# ---------------------------------------------------------------------------


class TestSingleStringType:
    """Existing behaviour: string type → string @type."""

    def test_string_type_produces_string(self):
        shape = _make_shape_def("Organization")
        builder = JSONLDBuilder(shape)
        doc = builder.build_one(_minimal_mapped_row())
        assert doc["@type"] == "Organization"

    def test_string_type_is_not_list(self):
        shape = _make_shape_def("Person")
        builder = JSONLDBuilder(shape)
        doc = builder.build_one(_minimal_mapped_row())
        assert not isinstance(doc["@type"], list)


# ---------------------------------------------------------------------------
# Tests — array type (new behaviour)
# ---------------------------------------------------------------------------


class TestArrayType:
    """New behaviour: list type → list @type."""

    def test_list_type_produces_list(self):
        shape = _make_shape_def(["Organization", "K12School"])
        builder = JSONLDBuilder(shape)
        doc = builder.build_one(_minimal_mapped_row())
        assert doc["@type"] == ["Organization", "K12School"]

    def test_list_type_preserves_order(self):
        shape = _make_shape_def(["K12School", "Organization"])
        builder = JSONLDBuilder(shape)
        doc = builder.build_one(_minimal_mapped_row())
        assert doc["@type"] == ["K12School", "Organization"]

    def test_list_type_with_three_values(self):
        shape = _make_shape_def(["Organization", "K12School", "CharterSchool"])
        builder = JSONLDBuilder(shape)
        doc = builder.build_one(_minimal_mapped_row())
        assert doc["@type"] == ["Organization", "K12School", "CharterSchool"]
        assert len(doc["@type"]) == 3

    def test_single_element_list_stays_list(self):
        """A list with one element should remain a list — user explicitly chose array form."""
        shape = _make_shape_def(["Organization"])
        builder = JSONLDBuilder(shape)
        doc = builder.build_one(_minimal_mapped_row())
        assert doc["@type"] == ["Organization"]
        assert isinstance(doc["@type"], list)


# ---------------------------------------------------------------------------
# Tests — build_many preserves array type
# ---------------------------------------------------------------------------


class TestBuildManyArrayType:
    """build_many produces consistent @type across all documents."""

    def test_build_many_all_have_array_type(self):
        shape = _make_shape_def(["Organization", "LocalEducationAgency"])
        builder = JSONLDBuilder(shape)
        rows = [_minimal_mapped_row() for _ in range(3)]
        docs = builder.build_many(rows)
        assert len(docs) == 3
        for doc in docs:
            assert doc["@type"] == ["Organization", "LocalEducationAgency"]


# ---------------------------------------------------------------------------
# Tests — integration with real Person shape (regression guard)
# ---------------------------------------------------------------------------


class TestPersonShapeRegressionGuard:
    """Existing Person shape uses string type — must stay string."""

    def test_person_type_still_string(self, person_shape_def, sample_person_row_full):
        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)
        doc = builder.build_one(mapper.map(sample_person_row_full))
        assert doc["@type"] == "Person"
        assert isinstance(doc["@type"], str)


# ---------------------------------------------------------------------------
# Tests — Cosmos prepare handles array @type partition key
# ---------------------------------------------------------------------------


class TestCosmosPartitionKeyArrayType:
    """prepare_for_cosmos must handle list @type for partition keys."""

    def test_string_type_partition_key(self):
        doc = {"@id": "cepi:org/1", "@type": "Organization"}
        result = prepare_for_cosmos(doc)
        assert result["partitionKey"] == "Organization"

    def test_list_type_uses_first_element(self):
        doc = {"@id": "cepi:org/1", "@type": ["Organization", "K12School"]}
        result = prepare_for_cosmos(doc)
        assert result["partitionKey"] == "Organization"

    def test_list_type_single_element(self):
        doc = {"@id": "cepi:org/1", "@type": ["Organization"]}
        result = prepare_for_cosmos(doc)
        assert result["partitionKey"] == "Organization"

    def test_explicit_partition_overrides_list_type(self):
        doc = {"@id": "cepi:org/1", "@type": ["Organization", "K12School"]}
        result = prepare_for_cosmos(doc, partition_value="custom")
        assert result["partitionKey"] == "custom"
