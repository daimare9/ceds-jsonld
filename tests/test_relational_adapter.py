"""Tests for RelationalAdapter and FieldMapper source_table support."""

from __future__ import annotations

from pathlib import Path

import pytest

from ceds_jsonld.adapters.dict_adapter import DictAdapter
from ceds_jsonld.adapters.relational_adapter import RELATED_KEY, RelationalAdapter
from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.exceptions import AdapterError
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeDefinition

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

RELATIONAL_MAPPING: dict = {
    "shape": "TestShape",
    "context_url": "https://example.org/ctx.json",
    "base_uri": "cepi:test/",
    "id_source": "student_id",
    "type": "Student",
    "properties": {
        "hasIdentification": {
            "type": "Identification",
            "cardinality": "multiple",
            "source_table": "identifications",
            "fields": {
                "IdentifierValue": {
                    "source": "id_value",
                    "target": "IdentifierValue",
                },
                "IdentifierType": {
                    "source": "id_type",
                    "target": "IdentifierType",
                    "optional": True,
                },
            },
        }
    },
}

FULL_MAPPING: dict = {
    "shape": "StudentShape",
    "context_url": "https://example.org/ctx.json",
    "base_uri": "cepi:student/",
    "id_source": "student_id",
    "type": "Student",
    "properties": {
        "hasPersonName": {
            "type": "PersonName",
            "cardinality": "single",
            "fields": {
                "FirstName": {"source": "first_name", "target": "FirstName"},
                "LastName": {"source": "last_name", "target": "LastOrSurname"},
            },
        },
        "hasIdentification": {
            "type": "Identification",
            "cardinality": "multiple",
            "source_table": "identifications",
            "fields": {
                "IdentifierValue": {"source": "id_value", "target": "IdentifierValue"},
                "IdentifierType": {"source": "id_type", "target": "IdentifierType", "optional": True},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# RelationalAdapter unit tests
# ---------------------------------------------------------------------------


def test_relational_adapter_basic_join():
    primary = DictAdapter(
        [
            {"student_id": "1", "first_name": "Alice"},
            {"student_id": "2", "first_name": "Bob"},
        ]
    )
    ids_sat = DictAdapter(
        [
            {"student_id": "1", "id_type": "SSN", "id_value": "111-11-1111"},
            {"student_id": "1", "id_type": "State", "id_value": "MI001"},
            {"student_id": "2", "id_type": "SSN", "id_value": "222-22-2222"},
        ]
    )
    adapter = RelationalAdapter(
        primary=primary,
        join_key="student_id",
        satellites={"identifications": ids_sat},
    )
    rows = list(adapter.read())

    assert len(rows) == 2
    alice = rows[0]
    assert alice["first_name"] == "Alice"
    assert len(alice[RELATED_KEY]["identifications"]) == 2

    bob = rows[1]
    assert bob[RELATED_KEY]["identifications"][0]["id_type"] == "SSN"
    assert len(bob[RELATED_KEY]["identifications"]) == 1


def test_relational_adapter_empty_satellites_raises():
    with pytest.raises(AdapterError, match="at least one satellite"):
        RelationalAdapter(
            primary=DictAdapter([{"id": "1"}]),
            join_key="id",
            satellites={},
        )


def test_relational_adapter_blank_join_key_raises():
    with pytest.raises(AdapterError, match="non-empty string"):
        RelationalAdapter(
            primary=DictAdapter([{"id": "1"}]),
            join_key="  ",
            satellites={"x": DictAdapter([])},
        )


def test_relational_adapter_no_satellite_match_yields_empty_list():
    primary = DictAdapter([{"student_id": "99", "name": "Ghost"}])
    sat = DictAdapter([{"student_id": "1", "code": "SSN"}])
    adapter = RelationalAdapter(primary=primary, join_key="student_id", satellites={"ids": sat})
    rows = list(adapter.read())
    assert rows[0][RELATED_KEY]["ids"] == []


def test_relational_adapter_multiple_satellites():
    primary = DictAdapter([{"id": "1", "name": "Alice"}])
    races = DictAdapter([{"id": "1", "race": "Asian"}])
    ids = DictAdapter([{"id": "1", "id_val": "MI001"}])
    adapter = RelationalAdapter(
        primary=primary,
        join_key="id",
        satellites={"races": races, "ids": ids},
    )
    rows = list(adapter.read())
    related = rows[0][RELATED_KEY]
    assert "races" in related
    assert "ids" in related
    assert related["races"][0]["race"] == "Asian"
    assert related["ids"][0]["id_val"] == "MI001"


def test_relational_adapter_custom_satellite_join_key():
    """Support different FK column names in primary vs satellite."""
    primary = DictAdapter([{"person_id": "1", "name": "Bob"}])
    sat = DictAdapter([{"student_fk": "1", "val": "X"}])
    adapter = RelationalAdapter(
        primary=primary,
        join_key="person_id",
        satellites={"data": sat},
        satellite_join_key="student_fk",
    )
    rows = list(adapter.read())
    assert rows[0][RELATED_KEY]["data"][0]["val"] == "X"


def test_relational_adapter_satellite_missing_fk_skipped():
    """Satellite rows with no FK value are skipped."""
    primary = DictAdapter([{"id": "1", "name": "Alice"}])
    sat = DictAdapter(
        [
            {"id": "1", "code": "SSN"},
            {"id": "", "code": "BAD"},
            {"id": None, "code": "ALSO_BAD"},
        ]
    )
    adapter = RelationalAdapter(primary=primary, join_key="id", satellites={"ids": sat})
    rows = list(adapter.read())
    # Only the one valid satellite row is linked
    assert len(rows[0][RELATED_KEY]["ids"]) == 1
    assert rows[0][RELATED_KEY]["ids"][0]["code"] == "SSN"


def test_relational_adapter_count_delegates_to_primary():
    primary = DictAdapter([{"id": "1"}, {"id": "2"}])
    sat = DictAdapter([])
    adapter = RelationalAdapter(primary=primary, join_key="id", satellites={"x": sat})
    # count() delegates to the primary adapter; DictAdapter returns its row count
    assert adapter.count() == 2


def test_relational_adapter_primary_row_fields_preserved():
    """All primary row fields must appear in the enriched output."""
    primary = DictAdapter([{"id": "1", "a": "foo", "b": "bar"}])
    sat = DictAdapter([{"id": "1", "val": "X"}])
    adapter = RelationalAdapter(primary=primary, join_key="id", satellites={"s": sat})
    row = list(adapter.read())[0]
    assert row["a"] == "foo"
    assert row["b"] == "bar"
    assert RELATED_KEY in row


def test_relational_adapter_empty_primary():
    """No rows in primary → no rows out."""
    primary = DictAdapter([])
    sat = DictAdapter([{"id": "1", "val": "X"}])
    adapter = RelationalAdapter(primary=primary, join_key="id", satellites={"s": sat})
    assert list(adapter.read()) == []


def test_relational_adapter_importable_from_top_level():
    from ceds_jsonld import RelationalAdapter as RA  # noqa: F401

    assert RA is RelationalAdapter


# ---------------------------------------------------------------------------
# FieldMapper source_table tests
# ---------------------------------------------------------------------------


def test_field_mapper_source_table():
    primary = DictAdapter([{"student_id": "1", "name": "Alice"}])
    sat = DictAdapter(
        [
            {"student_id": "1", "id_value": "MI001", "id_type": "State"},
            {"student_id": "1", "id_value": "SSN123", "id_type": "SSN"},
        ]
    )
    adapter = RelationalAdapter(
        primary=primary,
        join_key="student_id",
        satellites={"identifications": sat},
    )
    mapper = FieldMapper(RELATIONAL_MAPPING)
    rows = list(adapter.read())
    mapped = mapper.map(rows[0])

    assert mapped["__id__"] == "1"
    ids = mapped["hasIdentification"]
    assert len(ids) == 2
    assert ids[0]["IdentifierValue"] == "MI001"
    assert ids[0]["IdentifierType"] == "State"
    assert ids[1]["IdentifierValue"] == "SSN123"


def test_field_mapper_source_table_no_satellite_rows():
    """Property is absent from output when there are no satellite rows."""
    primary = DictAdapter([{"student_id": "99", "name": "Ghost"}])
    sat = DictAdapter([{"student_id": "1", "id_value": "X", "id_type": "Y"}])
    adapter = RelationalAdapter(primary=primary, join_key="student_id", satellites={"identifications": sat})
    mapper = FieldMapper(RELATIONAL_MAPPING)
    rows = list(adapter.read())
    mapped = mapper.map(rows[0])
    assert "hasIdentification" not in mapped


def test_field_mapper_source_table_optional_field_missing():
    """Optional satellite field missing → instance still produced without that field."""
    mapping = {
        "shape": "T",
        "context_url": "https://x.org/ctx.json",
        "base_uri": "cepi:t/",
        "id_source": "id",
        "type": "T",
        "properties": {
            "hasData": {
                "type": "Data",
                "cardinality": "multiple",
                "source_table": "data_table",
                "fields": {
                    "Required": {"source": "req", "target": "Required"},
                    "Optional": {"source": "opt", "target": "Optional", "optional": True},
                },
            }
        },
    }
    primary = DictAdapter([{"id": "1"}])
    sat = DictAdapter([{"id": "1", "req": "present"}])  # 'opt' column absent
    adapter = RelationalAdapter(primary=primary, join_key="id", satellites={"data_table": sat})
    mapper = FieldMapper(mapping)
    rows = list(adapter.read())
    mapped = mapper.map(rows[0])
    instances = mapped["hasData"]
    assert len(instances) == 1
    assert instances[0]["Required"] == "present"
    assert "Optional" not in instances[0]


def test_field_mapper_source_table_with_transform():
    """Transforms are applied to satellite field values."""
    mapping = {
        "shape": "T",
        "context_url": "https://x.org/ctx.json",
        "base_uri": "cepi:t/",
        "id_source": "id",
        "type": "T",
        "properties": {
            "hasRace": {
                "type": "Race",
                "cardinality": "multiple",
                "source_table": "races",
                "fields": {
                    "hasRaceCode": {
                        "source": "race_code",
                        "target": "hasRaceCode",
                        "transform": "race_prefix",
                    }
                },
            }
        },
    }
    primary = DictAdapter([{"id": "1"}])
    sat = DictAdapter([{"id": "1", "race_code": "Asian"}])
    adapter = RelationalAdapter(primary=primary, join_key="id", satellites={"races": sat})
    mapper = FieldMapper(mapping)
    rows = list(adapter.read())
    mapped = mapper.map(rows[0])
    assert mapped["hasRace"][0]["hasRaceCode"] == "RaceAndEthnicity_Asian"


def test_field_mapper_source_table_flat_adapter_graceful_degradation():
    """Using source_table with a non-relational adapter → property omitted, no crash."""
    mapper = FieldMapper(RELATIONAL_MAPPING)
    flat_row = {"student_id": "1", "name": "Alice"}  # no __related__
    mapped = mapper.map(flat_row)
    assert "hasIdentification" not in mapped


# ---------------------------------------------------------------------------
# End-to-end integration: RelationalAdapter → FieldMapper → JSONLDBuilder
# ---------------------------------------------------------------------------


def test_full_pipeline_relational():
    """Primary + satellite → JSON-LD with embedded typed array."""
    primary = DictAdapter(
        [
            {"student_id": "1", "first_name": "Alice", "last_name": "Smith"},
        ]
    )
    sat = DictAdapter(
        [
            {"student_id": "1", "id_value": "MI001", "id_type": "State"},
            {"student_id": "1", "id_value": "SSN123", "id_type": "SSN"},
        ]
    )
    adapter = RelationalAdapter(primary=primary, join_key="student_id", satellites={"identifications": sat})
    shape_def = ShapeDefinition(
        name="StudentShape",
        base_dir=Path("."),
        shacl_path=Path("."),
        context={},
        mapping_config=FULL_MAPPING,
    )
    mapper = FieldMapper(FULL_MAPPING)
    builder = JSONLDBuilder(shape_def)

    rows = list(adapter.read())
    mapped = mapper.map(rows[0])
    doc = builder.build_one(mapped)

    assert doc["@type"] == "Student"
    assert doc["@id"] == "cepi:student/1"
    assert doc["hasPersonName"]["FirstName"] == "Alice"
    assert doc["hasPersonName"]["LastOrSurname"] == "Smith"
    ids = doc["hasIdentification"]
    assert isinstance(ids, list)
    assert len(ids) == 2
    assert ids[0]["IdentifierValue"] == "MI001"
    assert ids[1]["IdentifierType"] == "SSN"


def test_full_pipeline_mixed_flat_and_relational():
    """A shape can mix flat primary fields and satellite source_table properties."""
    primary = DictAdapter(
        [
            {"student_id": "1", "first_name": "Bob", "last_name": "Jones"},
        ]
    )
    # No satellite rows for this student — hasIdentification should be absent
    sat = DictAdapter([])
    adapter = RelationalAdapter(primary=primary, join_key="student_id", satellites={"identifications": sat})
    shape_def = ShapeDefinition(
        name="StudentShape",
        base_dir=Path("."),
        shacl_path=Path("."),
        context={},
        mapping_config=FULL_MAPPING,
    )
    mapper = FieldMapper(FULL_MAPPING)
    builder = JSONLDBuilder(shape_def)

    rows = list(adapter.read())
    mapped = mapper.map(rows[0])
    doc = builder.build_one(mapped)

    assert doc["hasPersonName"]["FirstName"] == "Bob"
    assert "hasIdentification" not in doc


def test_full_pipeline_multiple_primary_rows():
    """Multiple primary rows each get their own satellite data."""
    primary = DictAdapter(
        [
            {"student_id": "1", "first_name": "Alice", "last_name": "Smith"},
            {"student_id": "2", "first_name": "Bob", "last_name": "Jones"},
        ]
    )
    sat = DictAdapter(
        [
            {"student_id": "1", "id_value": "MI001", "id_type": "State"},
            {"student_id": "2", "id_value": "MI002", "id_type": "State"},
            {"student_id": "2", "id_value": "SSN999", "id_type": "SSN"},
        ]
    )
    adapter = RelationalAdapter(primary=primary, join_key="student_id", satellites={"identifications": sat})
    shape_def = ShapeDefinition(
        name="StudentShape",
        base_dir=Path("."),
        shacl_path=Path("."),
        context={},
        mapping_config=FULL_MAPPING,
    )
    mapper = FieldMapper(FULL_MAPPING)
    builder = JSONLDBuilder(shape_def)

    rows = list(adapter.read())
    docs = [builder.build_one(mapper.map(r)) for r in rows]

    assert docs[0]["@id"] == "cepi:student/1"
    # One satellite row → builder unwraps to a plain dict (not a list)
    alice_id = docs[0]["hasIdentification"]
    assert isinstance(alice_id, dict)
    assert alice_id["IdentifierValue"] == "MI001"

    assert docs[1]["@id"] == "cepi:student/2"
    # Two satellite rows → builder keeps as a list
    bob_ids = docs[1]["hasIdentification"]
    assert isinstance(bob_ids, list)
    assert len(bob_ids) == 2
