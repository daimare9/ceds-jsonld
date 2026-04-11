"""Tests for the Pipeline orchestrator.

Covers: stream(), build_all(), to_json(), to_ndjson(), to_cosmos() stub.
Uses the Person shape + DictAdapter to exercise the full chain without
needing external files beyond the shipped ontology.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ceds_jsonld.adapters.csv_adapter import CSVAdapter
from ceds_jsonld.adapters.dict_adapter import DictAdapter
from ceds_jsonld.exceptions import PipelineError
from ceds_jsonld.pipeline import Pipeline
from ceds_jsonld.registry import ShapeRegistry

PERSON_CSV = (
    Path(__file__).resolve().parent.parent / "src" / "ceds_jsonld" / "ontologies" / "person" / "person_sample.csv"
)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture()
def registry() -> ShapeRegistry:
    """A fresh registry with the Person shape loaded."""
    reg = ShapeRegistry()
    reg.load_shape("person")
    return reg


@pytest.fixture()
def sample_rows() -> list[dict[str, Any]]:
    """Two minimal Person rows for pipeline tests."""
    return [
        {
            "FirstName": "Alice",
            "MiddleName": "",
            "LastName": "Smith",
            "GenerationCodeOrSuffix": "",
            "Birthdate": "1990-01-15",
            "Sex": "Female",
            "RaceEthnicity": "White",
            "PersonIdentifiers": "111222333",
            "IdentificationSystems": "PersonIdentificationSystem_SSN",
            "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
        },
        {
            "FirstName": "Bob",
            "MiddleName": "J",
            "LastName": "Jones",
            "GenerationCodeOrSuffix": "",
            "Birthdate": "1985-06-20",
            "Sex": "Male",
            "RaceEthnicity": "Hispanic",
            "PersonIdentifiers": "444555666",
            "IdentificationSystems": "PersonIdentificationSystem_SSN",
            "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
        },
    ]


# =====================================================================
# Pipeline construction
# =====================================================================


class TestPipelineConstruction:
    """Verify Pipeline initializes correctly and fails on bad shapes."""

    def test_construct_with_dict_adapter(self, registry: ShapeRegistry, sample_rows: list[dict]) -> None:
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        assert pipeline is not None

    def test_bad_shape_raises(self, registry: ShapeRegistry) -> None:
        source = DictAdapter([{"a": 1}])
        with pytest.raises(PipelineError, match="not found"):
            Pipeline(source=source, shape="nonexistent", registry=registry)


# =====================================================================
# Validation metadata
# =====================================================================


class TestValidateMetadata:
    """Pipeline.validate() populates run metadata on the result."""

    def test_validate_populates_run_metadata(self, registry: ShapeRegistry, sample_rows: list[dict]) -> None:
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        result = pipeline.validate()
        assert result.run_id  # non-empty UUID
        assert result.timestamp  # non-empty ISO timestamp
        assert result.shape_name == "person"
        assert result.source_name == "DictAdapter"
        assert result.library_version  # non-empty version string


# =====================================================================
# stream()
# =====================================================================


class TestStream:
    """Pipeline.stream() yields JSON-LD documents one at a time."""

    def test_stream_yields_dicts(self, registry: ShapeRegistry, sample_rows: list[dict]) -> None:
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        docs = list(pipeline.stream())
        assert len(docs) == 2

    def test_stream_docs_have_context(self, registry: ShapeRegistry, sample_rows: list[dict]) -> None:
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        doc = next(pipeline.stream())
        assert "@context" in doc
        assert "@type" in doc
        assert doc["@type"] == "Person"

    def test_stream_doc_ids_unique(self, registry: ShapeRegistry, sample_rows: list[dict]) -> None:
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        ids = [doc["@id"] for doc in pipeline.stream()]
        assert len(set(ids)) == 2

    def test_stream_empty_source(self, registry: ShapeRegistry) -> None:
        source = DictAdapter([])
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        assert list(pipeline.stream()) == []


# =====================================================================
# build_all()
# =====================================================================


class TestBuildAll:
    """Pipeline.build_all() returns a list of all JSON-LD documents."""

    def test_build_all_returns_list(self, registry: ShapeRegistry, sample_rows: list[dict]) -> None:
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        docs = pipeline.build_all()
        assert isinstance(docs, list)
        assert len(docs) == 2

    def test_build_all_matches_stream(self, registry: ShapeRegistry, sample_rows: list[dict]) -> None:
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        streamed = list(pipeline.stream())
        # build_all uses a new iteration, but results should match structurally
        source2 = DictAdapter(sample_rows)
        pipeline2 = Pipeline(source=source2, shape="person", registry=registry)
        built = pipeline2.build_all()
        assert streamed == built


# =====================================================================
# to_json()
# =====================================================================


class TestToJSON:
    """Pipeline.to_json() writes a JSON array to a file."""

    def test_to_json_creates_file(
        self,
        tmp_path: Path,
        registry: ShapeRegistry,
        sample_rows: list[dict],
    ) -> None:
        out = tmp_path / "output.json"
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        result = pipeline.to_json(out)
        assert out.exists()
        assert result.bytes_written > 0

    def test_to_json_valid_json(
        self,
        tmp_path: Path,
        registry: ShapeRegistry,
        sample_rows: list[dict],
    ) -> None:
        out = tmp_path / "output.json"
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        pipeline.to_json(out)
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_to_json_creates_parent_dirs(
        self,
        tmp_path: Path,
        registry: ShapeRegistry,
        sample_rows: list[dict],
    ) -> None:
        out = tmp_path / "sub" / "dir" / "output.json"
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        pipeline.to_json(out)
        assert out.exists()


# =====================================================================
# to_ndjson()
# =====================================================================


class TestToNDJSON:
    """Pipeline.to_ndjson() writes one JSON document per line."""

    def test_to_ndjson_creates_file(
        self,
        tmp_path: Path,
        registry: ShapeRegistry,
        sample_rows: list[dict],
    ) -> None:
        out = tmp_path / "output.ndjson"
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        result = pipeline.to_ndjson(out)
        assert out.exists()
        assert result.bytes_written > 0

    def test_to_ndjson_valid_lines(
        self,
        tmp_path: Path,
        registry: ShapeRegistry,
        sample_rows: list[dict],
    ) -> None:
        out = tmp_path / "output.ndjson"
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        pipeline.to_ndjson(out)
        lines = [line for line in out.read_text(encoding="utf-8").strip().split("\n") if line.strip()]
        assert len(lines) == 2
        for line in lines:
            doc = json.loads(line)
            assert "@type" in doc

    def test_to_ndjson_creates_parent_dirs(
        self,
        tmp_path: Path,
        registry: ShapeRegistry,
        sample_rows: list[dict],
    ) -> None:
        out = tmp_path / "deep" / "path" / "output.ndjson"
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        pipeline.to_ndjson(out)
        assert out.exists()


# =====================================================================
# to_cosmos() stub
# =====================================================================


class TestToCosmos:
    """Pipeline.to_cosmos() is now tested in test_cosmos.py (Phase 4)."""

    def test_to_cosmos_requires_arguments(self, registry: ShapeRegistry, sample_rows: list[dict]) -> None:
        """to_cosmos() now requires endpoint/credential/database args."""
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        with pytest.raises(TypeError):
            pipeline.to_cosmos()  # type: ignore[call-arg]


# =====================================================================
# Pipeline with mapping overrides
# =====================================================================


class TestPipelineMappingOverrides:
    """Pipeline(source_overrides=...) lets users remap columns without leaving the Pipeline API."""

    def _make_rows_with_renamed_cols(self) -> list[dict[str, Any]]:
        """Sample rows using non-standard column names."""
        return [
            {
                "FIRST_NM": "Alice",
                "MID_NM": "",
                "LAST_NM": "Smith",
                "SUFFIX": "",
                "DOB": "1990-01-15",
                "GENDER": "Female",
                "RACE": "White",
                "IDS": "111222333",
                "ID_SYSTEMS": "PersonIdentificationSystem_SSN",
                "ID_TYPES": "PersonIdentifierType_PersonIdentifier",
            },
        ]

    def test_source_overrides_remap_columns(self, registry: ShapeRegistry) -> None:
        rows = self._make_rows_with_renamed_cols()
        source = DictAdapter(rows)
        pipeline = Pipeline(
            source=source,
            shape="person",
            registry=registry,
            source_overrides={
                "hasPersonName": {
                    "FirstName": "FIRST_NM",
                    "MiddleName": "MID_NM",
                    "LastOrSurname": "LAST_NM",
                    "GenerationCodeOrSuffix": "SUFFIX",
                },
                "hasPersonBirth": {
                    "Birthdate": "DOB",
                },
                "hasPersonSexGender": {
                    "hasSex": "GENDER",
                },
                "hasPersonDemographicRace": {
                    "hasRaceAndEthnicity": "RACE",
                },
                "hasPersonIdentification": {
                    "PersonIdentifier": "IDS",
                    "hasPersonIdentificationSystem": "ID_SYSTEMS",
                    "hasPersonIdentifierType": "ID_TYPES",
                },
            },
            id_source="IDS",
        )
        docs = pipeline.build_all()
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Person"
        assert doc["hasPersonName"]["FirstName"] == "Alice"
        assert doc["hasPersonName"]["LastOrSurname"] == "Smith"

    def test_id_source_override(self, registry: ShapeRegistry) -> None:
        rows = [
            {
                "FirstName": "Jane",
                "MiddleName": "",
                "LastName": "Doe",
                "GenerationCodeOrSuffix": "",
                "Birthdate": "2000-01-01",
                "Sex": "Female",
                "RaceEthnicity": "White",
                "STUDENT_ID": "STU_999",
                "IdentificationSystems": "PersonIdentificationSystem_SSN",
                "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
            },
        ]
        source = DictAdapter(rows)
        pipeline = Pipeline(
            source=source,
            shape="person",
            registry=registry,
            source_overrides={
                "hasPersonIdentification": {
                    "PersonIdentifier": "STUDENT_ID",
                },
            },
            id_source="STUDENT_ID",
            id_transform=None,
        )
        docs = pipeline.build_all()
        assert len(docs) == 1
        assert "STU_999" in docs[0]["@id"]

    def test_no_overrides_works_normally(self, registry: ShapeRegistry, sample_rows: list[dict]) -> None:
        """Passing no overrides should behave identically to the default Pipeline."""
        source = DictAdapter(sample_rows)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        docs = pipeline.build_all()
        assert len(docs) == 2
        assert docs[0]["hasPersonName"]["FirstName"] == "Alice"


# =====================================================================
# CSV → Pipeline integration
# =====================================================================


class TestCSVIntegration:
    """Full end-to-end: CSV file → Pipeline → JSON-LD documents."""

    def test_csv_to_stream(self, registry: ShapeRegistry) -> None:
        if not PERSON_CSV.exists():
            pytest.skip("person_sample.csv not found")
        source = CSVAdapter(PERSON_CSV)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        docs = list(pipeline.stream())
        assert len(docs) == 90
        # First record should be EDITH ADAMS
        assert "cepi:person/" in docs[0]["@id"]

    def test_csv_to_json_file(self, tmp_path: Path, registry: ShapeRegistry) -> None:
        if not PERSON_CSV.exists():
            pytest.skip("person_sample.csv not found")
        out = tmp_path / "persons.json"
        source = CSVAdapter(PERSON_CSV)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        result = pipeline.to_json(out)
        assert result.bytes_written > 0
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert len(parsed) == 90

    def test_csv_to_ndjson_file(self, tmp_path: Path, registry: ShapeRegistry) -> None:
        if not PERSON_CSV.exists():
            pytest.skip("person_sample.csv not found")
        out = tmp_path / "persons.ndjson"
        source = CSVAdapter(PERSON_CSV)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        result = pipeline.to_ndjson(out)
        assert result.bytes_written > 0
        lines = [l for l in out.read_text(encoding="utf-8").strip().split("\n") if l]
        assert len(lines) == 90


# =====================================================================
# Duplicate @id detection (issue #8)
# =====================================================================


class TestDuplicateIdWarning:
    """Verify build_all() warns when output contains duplicate @id values."""

    def test_sample_csv_has_unique_ids(self, registry: ShapeRegistry) -> None:
        """The shipped person_sample.csv must produce 90 docs with 90 unique @id values."""
        if not PERSON_CSV.exists():
            pytest.skip("person_sample.csv not found")
        source = CSVAdapter(PERSON_CSV)
        pipeline = Pipeline(source=source, shape="person", registry=registry)
        docs = pipeline.build_all()
        ids = [d["@id"] for d in docs]
        assert len(ids) == 90
        assert len(set(ids)) == 90, f"Expected 90 unique @ids, got {len(set(ids))}"

    def test_duplicate_ids_emit_warning(
        self,
        registry: ShapeRegistry,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When source data produces duplicate @ids, a warning is logged."""
        # Feed 3 rows with the same PersonIdentifier → same @id
        rows = [
            {
                "FirstName": "Alice",
                "LastName": "Smith",
                "Birthdate": "1990-01-15",
                "Sex": "Female",
                "RaceEthnicity": "White",
                "PersonIdentifiers": "111222333",
                "IdentificationSystems": "PersonIdentificationSystem_SSN",
                "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
            },
            {
                "FirstName": "Bob",
                "LastName": "Jones",
                "Birthdate": "1985-06-20",
                "Sex": "Male",
                "RaceEthnicity": "Hispanic",
                "PersonIdentifiers": "111222333",
                "IdentificationSystems": "PersonIdentificationSystem_SSN",
                "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
            },
            {
                "FirstName": "Carol",
                "LastName": "White",
                "Birthdate": "1988-03-10",
                "Sex": "Female",
                "RaceEthnicity": "Asian",
                "PersonIdentifiers": "999888777",
                "IdentificationSystems": "PersonIdentificationSystem_SSN",
                "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
            },
        ]
        import logging

        with caplog.at_level(logging.WARNING):
            source = DictAdapter(rows)
            pipeline = Pipeline(source=source, shape="person", registry=registry)
            docs = pipeline.build_all()

        assert len(docs) == 3
        # Two docs share the same @id, one is unique
        ids = [d["@id"] for d in docs]
        assert len(set(ids)) == 2

        # The warning should mention duplicate IDs
        assert any("duplicate_ids" in r.message for r in caplog.records)

    def test_no_warning_on_unique_ids(
        self,
        registry: ShapeRegistry,
        sample_rows: list[dict],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """No duplicate warning when all @ids are unique."""
        import logging

        with caplog.at_level(logging.WARNING):
            source = DictAdapter(sample_rows)
            pipeline = Pipeline(source=source, shape="person", registry=registry)
            docs = pipeline.build_all()

        assert len(docs) == 2
        assert len(set(d["@id"] for d in docs)) == 2
        assert not any("duplicate_ids" in r.message for r in caplog.records)
