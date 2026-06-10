"""Tests for wrapper_field / inner_type support in JSONLDBuilder._build_sub_nodes.

Covers the two-level container node pattern required by SHACL shapes such as:
  Organization → hasLocation → Location → hasLocationAddress → LocationAddress
"""

from __future__ import annotations

from pathlib import Path

from ceds_jsonld.adapters.dict_adapter import DictAdapter
from ceds_jsonld.adapters.relational_adapter import RelationalAdapter
from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeDefinition


def _make_shape(mapping_config: dict) -> ShapeDefinition:
    """Wrap a raw mapping config dict in a minimal ShapeDefinition."""
    return ShapeDefinition(
        name="test",
        base_dir=Path("."),
        shacl_path=Path("."),
        context={},
        mapping_config=mapping_config,
    )


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

WRAPPER_PROP_DEF = {
    "type": "Location",
    "wrapper_field": "hasLocationAddress",
    "inner_type": "LocationAddress",
    "fields": {
        "city": {
            "source": "AddressCity",
            "target": "AddressCity",
            "optional": True,
        },
        "street": {
            "source": "AddressStreetNumberAndName",
            "target": "AddressStreetNumberAndName",
            "optional": True,
        },
    },
}

ORG_SHAPE_DEF = {
    "type": "Organization",
    "base_uri": "https://example.org/org/",
    "id_field": "OrgId",
    "id_source": "OrgId",
    "context_url": "https://example.org/context.json",
    "properties": {
        "hasLocation": WRAPPER_PROP_DEF,
    },
}


# ---------------------------------------------------------------------------
# Unit: _build_sub_nodes
# ---------------------------------------------------------------------------


class TestBuildSubNodesWrapper:
    """Direct unit tests for the wrapper_field / inner_type code path."""

    def _builder(self) -> JSONLDBuilder:
        return JSONLDBuilder(_make_shape(ORG_SHAPE_DEF))

    def test_outer_type_is_location(self):
        """Outer node carries @type = type (Location)."""
        builder = self._builder()
        instances = [{"AddressCity": "GRAND RAPIDS", "AddressStreetNumberAndName": "123 Main St"}]
        nodes = builder._build_sub_nodes(instances, WRAPPER_PROP_DEF)
        assert len(nodes) == 1
        assert nodes[0]["@type"] == "Location"

    def test_inner_type_is_location_address(self):
        """Inner node under wrapper_field carries @type = inner_type (LocationAddress)."""
        builder = self._builder()
        instances = [{"AddressCity": "GRAND RAPIDS", "AddressStreetNumberAndName": "123 Main St"}]
        nodes = builder._build_sub_nodes(instances, WRAPPER_PROP_DEF)
        inner = nodes[0]["hasLocationAddress"]
        assert inner["@type"] == "LocationAddress"

    def test_fields_placed_on_inner_node(self):
        """Mapped fields appear on the inner node, not the outer node."""
        builder = self._builder()
        instances = [{"AddressCity": "GRAND RAPIDS", "AddressStreetNumberAndName": "123 Main St"}]
        nodes = builder._build_sub_nodes(instances, WRAPPER_PROP_DEF)
        outer = nodes[0]
        inner = outer["hasLocationAddress"]
        # Fields belong to inner
        assert inner["AddressCity"] == "GRAND RAPIDS"
        assert inner["AddressStreetNumberAndName"] == "123 Main St"
        # Fields must NOT bleed onto outer
        assert "AddressCity" not in outer
        assert "AddressStreetNumberAndName" not in outer

    def test_multiple_instances_produce_multiple_outer_nodes(self):
        """Each satellite row yields one outer Location node."""
        builder = self._builder()
        instances = [
            {"AddressCity": "GRAND RAPIDS", "AddressStreetNumberAndName": "123 Main St"},
            {"AddressCity": "LANSING", "AddressStreetNumberAndName": "456 Oak Ave"},
        ]
        nodes = builder._build_sub_nodes(instances, WRAPPER_PROP_DEF)
        assert len(nodes) == 2
        assert nodes[0]["hasLocationAddress"]["AddressCity"] == "GRAND RAPIDS"
        assert nodes[1]["hasLocationAddress"]["AddressCity"] == "LANSING"

    def test_empty_inner_node_suppressed(self):
        """If all optional fields are missing, no outer node is emitted."""
        builder = self._builder()
        # Instance with no real field values
        instances = [{}]
        nodes = builder._build_sub_nodes(instances, WRAPPER_PROP_DEF)
        assert nodes == []

    def test_no_wrapper_field_unchanged_behaviour(self):
        """Without wrapper_field the original flat behaviour is preserved."""
        flat_prop_def = {
            "type": "LocationAddress",
            "fields": {
                "city": {
                    "source": "AddressCity",
                    "target": "AddressCity",
                    "optional": True,
                },
            },
        }
        flat_shape_config = {
            "type": "Organization",
            "base_uri": "https://example.org/org/",
            "id_field": "OrgId",
            "id_source": "OrgId",
            "context_url": "https://example.org/context.json",
            "properties": {"hasLocation": flat_prop_def},
        }
        builder = JSONLDBuilder(_make_shape(flat_shape_config))
        instances = [{"AddressCity": "GRAND RAPIDS"}]
        nodes = builder._build_sub_nodes(instances, flat_prop_def)
        assert len(nodes) == 1
        assert nodes[0]["@type"] == "LocationAddress"
        assert nodes[0]["AddressCity"] == "GRAND RAPIDS"
        assert "hasLocationAddress" not in nodes[0]


