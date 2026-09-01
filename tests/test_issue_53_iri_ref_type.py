"""Tests for IRI reference values (``sh:nodeKind sh:IRI``) — 1.8 feature.

A property declared ``type: id_ref`` (or ``iri_ref``) must serialize each value
as the node-object form ``{"@id": <value>}`` with **no** ``@type`` key.  This
supports SHACL object-property references such as
``OrganizationRelationship → hasOrganizationRelationshipSubject``.

Acceptance criteria:
- A property serializes each value as ``{"@id": <source value>}`` with no @type.
- Works for both ``cardinality: single`` and ``cardinality: multiple``.
- No ``@type`` key is ever emitted for such properties.
"""

from __future__ import annotations

from pathlib import Path

from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeDefinition


def _make_shape(mapping_config: dict) -> ShapeDefinition:
    """Build a minimal ShapeDefinition from a mapping config dict."""
    return ShapeDefinition(
        name="test",
        base_dir=Path("."),
        shacl_path=Path("test.ttl"),
        context={},
        mapping_config=mapping_config,
    )


SUBJECT_URI = "https://cepi-dev.state.mi.us/organization/03040"
OBJECT_URI = "https://cepi-dev.state.mi.us/organization/03041"


SINGLE_REF = {
    "type": "OrganizationRelationship",
    "base_uri": "urn:test/",
    "context_url": "https://example.org/ctx",
    "id_source": "Id",
    "properties": {
        "hasOrganizationRelationshipSubject": {
            "type": "id_ref",
            "cardinality": "single",
            "fields": {
                "orgId": {
                    "source": "hasOrganizationRelationshipSubject.@id",
                    "target": "@id",
                },
            },
        },
    },
}


MULTIPLE_REF = {
    "type": "OrganizationRelationship",
    "base_uri": "urn:test/",
    "context_url": "https://example.org/ctx",
    "id_source": "Id",
    "properties": {
        "hasOrganizationRelationshipObject": {
            "type": "iri_ref",
            "cardinality": "multiple",
            "split_on": "|",
            "fields": {
                "orgId": {
                    "source": "hasOrganizationRelationshipObject.@id",
                    "target": "@id",
                },
            },
        },
    },
}


NESTED_REF = {
    "type": "Organization",
    "base_uri": "urn:test/",
    "context_url": "https://example.org/ctx",
    "id_source": "Id",
    "properties": {
        "hasOrganizationRelationship": {
            "type": "OrganizationRelationship",
            "cardinality": "single",
            "fields": {
                "relType": {
                    "source": "relType",
                    "target": "relationshipType",
                    "optional": True,
                },
            },
            "properties": {
                "hasOrganizationRelationshipSubject": {
                    "type": "id_ref",
                    "cardinality": "single",
                    "fields": {
                        "orgId": {
                            "source": "subject.@id",
                            "target": "@id",
                        },
                    },
                },
                "hasOrganizationRelationshipObject": {
                    "type": "iri_ref",
                    "cardinality": "multiple",
                    "split_on": "|",
                    "fields": {
                        "orgId": {
                            "source": "object.@id",
                            "target": "@id",
                        },
                    },
                },
            },
        },
    },
}


class TestSingleIriRef:
    """cardinality: single → a single {"@id": ...} node."""

    def test_emits_id_only_node(self) -> None:
        shape = _make_shape(SINGLE_REF)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "hasOrganizationRelationshipSubject.@id": SUBJECT_URI}
        doc = builder.build_one(mapper.map(row))
        assert doc["hasOrganizationRelationshipSubject"] == {"@id": SUBJECT_URI}

    def test_no_type_key(self) -> None:
        shape = _make_shape(SINGLE_REF)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "hasOrganizationRelationshipSubject.@id": SUBJECT_URI}
        doc = builder.build_one(mapper.map(row))
        node = doc["hasOrganizationRelationshipSubject"]
        assert "@type" not in node
        assert list(node.keys()) == ["@id"]


class TestMultipleIriRef:
    """cardinality: multiple → an array of {"@id": ...} nodes."""

    def test_emits_array_of_id_nodes(self) -> None:
        shape = _make_shape(MULTIPLE_REF)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {
            "Id": "1",
            "hasOrganizationRelationshipObject.@id": f"{SUBJECT_URI}|{OBJECT_URI}",
        }
        doc = builder.build_one(mapper.map(row))
        assert doc["hasOrganizationRelationshipObject"] == [
            {"@id": SUBJECT_URI},
            {"@id": OBJECT_URI},
        ]

    def test_single_value_multiple_cardinality_unwraps(self) -> None:
        shape = _make_shape(MULTIPLE_REF)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {"Id": "1", "hasOrganizationRelationshipObject.@id": SUBJECT_URI}
        doc = builder.build_one(mapper.map(row))
        assert doc["hasOrganizationRelationshipObject"] == {"@id": SUBJECT_URI}

    def test_no_type_key_on_any_node(self) -> None:
        shape = _make_shape(MULTIPLE_REF)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {
            "Id": "1",
            "hasOrganizationRelationshipObject.@id": f"{SUBJECT_URI}|{OBJECT_URI}",
        }
        doc = builder.build_one(mapper.map(row))
        for node in doc["hasOrganizationRelationshipObject"]:
            assert "@type" not in node
            assert list(node.keys()) == ["@id"]


class TestNestedIriRef:
    """id_ref / iri_ref declared inside a sub-node's ``properties:`` block."""

    def test_nested_single_ref_is_id_only(self) -> None:
        shape = _make_shape(NESTED_REF)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {
            "Id": "1",
            "relType": "parent",
            "subject.@id": SUBJECT_URI,
            "object.@id": OBJECT_URI,
        }
        doc = builder.build_one(mapper.map(row))
        rel = doc["hasOrganizationRelationship"]
        assert rel["@type"] == "OrganizationRelationship"
        assert rel["hasOrganizationRelationshipSubject"] == {"@id": SUBJECT_URI}

    def test_nested_ref_has_no_type_key(self) -> None:
        shape = _make_shape(NESTED_REF)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {
            "Id": "1",
            "relType": "parent",
            "subject.@id": SUBJECT_URI,
            "object.@id": OBJECT_URI,
        }
        doc = builder.build_one(mapper.map(row))
        subject = doc["hasOrganizationRelationship"]["hasOrganizationRelationshipSubject"]
        assert "@type" not in subject
        assert list(subject.keys()) == ["@id"]

    def test_nested_multiple_ref_is_array_of_id_nodes(self) -> None:
        shape = _make_shape(NESTED_REF)
        mapper = FieldMapper(shape.mapping_config)
        builder = JSONLDBuilder(shape)
        row = {
            "Id": "1",
            "relType": "parent",
            "subject.@id": SUBJECT_URI,
            "object.@id": f"{SUBJECT_URI}|{OBJECT_URI}",
        }
        doc = builder.build_one(mapper.map(row))
        objects = doc["hasOrganizationRelationship"]["hasOrganizationRelationshipObject"]
        assert objects == [{"@id": SUBJECT_URI}, {"@id": OBJECT_URI}]
        for node in objects:
            assert "@type" not in node
