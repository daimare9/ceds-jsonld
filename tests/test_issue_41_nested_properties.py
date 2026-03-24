"""Tests for issue #41 — nested sub-properties (hasLocationAddress within Location).

The builder and mapper should support a ``properties`` key inside
property definitions, enabling arbitrary nesting of sub-shapes.
Example: Location → hasLocationAddress[] → LocationAddress fields.

Closes #41.
"""

from __future__ import annotations

from pathlib import Path

from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeDefinition, ShapeRegistry

# ---------------------------------------------------------------------------
# Synthetic mapping config with nested properties
# ---------------------------------------------------------------------------


def _make_nested_config() -> dict:
    """Return a minimal mapping config with nested properties."""
    return {
        "shape": "TestNestedShape",
        "context_url": "https://example.org/context.json",
        "base_uri": "test:org/",
        "id_source": "OrgId",
        "type": "Organization",
        "properties": {
            "hasLocation": {
                "type": "Location",
                "cardinality": "single",
                "fields": {},
                "properties": {
                    "hasLocationAddress": {
                        "type": "LocationAddress",
                        "cardinality": "multiple",
                        "split_on": ";",
                        "fields": {
                            "hasAddressTypeForOrganization": {
                                "source": "AddressTypes",
                                "target": "hasAddressTypeForOrganization",
                                "optional": True,
                            },
                            "AddressStreetNumberAndName": {
                                "source": "AddressStreets",
                                "target": "AddressStreetNumberAndName",
                                "datatype": "xsd:string",
                                "optional": True,
                            },
                            "AddressCity": {
                                "source": "AddressCities",
                                "target": "AddressCity",
                                "datatype": "xsd:string",
                                "optional": True,
                            },
                            "hasStateAbbreviation": {
                                "source": "AddressStates",
                                "target": "hasStateAbbreviation",
                                "optional": True,
                            },
                            "AddressPostalCode": {
                                "source": "AddressZips",
                                "target": "AddressPostalCode",
                                "datatype": "xsd:string",
                                "optional": True,
                            },
                        },
                    },
                },
            },
        },
    }


def _shape_def_from_config(config: dict) -> ShapeDefinition:
    """Build a ShapeDefinition from a raw config dict."""
    return ShapeDefinition(
        name=config["shape"],
        base_dir=Path("."),
        shacl_path=Path("."),
        context={},
        mapping_config=config,
    )


# ---------------------------------------------------------------------------
# Test: FieldMapper handles nested properties
# ---------------------------------------------------------------------------


class TestMapperNestedProperties:
    """FieldMapper should recursively map nested ``properties``."""

    def test_mapper_produces_nested_sub_instances(self) -> None:
        """Mapper output for hasLocation should contain hasLocationAddress key."""
        config = _make_nested_config()
        mapper = FieldMapper(config)
        row = {
            "OrgId": "1",
            "AddressTypes": "Physical;Shipping",
            "AddressStreets": "711 Duncan;814 Bruce",
            "AddressCities": "Lansing;Fairfield",
            "AddressStates": "StateAbbreviation_MI;StateAbbreviation_MI",
            "AddressZips": "52231;34321",
        }
        mapped = mapper.map(row)
        loc_instances = mapped.get("hasLocation")
        assert loc_instances is not None
        assert len(loc_instances) == 1  # single cardinality → one Location instance
        loc = loc_instances[0]
        # Nested sub-instances should be keyed under the nested property name
        assert "hasLocationAddress" in loc
        addresses = loc["hasLocationAddress"]
        assert isinstance(addresses, list)
        assert len(addresses) == 2

    def test_mapper_nested_single_instance(self) -> None:
        """A single address (no delimiter) should produce one nested instance."""
        config = _make_nested_config()
        mapper = FieldMapper(config)
        row = {
            "OrgId": "1",
            "AddressTypes": "Physical",
            "AddressStreets": "100 Main St",
            "AddressCities": "Detroit",
            "AddressStates": "StateAbbreviation_MI",
            "AddressZips": "48201",
        }
        mapped = mapper.map(row)
        loc = mapped["hasLocation"][0]
        assert "hasLocationAddress" in loc
        addresses = loc["hasLocationAddress"]
        assert len(addresses) == 1
        assert addresses[0]["AddressCity"] == "Detroit"

    def test_mapper_nested_empty_source_skips_property(self) -> None:
        """When all nested fields are empty, the nested property is absent."""
        config = _make_nested_config()
        mapper = FieldMapper(config)
        row = {"OrgId": "1"}
        mapped = mapper.map(row)
        # hasLocation might still be present (empty Location) or absent
        # depending on implementation; but hasLocationAddress must not appear
        # with empty data
        loc_instances = mapped.get("hasLocation", [])
        if loc_instances:
            loc = loc_instances[0]
            addresses = loc.get("hasLocationAddress", [])
            assert len(addresses) == 0


