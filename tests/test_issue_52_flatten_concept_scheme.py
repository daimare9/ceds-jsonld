"""Tests for issue #52 — flatten concept scheme / named_individual output.

Concept scheme (named_individual) properties should emit plain string values
in JSON-LD, not wrapped in typed sub-node objects.

Two scenarios:
1. Top-level properties with ``type: named_individual`` → plain string
2. Fields within object properties with ``datatype: named_individual`` → plain string
"""

from __future__ import annotations

from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeDefinition


def _make_shape(mapping_config: dict) -> ShapeDefinition:
    """Build a minimal ShapeDefinition from a mapping config dict."""
    from pathlib import Path

    return ShapeDefinition(
        name="test",
        base_dir=Path("."),
        shacl_path=Path("test.ttl"),
        context={},
        mapping_config=mapping_config,
    )


# ── Mapping configs used by tests ─────────────────────────────────────

NAMED_INDIVIDUAL_TOP_LEVEL = {
    "type": "TestShape",
    "base_uri": "urn:test/",
    "context_url": "https://example.org/ctx",
    "id_source": "Id",
    "properties": {
        "hasBuildingUseType": {
            "type": "named_individual",
            "cardinality": "single",
            "fields": {
                "BuildingUseType": {
                    "source": "BuildingUseType",
                    "target": "hasBuildingUseType",
                    "datatype": "named_individual",
                    "optional": True,
                },
            },
        },
    },
}

NAMED_INDIVIDUAL_INSIDE_OBJECT = {
    "type": "TestShape",
    "base_uri": "urn:test/",
    "context_url": "https://example.org/ctx",
    "id_source": "Id",
    "properties": {
        "hasLocation": {
            "type": "Location",
            "cardinality": "single",
            "fields": {
                "City": {
                    "source": "City",
                    "target": "AddressCity",
                    "datatype": "xsd:string",
                    "optional": True,
                },
                "Locale": {
                    "source": "Locale",
                    "target": "hasLocale",
                    "datatype": "named_individual",
                    "optional": True,
                },
                "State": {
                    "source": "State",
                    "target": "hasStateAbbreviation",
                    "datatype": "named_individual",
                    "optional": True,
                },
            },
        },
    },
}

MIXED_PROPS = {
    "type": "TestShape",
    "base_uri": "urn:test/",
    "context_url": "https://example.org/ctx",
    "id_source": "Id",
    "properties": {
        "hasOrganizationTitle": {
            "type": "OrganizationTitle",
            "cardinality": "single",
            "fields": {
                "Name": {
                    "source": "Name",
                    "target": "hasName",
                    "datatype": "xsd:string",
                    "optional": False,
                },
            },
        },
        "hasOrganizationType": {
            "type": "named_individual",
            "cardinality": "single",
            "fields": {
                "OrgType": {
                    "source": "OrganizationType",
                    "target": "hasOrganizationType",
                    "datatype": "named_individual",
                    "optional": True,
                },
            },
        },
    },
}


# ── Tests ──────────────────────────────────────────────────────────────


class TestNamedIndividualTopLevel:
    """Top-level named_individual properties flatten to plain strings."""

    def test_single_concept_value_is_string(self) -> None:
        shape = _make_shape(NAMED_INDIVIDUAL_TOP_LEVEL)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "BuildingUseType": "BuildingUseType_Administrative"}
        doc = builder.build_one(mapper.map(row))
        assert doc["hasBuildingUseType"] == "BuildingUseType_Administrative"

    def test_concept_value_is_not_object(self) -> None:
        shape = _make_shape(NAMED_INDIVIDUAL_TOP_LEVEL)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "BuildingUseType": "BuildingUseType_Administrative"}
        doc = builder.build_one(mapper.map(row))
        assert not isinstance(doc["hasBuildingUseType"], dict)

    def test_missing_optional_concept_omitted(self) -> None:
        shape = _make_shape(NAMED_INDIVIDUAL_TOP_LEVEL)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1"}
        doc = builder.build_one(mapper.map(row))
        assert "hasBuildingUseType" not in doc