# ---------------------------------------------------------------------------
# Integration: FieldMapper + builder with a relational source
# ---------------------------------------------------------------------------

MAPPING_CONFIG = {
    "type": "Organization",
    "base_uri": "https://example.org/org/",
    "id_field": "OrgId",
    "id_source": "OrgId",
    "context_url": "https://example.org/context.json",
    "properties": {
        "hasLocation": {
            "source_table": "addresses",
            "type": "Location",
            "wrapper_field": "hasLocationAddress",
            "inner_type": "LocationAddress",
            "fields": {
                "city": {
                    "source": "AddressCity",
                    "target": "AddressCity",
                    "optional": True,
                },
                "street": {
                    "source": "AddressStreetNumberAndName",
                    "target": "AddressStreetNumberAndName",
                    "optional": True,
                },
            },
        },
    },
}

PRIMARY_ROWS = [{"OrgId": "ORG-1", "OrgName": "Acme Schools"}]
ADDRESS_ROWS = [
    {"OrgId": "ORG-1", "AddressCity": "GRAND RAPIDS", "AddressStreetNumberAndName": "100 Main St"},
]


class TestWrapperFieldIntegration:
    """End-to-end: RelationalAdapter → FieldMapper → JSONLDBuilder with wrapper."""

    def _build_doc(self) -> dict:
        primary = DictAdapter(PRIMARY_ROWS)
        addresses = DictAdapter(ADDRESS_ROWS)
        adapter = RelationalAdapter(
            primary=primary,
            join_key="OrgId",
            satellites={"addresses": addresses},
        )
        mapper = FieldMapper(MAPPING_CONFIG)
        builder = JSONLDBuilder(_make_shape(MAPPING_CONFIG))

        raw_row = next(iter(adapter.read()))
        mapped = mapper.map(raw_row)
        return builder.build_one(mapped)

    def test_has_location_present(self):
        doc = self._build_doc()
        assert "hasLocation" in doc

    def test_outer_node_type_is_location(self):
        doc = self._build_doc()
        location = doc["hasLocation"]
        assert location["@type"] == "Location"

    def test_inner_node_type_is_location_address(self):
        doc = self._build_doc()
        inner = doc["hasLocation"]["hasLocationAddress"]
        assert inner["@type"] == "LocationAddress"

    def test_address_fields_on_inner_node(self):
        doc = self._build_doc()
        inner = doc["hasLocation"]["hasLocationAddress"]
        assert inner["AddressCity"] == "GRAND RAPIDS"
        assert inner["AddressStreetNumberAndName"] == "100 Main St"

    def test_fields_not_on_outer_node(self):
        doc = self._build_doc()
        outer = doc["hasLocation"]
        assert "AddressCity" not in outer
        assert "AddressStreetNumberAndName" not in outer

    def test_multiple_addresses_produce_list(self):
        """Two satellite rows → hasLocation is a list of two Location nodes."""
        two_addresses = [
            {"OrgId": "ORG-1", "AddressCity": "GRAND RAPIDS", "AddressStreetNumberAndName": "100 Main St"},
            {"OrgId": "ORG-1", "AddressCity": "LANSING", "AddressStreetNumberAndName": "200 Oak Ave"},
        ]
        primary = DictAdapter(PRIMARY_ROWS)
        addresses = DictAdapter(two_addresses)
        adapter = RelationalAdapter(
            primary=primary,
            join_key="OrgId",
            satellites={"addresses": addresses},
        )
        mapper = FieldMapper(MAPPING_CONFIG)
        builder = JSONLDBuilder(_make_shape(MAPPING_CONFIG))

        raw_row = next(iter(adapter.read()))
        mapped = mapper.map(raw_row)
        doc = builder.build_one(mapped)

        locations = doc["hasLocation"]
        assert isinstance(locations, list)
        assert len(locations) == 2
        cities = {loc["hasLocationAddress"]["AddressCity"] for loc in locations}
        assert cities == {"GRAND RAPIDS", "LANSING"}