# ---------------------------------------------------------------------------
# Test: Builder handles nested properties
# ---------------------------------------------------------------------------


class TestBuilderNestedProperties:
    """Builder should recursively build nested sub-shapes."""

    def test_builder_creates_nested_sub_shape(self) -> None:
        """Location node should contain hasLocationAddress array of typed objects."""
        config = _make_nested_config()
        shape_def = _shape_def_from_config(config)
        mapper = FieldMapper(config)
        builder = JSONLDBuilder(shape_def)

        row = {
            "OrgId": "1",
            "AddressTypes": "Physical;Shipping",
            "AddressStreets": "711 Duncan;814 Bruce",
            "AddressCities": "Lansing;Fairfield",
            "AddressStates": "StateAbbreviation_MI;StateAbbreviation_MI",
            "AddressZips": "52231;34321",
        }
        doc = builder.build_one(mapper.map(row))

        loc = doc["hasLocation"]
        assert loc["@type"] == "Location"
        addresses = loc.get("hasLocationAddress")
        assert addresses is not None
        assert isinstance(addresses, list)
        assert len(addresses) == 2

    def test_nested_address_types(self) -> None:
        """Each nested LocationAddress should have @type = LocationAddress."""
        config = _make_nested_config()
        shape_def = _shape_def_from_config(config)
        mapper = FieldMapper(config)
        builder = JSONLDBuilder(shape_def)

        row = {
            "OrgId": "1",
            "AddressTypes": "Physical;Shipping",
            "AddressStreets": "711 Duncan;814 Bruce",
            "AddressCities": "Lansing;Fairfield",
            "AddressStates": "StateAbbreviation_MI;StateAbbreviation_MI",
            "AddressZips": "52231;34321",
        }
        doc = builder.build_one(mapper.map(row))
        addresses = doc["hasLocation"]["hasLocationAddress"]

        for addr in addresses:
            assert addr["@type"] == "LocationAddress"

    def test_nested_field_values(self) -> None:
        """Fields in nested LocationAddress should carry correct values."""
        config = _make_nested_config()
        shape_def = _shape_def_from_config(config)
        mapper = FieldMapper(config)
        builder = JSONLDBuilder(shape_def)

        row = {
            "OrgId": "1",
            "AddressTypes": "Physical;Shipping",
            "AddressStreets": "711 Duncan;814 Bruce",
            "AddressCities": "Lansing;Fairfield",
            "AddressStates": "StateAbbreviation_MI;StateAbbreviation_MI",
            "AddressZips": "52231-4321;34321",
        }
        doc = builder.build_one(mapper.map(row))
        addresses = doc["hasLocation"]["hasLocationAddress"]

        phys = addresses[0]
        assert phys["hasAddressTypeForOrganization"] == "Physical"
        assert phys["AddressStreetNumberAndName"] == "711 Duncan"
        assert phys["AddressCity"] == "Lansing"
        assert phys["hasStateAbbreviation"] == "StateAbbreviation_MI"
        assert phys["AddressPostalCode"] == "52231-4321"

        ship = addresses[1]
        assert ship["hasAddressTypeForOrganization"] == "Shipping"
        assert ship["AddressStreetNumberAndName"] == "814 Bruce"
        assert ship["AddressCity"] == "Fairfield"

    def test_single_nested_address_unwrapped(self) -> None:
        """A single nested address should be unwrapped from array (same as top-level behavior)."""
        config = _make_nested_config()
        shape_def = _shape_def_from_config(config)
        mapper = FieldMapper(config)
        builder = JSONLDBuilder(shape_def)

        row = {
            "OrgId": "1",
            "AddressTypes": "Physical",
            "AddressStreets": "100 Main St",
            "AddressCities": "Detroit",
            "AddressStates": "StateAbbreviation_MI",
            "AddressZips": "48201",
        }
        doc = builder.build_one(mapper.map(row))
        loc = doc["hasLocation"]
        # Single nested address → unwrapped from array to single object
        addr = loc["hasLocationAddress"]
        assert isinstance(addr, dict)
        assert addr["@type"] == "LocationAddress"
        assert addr["AddressCity"] == "Detroit"

    def test_no_nested_data_omits_property(self) -> None:
        """When all nested fields are missing, the nested property is absent."""
        config = _make_nested_config()
        shape_def = _shape_def_from_config(config)
        mapper = FieldMapper(config)
        builder = JSONLDBuilder(shape_def)

        row = {"OrgId": "1"}
        doc = builder.build_one(mapper.map(row))
        # With no location data at all, hasLocation itself shouldn't be present
        assert "hasLocation" not in doc


