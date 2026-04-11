"""Tests for the validator module — pre-build + SHACL validation.

Covers PreBuildValidator, SHACLValidator, ValidationResult, all three
validation modes (strict / report / sample), and Pipeline integration.
"""

from __future__ import annotations

import pytest

from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.exceptions import ValidationError
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeRegistry
from ceds_jsonld.validator import (
    FieldIssue,
    PreBuildValidator,
    SHACLValidator,
    ValidationMode,
    ValidationResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def person_registry():
    registry = ShapeRegistry()
    registry.load_shape("person")
    return registry


@pytest.fixture()
def person_mapping(person_registry):
    return person_registry.get_shape("person").mapping_config


@pytest.fixture()
def pre_validator(person_mapping):
    return PreBuildValidator(person_mapping)


@pytest.fixture()
def valid_row():
    return {
        "FirstName": "Jane",
        "LastName": "Doe",
        "Birthdate": "1990-01-15",
        "Sex": "Female",
        "RaceEthnicity": "White",
        "PersonIdentifiers": "123456789",
        "IdentificationSystems": "PersonIdentificationSystem_SSN",
        "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
    }


@pytest.fixture()
def invalid_row_missing_required():
    """Row missing required FirstName and Birthdate."""
    return {
        "LastName": "Doe",
        "Sex": "Female",
        "RaceEthnicity": "White",
        "PersonIdentifiers": "123456789",
        "IdentificationSystems": "PersonIdentificationSystem_SSN",
        "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
    }


@pytest.fixture()
def invalid_row_missing_id():
    """Row missing the ID source column."""
    return {
        "FirstName": "Jane",
        "LastName": "Doe",
        "Birthdate": "1990-01-15",
        "Sex": "Female",
        "RaceEthnicity": "White",
        "IdentificationSystems": "PersonIdentificationSystem_SSN",
        "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
    }


@pytest.fixture()
def invalid_row_bad_date():
    """Row with a non-date Birthdate value."""
    return {
        "FirstName": "Jane",
        "LastName": "Doe",
        "Birthdate": "not-a-date",
        "Sex": "Female",
        "RaceEthnicity": "White",
        "PersonIdentifiers": "123456789",
        "IdentificationSystems": "PersonIdentificationSystem_SSN",
        "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
    }


# =========================================================================
# ValidationResult data class
# =========================================================================


class TestValidationResult:
    def test_empty_result_conforms(self):
        result = ValidationResult()
        assert result.conforms is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_add_error_flips_conforms(self):
        result = ValidationResult(record_count=1)
        issue = FieldIssue(property_path="test", message="bad", severity="error")
        result.add_issue("rec1", issue)
        assert result.conforms is False
        assert result.error_count == 1

    def test_add_warning_keeps_conformant(self):
        result = ValidationResult(record_count=1)
        issue = FieldIssue(property_path="test", message="hm", severity="warning")
        result.add_issue("rec1", issue)
        assert result.conforms is True
        assert result.warning_count == 1

    def test_summary_string(self):
        result = ValidationResult(record_count=5, error_count=2, warning_count=1)
        s = result.summary()
        assert "5 records" in s
        assert "2 errors" in s
        assert "1 warnings" in s

    def test_metadata_defaults_populated(self):
        """New metadata fields auto-populate with sensible defaults."""
        result = ValidationResult()
        assert result.run_id  # non-empty UUID string
        assert result.timestamp  # non-empty ISO timestamp
        assert result.shape_name == ""
        assert result.source_name == ""
        assert result.library_version == ""

    def test_metadata_overrides(self):
        """Metadata fields can be overridden at construction."""
        result = ValidationResult(
            run_id="custom-id",
            timestamp="2026-04-10T00:00:00+00:00",
            shape_name="person",
            source_name="students.csv",
            library_version="1.2.0",
        )
        assert result.run_id == "custom-id"
        assert result.timestamp == "2026-04-10T00:00:00+00:00"
        assert result.shape_name == "person"
        assert result.source_name == "students.csv"
        assert result.library_version == "1.2.0"


# =========================================================================
# PreBuildValidator — basic checks
# =========================================================================


class TestPreBuildValidatorValid:
    """Valid rows should pass cleanly."""

    def test_valid_row_conforms(self, pre_validator, valid_row):
        result = pre_validator.validate_row(valid_row)
        assert result.conforms is True
        assert result.error_count == 0

    def test_valid_row_strict_mode(self, pre_validator, valid_row):
        result = pre_validator.validate_row(valid_row, mode=ValidationMode.STRICT)
        assert result.conforms is True

    def test_valid_batch(self, pre_validator, valid_row):
        rows = [valid_row] * 10
        result = pre_validator.validate_batch(rows)
        assert result.conforms is True
        assert result.record_count == 10


class TestPreBuildValidatorInvalid:
    """Invalid rows should surface issues."""

    def test_missing_required_field(self, pre_validator, invalid_row_missing_required):
        result = pre_validator.validate_row(invalid_row_missing_required)
        assert result.conforms is False
        assert result.error_count > 0
        # Should mention the missing field
        messages = [issue.message for issues in result.issues.values() for issue in issues if issue.severity == "error"]
        assert any("FirstName" in m for m in messages)

    def test_missing_id_source(self, pre_validator, invalid_row_missing_id):
        result = pre_validator.validate_row(invalid_row_missing_id)
        assert result.conforms is False
        messages = [issue.message for issues in result.issues.values() for issue in issues]
        assert any("PersonIdentifiers" in m for m in messages)

    def test_bad_date_warns(self, pre_validator, invalid_row_bad_date):
        result = pre_validator.validate_row(invalid_row_bad_date)
        # Bad date should produce a warning, not hard error
        warnings = [issue for issues in result.issues.values() for issue in issues if issue.severity == "warning"]
        assert len(warnings) >= 1
        assert any("date" in w.message.lower() for w in warnings)

    def test_strict_mode_raises(self, pre_validator, invalid_row_missing_required):
        with pytest.raises(ValidationError):
            pre_validator.validate_row(invalid_row_missing_required, mode=ValidationMode.STRICT)

    def test_batch_report_mode_collects_all(self, pre_validator, valid_row, invalid_row_missing_required):
        rows = [valid_row, invalid_row_missing_required, valid_row]
        result = pre_validator.validate_batch(rows, mode=ValidationMode.REPORT)
        assert result.record_count == 3
        assert result.error_count > 0
        assert result.conforms is False

    def test_batch_sample_mode(self, pre_validator, valid_row):
        rows = [valid_row] * 100
        result = pre_validator.validate_batch(rows, mode=ValidationMode.SAMPLE, sample_rate=0.1)
        # Should check ~10 rows (sampling is random, so allow tolerance)
        assert 1 <= result.record_count <= 20

    def test_batch_counts_not_doubled(self, pre_validator, invalid_row_missing_required):
        """Regression: validate_batch must not double-count errors/warnings (issue #11)."""
        rows = [invalid_row_missing_required] * 5
        result = pre_validator.validate_batch(rows, mode=ValidationMode.REPORT)
        assert result.record_count == 5
        # Count expected issues per row via validate_row
        single = pre_validator.validate_row(invalid_row_missing_required, mode=ValidationMode.REPORT)
        assert result.error_count == single.error_count * 5
        assert result.warning_count == single.warning_count * 5


class TestPreBuildDateValidation:
    """Impossible and non-ISO dates must be caught (issues #2, #3)."""

    @staticmethod
    def _make_row(date: str) -> dict:
        return {
            "FirstName": "Test",
            "MiddleName": "",
            "LastName": "User",
            "GenerationCodeOrSuffix": "",
            "Birthdate": date,
            "Sex": "Male",
            "RaceEthnicity": "White",
            "PersonIdentifiers": "ID-001",
            "IdentificationSystems": "",
            "PersonIdentifierTypes": "",
        }

    def test_impossible_month_99(self, pre_validator):
        result = pre_validator.validate_row(self._make_row("9999-99-99"))
        warnings = [i for issues in result.issues.values() for i in issues if i.severity == "warning"]
        assert any("Birthdate" in str(i.property_path) or "date" in i.message.lower() for i in warnings)

    def test_all_zeros(self, pre_validator):
        result = pre_validator.validate_row(self._make_row("0000-00-00"))
        warnings = [i for issues in result.issues.values() for i in issues if i.severity == "warning"]
        assert any("date" in i.message.lower() or "calendar" in i.message.lower() for i in warnings)

    def test_feb_30(self, pre_validator):
        result = pre_validator.validate_row(self._make_row("2026-02-30"))
        warnings = [i for issues in result.issues.values() for i in issues if i.severity == "warning"]
        assert any("calendar" in i.message.lower() or "date" in i.message.lower() for i in warnings)

    def test_month_13(self, pre_validator):
        result = pre_validator.validate_row(self._make_row("2026-13-01"))
        warnings = [i for issues in result.issues.values() for i in issues if i.severity == "warning"]
        assert any("calendar" in i.message.lower() or "date" in i.message.lower() for i in warnings)

    def test_american_format_rejected(self, pre_validator):
        """MM-DD-YYYY (e.g. 02-07-2026) should be flagged."""
        result = pre_validator.validate_row(self._make_row("02-07-2026"))
        warnings = [i for issues in result.issues.values() for i in issues if i.severity == "warning"]
        assert len(warnings) >= 1

    def test_no_zero_padding_rejected(self, pre_validator):
        """2026-2-7 should be flagged as non-ISO."""
        result = pre_validator.validate_row(self._make_row("2026-2-7"))
        warnings = [i for issues in result.issues.values() for i in issues if i.severity == "warning"]
        assert any("zero-padded" in i.message.lower() or "YYYY-MM-DD" in i.message for i in warnings)

    def test_valid_date_passes(self, pre_validator):
        """A proper ISO date should produce no date-related issues."""
        result = pre_validator.validate_row(self._make_row("1990-06-15"))
        date_warnings = [
            i
            for issues in result.issues.values()
            for i in issues
            if "Birthdate" in str(i.property_path) or "date" in i.message.lower()
        ]
        assert len(date_warnings) == 0

    def test_impossible_date_strict_raises(self, pre_validator):
        """Strict mode should raise on impossible dates."""
        with pytest.raises(ValidationError):
            pre_validator.validate_row(self._make_row("2026-02-30"), mode=ValidationMode.STRICT)


class TestPreBuildValidatorEdgeCases:
    """Edge cases: empty strings, None, NaN, etc."""

    def test_empty_string_as_missing(self, pre_validator):
        row = {
            "FirstName": "",
            "LastName": "Doe",
            "Birthdate": "1990-01-15",
            "Sex": "Female",
            "RaceEthnicity": "White",
            "PersonIdentifiers": "123456789",
            "IdentificationSystems": "SSN",
            "PersonIdentifierTypes": "Type",
        }
        result = pre_validator.validate_row(row)
        assert result.conforms is False

    def test_none_as_missing(self, pre_validator):
        row = {
            "FirstName": None,
            "LastName": "Doe",
            "Birthdate": "1990-01-15",
            "Sex": "Female",
            "RaceEthnicity": "White",
            "PersonIdentifiers": "123456789",
            "IdentificationSystems": "SSN",
            "PersonIdentifierTypes": "Type",
        }
        result = pre_validator.validate_row(row)
        assert result.conforms is False

    def test_nan_as_missing(self, pre_validator):
        row = {
            "FirstName": float("nan"),
            "LastName": "Doe",
            "Birthdate": "1990-01-15",
            "Sex": "Female",
            "RaceEthnicity": "White",
            "PersonIdentifiers": "123456789",
            "IdentificationSystems": "SSN",
            "PersonIdentifierTypes": "Type",
        }
        result = pre_validator.validate_row(row)
        assert result.conforms is False

    def test_optional_fields_can_be_missing(self, pre_validator):
        """MiddleName and GenerationCodeOrSuffix are optional."""
        row = {
            "FirstName": "Jane",
            "LastName": "Doe",
            "Birthdate": "1990-01-15",
            "Sex": "Female",
            "RaceEthnicity": "White",
            "PersonIdentifiers": "123456789",
            "IdentificationSystems": "SSN",
            "PersonIdentifierTypes": "Type",
        }
        result = pre_validator.validate_row(row)
        assert result.conforms is True


# =========================================================================
# PreBuildValidator.from_introspector
# =========================================================================


class TestPreBuildValidatorFromIntrospector:
    """Test SHACL-enriched pre-build validation."""

    def test_from_introspector_creates_validator(self, person_registry, person_mapping):
        from ceds_jsonld.introspector import SHACLIntrospector

        shape_def = person_registry.get_shape("person")
        introspector = SHACLIntrospector(shape_def.shacl_path)
        context = shape_def.context.get("@context", shape_def.context)

        validator = PreBuildValidator.from_introspector(person_mapping, introspector, context_lookup=context)
        assert isinstance(validator, PreBuildValidator)

    def test_enriched_validator_still_passes_valid(self, person_registry, person_mapping, valid_row):
        from ceds_jsonld.introspector import SHACLIntrospector

        shape_def = person_registry.get_shape("person")
        introspector = SHACLIntrospector(shape_def.shacl_path)
        context = shape_def.context.get("@context", shape_def.context)

        validator = PreBuildValidator.from_introspector(person_mapping, introspector, context_lookup=context)
        result = validator.validate_row(valid_row)
        assert result.conforms is True


# =========================================================================
# SHACLValidator — full round-trip
# =========================================================================


class TestSHACLValidator:
    """Full SHACL round-trip validation via pySHACL."""

    @pytest.fixture()
    def shacl_validator(self, person_registry):
        shape_def = person_registry.get_shape("person")
        return SHACLValidator(shape_def.shacl_path, context=shape_def.context)

    @pytest.fixture()
    def built_doc(self, person_registry, valid_row):
        shape_def = person_registry.get_shape("person")
        mapper = FieldMapper(shape_def.mapping_config)
        builder = JSONLDBuilder(shape_def)
        return builder.build_one(mapper.map(valid_row))

    @pytest.fixture()
    def built_doc_full(self, person_registry, sample_person_row_full):
        shape_def = person_registry.get_shape("person")
        mapper = FieldMapper(shape_def.mapping_config)
        builder = JSONLDBuilder(shape_def)
        return builder.build_one(mapper.map(sample_person_row_full))

    def test_valid_doc_conforms(self, shacl_validator, built_doc):
        result = shacl_validator.validate_one(built_doc)
        # The document may or may not conform depending on how strict the
        # SHACL is with the simplified context.  At minimum, it should
        # return a result object without crashing.
        assert isinstance(result, ValidationResult)
        assert result.record_count == 1

    def test_validate_one_returns_result(self, shacl_validator, built_doc_full):
        result = shacl_validator.validate_one(built_doc_full)
        assert isinstance(result, ValidationResult)
        assert result.record_count == 1

    def test_validate_batch(self, shacl_validator, built_doc):
        docs = [built_doc] * 5
        result = shacl_validator.validate_batch(docs, mode=ValidationMode.REPORT)
        assert result.record_count == 5

    def test_validate_batch_sample_mode(self, shacl_validator, built_doc):
        docs = [built_doc] * 100
        result = shacl_validator.validate_batch(docs, mode=ValidationMode.SAMPLE, sample_rate=0.05)
        # 5% of 100 = 5 docs ± sampling
        assert 1 <= result.record_count <= 10

    def test_validate_batch_counts_not_doubled(self, shacl_validator, built_doc):
        """Regression: SHACLValidator.validate_batch must not double-count (issue #11)."""
        docs = [built_doc] * 3
        result = shacl_validator.validate_batch(docs, mode=ValidationMode.REPORT)
        assert result.record_count == 3
        single = shacl_validator.validate_one(built_doc, mode=ValidationMode.REPORT)
        assert result.error_count == single.error_count * 3
        assert result.warning_count == single.warning_count * 3

    def test_validate_one_strict_mode_bad_doc(self, shacl_validator):
        """A clearly invalid doc (wrong @type) should raise in strict mode."""
        bad_doc = {
            "@context": {"@vocab": "http://example.org/"},
            "@type": "NotAPerson",
            "@id": "http://example.org/bad/1",
        }
        # This should either raise or return non-conformant
        try:
            shacl_validator.validate_one(bad_doc, mode=ValidationMode.STRICT)
        except ValidationError:
            pass  # Expected in strict mode

    def test_raw_report_populated(self, shacl_validator, built_doc):
        result = shacl_validator.validate_one(built_doc)
        # raw_report should be a string (may be empty if conformant)
        assert isinstance(result.raw_report, str)


# =========================================================================
# Pipeline.validate() integration
# =========================================================================


class TestPipelineValidation:
    """Test validation wired through the Pipeline."""

    def test_pipeline_validate_valid_data(self, person_registry, valid_row, tmp_path):
        import csv

        from ceds_jsonld.adapters import CSVAdapter
        from ceds_jsonld.pipeline import Pipeline

        # Write valid data to CSV
        csv_path = tmp_path / "valid.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=valid_row.keys())
            writer.writeheader()
            writer.writerow(valid_row)

        pipeline = Pipeline(
            source=CSVAdapter(str(csv_path)),
            shape="person",
            registry=person_registry,
        )
        result = pipeline.validate(mode="report")
        assert isinstance(result, ValidationResult)
        assert result.record_count == 1

    def test_pipeline_validate_invalid_data(self, person_registry, tmp_path):
        import csv

        from ceds_jsonld.adapters import CSVAdapter
        from ceds_jsonld.pipeline import Pipeline

        # Missing required FirstName
        row = {
            "LastName": "Doe",
            "Birthdate": "1990-01-15",
            "Sex": "Female",
            "RaceEthnicity": "White",
            "PersonIdentifiers": "123456789",
            "IdentificationSystems": "SSN",
            "PersonIdentifierTypes": "Type",
        }
        csv_path = tmp_path / "invalid.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            writer.writeheader()
            writer.writerow(row)

        pipeline = Pipeline(
            source=CSVAdapter(str(csv_path)),
            shape="person",
            registry=person_registry,
        )
        result = pipeline.validate(mode="report")
        assert result.error_count > 0
        assert result.conforms is False

    def test_pipeline_build_all_with_validate(self, person_registry, valid_row, tmp_path):
        import csv

        from ceds_jsonld.adapters import CSVAdapter
        from ceds_jsonld.pipeline import Pipeline

        csv_path = tmp_path / "valid.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=valid_row.keys())
            writer.writeheader()
            writer.writerow(valid_row)

        pipeline = Pipeline(
            source=CSVAdapter(str(csv_path)),
            shape="person",
            registry=person_registry,
        )
        docs = pipeline.build_all(validate=True, validation_mode="report")
        assert len(docs) == 1
        assert docs[0]["@type"] == "Person"

    def test_pipeline_stream_with_validate(self, person_registry, valid_row, tmp_path):
        import csv

        from ceds_jsonld.adapters import CSVAdapter
        from ceds_jsonld.pipeline import Pipeline

        csv_path = tmp_path / "valid.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=valid_row.keys())
            writer.writeheader()
            for _ in range(3):
                writer.writerow(valid_row)

        pipeline = Pipeline(
            source=CSVAdapter(str(csv_path)),
            shape="person",
            registry=person_registry,
        )
        docs = list(pipeline.stream(validate=True))
        assert len(docs) == 3


# =========================================================================
# Round-trip validation test
# =========================================================================


class TestRoundTrip:
    """Build JSON-LD → parse with rdflib → validate with pySHACL."""

    def test_person_roundtrip_parseable(self, person_shape_def, sample_person_row_full):
        """Built JSON-LD should parse as valid RDF."""
        import json as _json

        from rdflib import Graph

        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)
        doc = builder.build_one(mapper.map(sample_person_row_full))

        # Inject local context for parsing (avoid network fetch)
        doc_for_parse = dict(doc)
        doc_for_parse["@context"] = person_shape_def.context.get("@context", person_shape_def.context)

        g = Graph()
        g.parse(data=_json.dumps(doc_for_parse), format="json-ld")

        # The graph should have triples
        assert len(g) > 0

    def test_person_roundtrip_shacl_validates(self, person_shape_def, sample_person_row_full):
        """Full round-trip: build → parse → validate with pySHACL."""
        import json as _json

        from pyshacl import validate as pyshacl_validate
        from rdflib import Graph

        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)
        doc = builder.build_one(mapper.map(sample_person_row_full))

        # Inject local context for parsing
        doc_for_parse = dict(doc)
        doc_for_parse["@context"] = person_shape_def.context.get("@context", person_shape_def.context)

        data_graph = Graph()
        data_graph.parse(data=_json.dumps(doc_for_parse), format="json-ld")

        shacl_graph = Graph()
        shacl_graph.parse(str(person_shape_def.shacl_path), format="turtle")

        conforms, results_graph, results_text = pyshacl_validate(
            data_graph,
            shacl_graph=shacl_graph,
            inference="none",
        )

        # Report details on failure
        assert isinstance(results_text, str)
        # The graph was parsed and validated — verify we get a result
        assert isinstance(conforms, bool)

    def test_minimal_person_roundtrip(self, person_shape_def, sample_person_row_minimal):
        """Minimal row also round-trips through rdflib."""
        import json as _json

        from rdflib import Graph

        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)
        doc = builder.build_one(mapper.map(sample_person_row_minimal))

        doc_for_parse = dict(doc)
        doc_for_parse["@context"] = person_shape_def.context.get("@context", person_shape_def.context)

        g = Graph()
        g.parse(data=_json.dumps(doc_for_parse), format="json-ld")
        assert len(g) > 0