class TestNamedIndividualInsideObject:
    """Named-individual fields within object properties flatten to plain strings."""

    def test_locale_field_is_plain_string(self) -> None:
        shape = _make_shape(NAMED_INDIVIDUAL_INSIDE_OBJECT)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "City": "Lansing", "Locale": "Locale_CityMidsize", "State": "StateAbbreviation_MI"}
        doc = builder.build_one(mapper.map(row))
        loc = doc["hasLocation"]
        assert loc["hasLocale"] == "Locale_CityMidsize"
        assert loc["hasStateAbbreviation"] == "StateAbbreviation_MI"

    def test_locale_not_typed_literal(self) -> None:
        shape = _make_shape(NAMED_INDIVIDUAL_INSIDE_OBJECT)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "Locale": "Locale_CityMidsize"}
        doc = builder.build_one(mapper.map(row))
        loc = doc["hasLocation"]
        assert not isinstance(loc["hasLocale"], dict)

    def test_string_field_still_plain(self) -> None:
        """xsd:string fields are not affected by the named_individual change."""
        shape = _make_shape(NAMED_INDIVIDUAL_INSIDE_OBJECT)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "City": "Lansing"}
        doc = builder.build_one(mapper.map(row))
        loc = doc["hasLocation"]
        assert loc["AddressCity"] == "Lansing"

    def test_object_still_has_type(self) -> None:
        """Object properties still produce @type even when containing NI fields."""
        shape = _make_shape(NAMED_INDIVIDUAL_INSIDE_OBJECT)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "City": "Lansing", "Locale": "Locale_CityMidsize"}
        doc = builder.build_one(mapper.map(row))
        loc = doc["hasLocation"]
        assert loc["@type"] == "Location"


class TestMixedPropertyTypes:
    """Object and named_individual properties coexist correctly."""

    def test_object_prop_remains_nested(self) -> None:
        shape = _make_shape(MIXED_PROPS)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "Name": "Springfield ISD", "OrganizationType": "OrgType_LEA"}
        doc = builder.build_one(mapper.map(row))
        assert isinstance(doc["hasOrganizationTitle"], dict)
        assert doc["hasOrganizationTitle"]["@type"] == "OrganizationTitle"
        assert doc["hasOrganizationTitle"]["hasName"] == "Springfield ISD"

    def test_named_individual_prop_is_flat(self) -> None:
        shape = _make_shape(MIXED_PROPS)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "Name": "Springfield ISD", "OrganizationType": "OrgType_LEA"}
        doc = builder.build_one(mapper.map(row))
        assert doc["hasOrganizationType"] == "OrgType_LEA"


class TestTypedLiteralNamedIndividual:
    """_typed_literal treats named_individual like xsd:string."""

    def test_returns_plain_string(self) -> None:
        result = JSONLDBuilder._typed_literal("Locale_City", "named_individual")
        assert result == "Locale_City"
        assert isinstance(result, str)

    def test_returns_none_for_none(self) -> None:
        assert JSONLDBuilder._typed_literal(None, "named_individual") is None

    def test_returns_none_for_nan(self) -> None:
        assert JSONLDBuilder._typed_literal(float("nan"), "named_individual") is None

    def test_list_of_values_returns_strings(self) -> None:
        result = JSONLDBuilder._typed_literal(
            ["Locale_City", "Locale_Rural"],
            "named_individual",
        )
        assert result == ["Locale_City", "Locale_Rural"]

    def test_xsd_string_unchanged(self) -> None:
        """Ensure xsd:string still works as before."""
        result = JSONLDBuilder._typed_literal("hello", "xsd:string")
        assert result == "hello"

    def test_xsd_date_still_wrapped(self) -> None:
        """Non-NI datatypes still produce typed literals."""
        result = JSONLDBuilder._typed_literal("2024-01-01", "xsd:date")
        assert result == {"@type": "xsd:date", "@value": "2024-01-01"}