# ---------------------------------------------------------------------------
# Test: Typed literals in nested fields (xsd:string simplified, xsd:decimal wrapped)
# ---------------------------------------------------------------------------


class TestNestedTypedLiterals:
    """Nested fields should respect typed literal rules (issue #43 integration)."""

    def test_xsd_string_in_nested_is_plain(self) -> None:
        """xsd:string fields in nested LocationAddress should be plain strings."""
        config = _make_nested_config()
        shape_def = _shape_def_from_config(config)
        mapper = FieldMapper(config)
        builder = JSONLDBuilder(shape_def)

        row = {
            "OrgId": "1",
            "AddressTypes": "Physical",
            "AddressStreets": "711 Duncan",
            "AddressCities": "Lansing",
            "AddressStates": "StateAbbreviation_MI",
            "AddressZips": "52231",
        }
        doc = builder.build_one(mapper.map(row))
        addr = doc["hasLocation"]["hasLocationAddress"]
        assert addr["AddressCity"] == "Lansing"
        assert isinstance(addr["AddressCity"], str)
        assert addr["AddressStreetNumberAndName"] == "711 Duncan"

    def test_xsd_decimal_in_nested_stays_wrapped(self) -> None:
        """Non-string typed literals in nested shapes should stay wrapped."""
        config = _make_nested_config()
        # Add a decimal field to the nested config
        config["properties"]["hasLocation"]["properties"]["hasLocationAddress"]["fields"]["Latitude"] = {
            "source": "Latitudes",
            "target": "Latitude",
            "datatype": "xsd:decimal",
            "optional": True,
        }
        shape_def = _shape_def_from_config(config)
        mapper = FieldMapper(config)
        builder = JSONLDBuilder(shape_def)

        row = {
            "OrgId": "1",
            "AddressTypes": "Physical",
            "AddressStreets": "711 Duncan",
            "AddressCities": "Lansing",
            "AddressStates": "StateAbbreviation_MI",
            "AddressZips": "52231",
            "Latitudes": "42.7325",
        }
        doc = builder.build_one(mapper.map(row))
        addr = doc["hasLocation"]["hasLocationAddress"]
        assert addr["Latitude"] == {"@type": "xsd:decimal", "@value": "42.7325"}


# ---------------------------------------------------------------------------
# Test: Backward compatibility — existing flat shapes still work
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Shapes without nested ``properties`` must work identically to before."""

    def test_person_shape_unchanged(self) -> None:
        """Person shape (no nested properties) builds normally."""
        registry = ShapeRegistry()
        shape_def = registry.load_shape("person")
        mapper = FieldMapper(shape_def.mapping_config)
        builder = JSONLDBuilder(shape_def)

        row = {
            "FirstName": "Jane",
            "LastName": "Doe",
            "Birthdate": "1990-01-15",
            "Sex": "Female",
            "RaceEthnicity": "White",
            "PersonIdentifiers": "123456789",
            "IdentificationSystems": "PersonIdentificationSystem_SSN",
            "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
        }
        doc = builder.build_one(mapper.map(row))
        assert doc["@type"] == "Person"
        assert doc["hasPersonName"]["FirstName"] == "Jane"

    def test_flat_org_location_still_works_if_no_nested_props(self) -> None:
        """An Organization config without nested properties still produces flat Location."""
        flat_config = {
            "shape": "FlatOrg",
            "context_url": "https://example.org/context.json",
            "base_uri": "test:org/",
            "id_source": "OrgId",
            "type": "Organization",
            "properties": {
                "hasLocation": {
                    "type": "Location",
                    "cardinality": "single",
                    "fields": {
                        "AddressCity": {
                            "source": "City",
                            "target": "AddressCity",
                            "datatype": "xsd:string",
                            "optional": True,
                        },
                    },
                },
            },
        }
        shape_def = _shape_def_from_config(flat_config)
        mapper = FieldMapper(flat_config)
        builder = JSONLDBuilder(shape_def)

        row = {"OrgId": "1", "City": "Detroit"}
        doc = builder.build_one(mapper.map(row))
        loc = doc["hasLocation"]
        assert loc["@type"] == "Location"
        assert loc["AddressCity"] == "Detroit"
        # No hasLocationAddress should appear for flat configs
        assert "hasLocationAddress" not in loc


# ---------------------------------------------------------------------------
# Test: End-to-end with real Organization shape (after YAML update)
# ---------------------------------------------------------------------------


class TestOrganizationShapeIntegration:
    """Integration tests with the real shipped Organization shape."""

    def test_org_shape_produces_nested_location_address(self) -> None:
        """Organization shape should produce Location with nested hasLocationAddress."""
        registry = ShapeRegistry()
        shape_def = registry.load_shape("organization")
        config = shape_def.mapping_config

        # Verify the YAML now has nested properties
        loc_def = config["properties"]["hasLocation"]
        assert "properties" in loc_def, (
            "Organization hasLocation should have nested 'properties' key after YAML update for issue #41"
        )
        assert "hasLocationAddress" in loc_def["properties"]

    def test_org_shape_full_build_two_addresses(self) -> None:
        """Full end-to-end build with two addresses nested under Location."""
        registry = ShapeRegistry()
        shape_def = registry.load_shape("organization")
        # Provide decimal_clean as a custom transform (identity for test purposes)
        custom_transforms = {"decimal_clean": lambda v: v}
        mapper = FieldMapper(shape_def.mapping_config, custom_transforms=custom_transforms)
        builder = JSONLDBuilder(shape_def)

        row = {
            "OrgId": "1234",
            "OrgName": "Test District",
            "AddressTypes": "AddressTypeForOrganization_Physical;AddressTypeForOrganization_Shipping",
            "AddressStreets": "711 Duncan;814 Bruce",
            "AddressApts": ";Suite 330",
            "AddressCities": "Lansing;Fairfield",
            "AddressStates": "StateAbbreviation_MI;StateAbbreviation_MI",
            "AddressZips": "52231-4321;34321",
            "AddressCounties": "Washtenaw;Macomb",
            "Latitudes": "1.123;2.1231",
            "Longitudes": "31.1231;32.2132",
        }
        doc = builder.build_one(mapper.map(row))

        loc = doc["hasLocation"]
        assert loc["@type"] == "Location"

        addresses = loc["hasLocationAddress"]
        assert isinstance(addresses, list)
        assert len(addresses) == 2

        phys = addresses[0]
        assert phys["@type"] == "LocationAddress"
        assert phys["hasAddressTypeForOrganization"] == "AddressTypeForOrganization_Physical"
        assert phys["AddressStreetNumberAndName"] == "711 Duncan"
        assert phys["AddressCity"] == "Lansing"
        assert phys["AddressPostalCode"] == "52231-4321"
        assert phys["AddressCountyName"] == "Washtenaw"
        assert phys["Latitude"] == {"@type": "xsd:decimal", "@value": "1.123"}

        ship = addresses[1]
        assert ship["@type"] == "LocationAddress"
        assert ship["hasAddressTypeForOrganization"] == "AddressTypeForOrganization_Shipping"
        assert ship["AddressStreetNumberAndName"] == "814 Bruce"
        assert ship["AddressCity"] == "Fairfield"
        assert ship["AddressPostalCode"] == "34321"
        assert ship["AddressCountyName"] == "Macomb"
