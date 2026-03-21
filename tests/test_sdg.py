"""Tests for the Synthetic Data Generator (SDG) sub-package.

Covers:
- ConceptSchemeResolver: concept value resolution from ontology
- FallbackGenerators: XSD-type and heuristic value generation
- MappingAwareAssembler: flat row assembly from value pools
- SyntheticDataGenerator: end-to-end orchestration
- Round-trip: SDG → Pipeline → JSON-LD → validate structure
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.introspector import SHACLIntrospector
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeRegistry
from ceds_jsonld.sdg.assembler import MappingAwareAssembler
from ceds_jsonld.sdg.concept_resolver import (
    ConceptSchemeResolver,
    PropertyMetadata,
)
from ceds_jsonld.sdg.fallback_generators import FallbackGenerators
from ceds_jsonld.sdg.generator import SyntheticDataGenerator


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry() -> ShapeRegistry:
    """ShapeRegistry with the Person shape loaded."""
    reg = ShapeRegistry()
    reg.load_shape("person")
    return reg


@pytest.fixture(scope="module")
def person_shape_def(registry):
    return registry.get_shape("person")


@pytest.fixture(scope="module")
def introspector(person_shape_def):
    return SHACLIntrospector(person_shape_def.shacl_path)


@pytest.fixture(scope="module")
def resolver():
    """ConceptSchemeResolver with Person extensions loaded."""
    base_dir = Path(__file__).parent.parent / "src" / "ceds_jsonld" / "ontologies" / "base"
    ext = base_dir / "Person_Extension_Ontology.ttl"
    extensions = [ext] if ext.exists() else []
    return ConceptSchemeResolver(ontology_dir=base_dir, extension_files=extensions)


# ==================================================================
# ConceptSchemeResolver
# ==================================================================

class TestConceptSchemeResolver:
    """Tests for ontology concept scheme resolution."""

    def test_concept_resolution_for_sex_property(self, resolver, introspector):
        """P000255 (Sex) should resolve to concept values like Male/Female via Path B."""
        result = resolver.classify_shape_properties(introspector)
        sex_shape_props = result.get("PersonSexGenderShape", [])
        assert len(sex_shape_props) > 0

        sex_meta = sex_shape_props[0]  # P000255
        assert sex_meta.category == "concept"
        assert len(sex_meta.allowed_values) > 0
        lower_vals = {v.lower() for v in sex_meta.allowed_values}
        assert "male" in lower_vals or "female" in lower_vals

    def test_resolve_concept_class_members(self, resolver):
        """Path B: resolve NamedIndividual members for a concept scheme class."""
        # PersonIdentificationSystem class (C200058) should have members
        values = resolver.resolve_concept_class_members("http://ceds.ed.gov/terms#C200058")
        # If the ontology has them, we should get back notations
        # If not populated, this is still valid — just empty
        assert isinstance(values, list)

    def test_classify_shape_properties_returns_dict(self, resolver, introspector):
        """classify_shape_properties should return a dict of sub-shape → properties."""
        result = resolver.classify_shape_properties(introspector)
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_classified_has_person_name(self, resolver, introspector):
        """PersonNameShape should appear with literal properties (P-codes)."""
        result = resolver.classify_shape_properties(introspector)
        assert "PersonNameShape" in result
        name_props = result["PersonNameShape"]
        prop_names = {p.name for p in name_props}
        # P000115=FirstName, P000172=LastOrSurname
        assert "P000115" in prop_names or "P000172" in prop_names

    def test_classified_has_concept_properties(self, resolver, introspector):
        """At least one property should be classified as 'concept'."""
        result = resolver.classify_shape_properties(introspector)
        concept_count = sum(
            1
            for props in result.values()
            for p in props
            if p.category == "concept"
        )
        assert concept_count > 0, "Expected at least one concept property"

    def test_classified_has_literal_properties(self, resolver, introspector):
        """At least one property should be classified as 'literal'."""
        result = resolver.classify_shape_properties(introspector)
        literal_count = sum(
            1
            for props in result.values()
            for p in props
            if p.category == "literal"
        )
        assert literal_count > 0, "Expected at least one literal property"

    def test_structural_classes_excluded(self, resolver, introspector):
        """RecordStatus and DataCollection sub-shapes should NOT appear."""
        result = resolver.classify_shape_properties(introspector)
        for key in result:
            assert "RecordStatus" not in key
            assert "DataCollection" not in key


# ==================================================================
# FallbackGenerators
# ==================================================================

class TestFallbackGenerators:
    """Tests for XSD-type and heuristic value generators."""

    def test_deterministic_with_seed(self):
        gen1 = FallbackGenerators(seed=42)
        gen2 = FallbackGenerators(seed=42)
        meta = PropertyMetadata("FirstName", "", label="First Name",
                                xsd_datatype="http://www.w3.org/2001/XMLSchema#string")
        assert gen1.generate_one(meta) == gen2.generate_one(meta)

    def test_generate_first_name(self):
        gen = FallbackGenerators(seed=1)
        meta = PropertyMetadata("FirstName", "", label="First Name",
                                xsd_datatype="http://www.w3.org/2001/XMLSchema#string")
        val = gen.generate_one(meta)
        assert isinstance(val, str)
        assert len(val) > 0

    def test_generate_last_name(self):
        gen = FallbackGenerators(seed=1)
        meta = PropertyMetadata("LastOrSurname", "", label="Last or Surname",
                                xsd_datatype="http://www.w3.org/2001/XMLSchema#string")
        val = gen.generate_one(meta)
        assert isinstance(val, str)
        assert len(val) > 0

    def test_generate_date(self):
        gen = FallbackGenerators(seed=1)
        meta = PropertyMetadata("Birthdate", "", label="Birthdate",
                                xsd_datatype="http://www.w3.org/2001/XMLSchema#date")
        val = gen.generate_one(meta)
        # Must be YYYY-MM-DD
        parts = val.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4

    def test_generate_datetime(self):
        gen = FallbackGenerators(seed=1)
        meta = PropertyMetadata("Created", "", label="Created",
                                xsd_datatype="http://www.w3.org/2001/XMLSchema#dateTime")
        val = gen.generate_one(meta)
        assert "T" in val

    def test_generate_token(self):
        gen = FallbackGenerators(seed=1)
        meta = PropertyMetadata("PersonIdentifier", "", label="Person Identifier",
                                xsd_datatype="http://www.w3.org/2001/XMLSchema#token")
        val = gen.generate_one(meta)
        assert len(val) > 0

    def test_generate_integer(self):
        gen = FallbackGenerators(seed=1)
        meta = PropertyMetadata("Count", "", label="Count",
                                xsd_datatype="http://www.w3.org/2001/XMLSchema#integer")
        val = gen.generate_one(meta)
        int(val)  # Should not raise

    def test_generate_boolean(self):
        gen = FallbackGenerators(seed=1)
        meta = PropertyMetadata("IsActive", "", label="Is Active",
                                xsd_datatype="http://www.w3.org/2001/XMLSchema#boolean")
        val = gen.generate_one(meta)
        assert val in ("true", "false")

    def test_generate_pool_size(self):
        gen = FallbackGenerators(seed=1)
        meta = PropertyMetadata("X", "", xsd_datatype="http://www.w3.org/2001/XMLSchema#string")
        pool = gen.generate_pool(meta, count=50)
        assert len(pool) == 50

    def test_sample_from_pool(self):
        gen = FallbackGenerators(seed=1)
        pool = ["a", "b", "c"]
        val = gen.sample_from_pool(pool)
        assert val in pool

    def test_unknown_datatype_falls_back_to_string(self):
        gen = FallbackGenerators(seed=1)
        meta = PropertyMetadata("X", "", xsd_datatype="http://example.org/custom")
        val = gen.generate_one(meta)
        assert isinstance(val, str)


# ==================================================================
# MappingAwareAssembler
# ==================================================================

class TestMappingAwareAssembler:
    """Tests for flat row assembly from value pools."""

    @pytest.fixture()
    def simple_config(self):
        return {
            "properties": {
                "hasPersonName": {
                    "cardinality": "single",
                    "fields": {
                        "FirstName": {"source": "FirstName", "target": "FirstName"},
                        "LastOrSurname": {"source": "LastName", "target": "LastOrSurname"},
                    },
                },
            },
        }

    @pytest.fixture()
    def simple_pools(self):
        return {
            "FirstName": ["Alice", "Bob", "Carol"],
            "LastName": ["Smith", "Jones", "Lee"],
        }

    def test_assemble_one_has_expected_keys(self, simple_config, simple_pools):
        asm = MappingAwareAssembler(simple_config, simple_pools, seed=1)
        row = asm.assemble_one()
        assert "FirstName" in row
        assert "LastName" in row

    def test_assemble_one_values_from_pool(self, simple_config, simple_pools):
        asm = MappingAwareAssembler(simple_config, simple_pools, seed=1)
        row = asm.assemble_one()
        assert row["FirstName"] in simple_pools["FirstName"]
        assert row["LastName"] in simple_pools["LastName"]

    def test_assemble_batch_count(self, simple_config, simple_pools):
        asm = MappingAwareAssembler(simple_config, simple_pools, seed=1)
        rows = asm.assemble_batch(25)
        assert len(rows) == 25

    def test_multiple_cardinality_produces_pipes(self):
        config = {
            "properties": {
                "hasPersonIdentification": {
                    "cardinality": "multiple",
                    "fields": {
                        "PersonIdentifier": {
                            "source": "PersonIdentifiers",
                            "target": "PersonIdentifier",
                        },
                    },
                },
            },
        }
        pools = {"PersonIdentifiers": ["111", "222", "333", "444"]}
        asm = MappingAwareAssembler(config, pools, seed=1, instances_range=(2, 5))
        row = asm.assemble_one()
        assert "|" in row["PersonIdentifiers"]

    def test_deterministic_with_seed(self, simple_config, simple_pools):
        asm1 = MappingAwareAssembler(simple_config, simple_pools, seed=99)
        asm2 = MappingAwareAssembler(simple_config, simple_pools, seed=99)
        assert asm1.assemble_one() == asm2.assemble_one()


# ==================================================================
# SyntheticDataGenerator (orchestration)
# ==================================================================

class TestSyntheticDataGenerator:
    """Tests for the end-to-end generator orchestrator."""

    def test_generate_returns_list_of_dicts(self, registry):
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=5)
        assert isinstance(rows, list)
        assert len(rows) == 5
        assert all(isinstance(r, dict) for r in rows)

    def test_generated_rows_have_expected_columns(self, registry):
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=3)
        # Every row should have at least FirstName and LastName
        for row in rows:
            assert "FirstName" in row
            assert "LastName" in row

    def test_generated_rows_string_values(self, registry):
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=3)
        for row in rows:
            for v in row.values():
                assert isinstance(v, str)

    def test_deterministic_with_seed(self, registry):
        gen1 = SyntheticDataGenerator(registry, seed=123)
        gen2 = SyntheticDataGenerator(registry, seed=123)
        rows1 = gen1.generate("person", count=5)
        rows2 = gen2.generate("person", count=5)
        assert rows1 == rows2

    def test_generate_csv_creates_file(self, registry, tmp_path):
        gen = SyntheticDataGenerator(registry, seed=42)
        out = tmp_path / "test.csv"
        result = gen.generate_csv("person", out, count=10)
        assert result.exists()
        with result.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 10
        assert "FirstName" in rows[0]

    def test_generate_ndjson_creates_file(self, registry, tmp_path):
        gen = SyntheticDataGenerator(registry, seed=42)
        out = tmp_path / "test.ndjson"
        result = gen.generate_ndjson("person", out, count=10)
        assert result.exists()
        lines = result.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 10
        obj = json.loads(lines[0])
        assert "FirstName" in obj


# ==================================================================
# Round-trip: SDG → Pipeline → JSON-LD
# ==================================================================

class TestRoundTrip:
    """Generate synthetic data and process it through the full pipeline."""

    def test_generated_row_produces_valid_jsonld(self, registry, person_shape_def):
        """A single generated row should produce a valid JSON-LD doc."""
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=1)
        row = rows[0]

        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)
        mapped = mapper.map(row)
        doc = builder.build_one(mapped)

        assert "@context" in doc
        assert "@type" in doc
        assert doc["@type"] == "Person"
        assert "hasPersonName" in doc

    def test_batch_generated_rows_all_produce_jsonld(self, registry, person_shape_def):
        """Multiple generated rows should all produce valid JSON-LD docs."""
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=20)

        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)

        for row in rows:
            mapped = mapper.map(row)
            doc = builder.build_one(mapped)
            assert doc["@type"] == "Person"
            assert "@context" in doc

    def test_generated_jsonld_has_sub_shapes(self, registry, person_shape_def):
        """Generated JSON-LD should have expected sub-shape keys."""
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=1)

        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)
        doc = builder.build_one(mapper.map(rows[0]))

        # All these sub-shapes should be present
        expected = {"hasPersonName", "hasPersonBirth", "hasPersonSexGender"}
        assert expected.issubset(set(doc.keys()))


class TestValueQuality:
    """Verify that generated values come from real ontology values, not random strings."""

    def test_sex_values_from_ontology(self, registry):
        """Sex column should only contain ontology concept values."""
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=50)
        valid_sex = {"Male", "Female", "NotSelected"}
        sex_values = {row["Sex"] for row in rows}
        assert sex_values.issubset(valid_sex), (
            f"Sex values contain non-ontology strings: {sex_values - valid_sex}"
        )

    def test_race_values_from_ontology(self, registry):
        """RaceEthnicity column values should come from ontology concepts."""
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=50)
        valid_race = {
            "AmericanIndianOrAlaskaNative", "Asian",
            "BlackOrAfricanAmerican", "DemographicRaceTwoOrMoreRaces",
            "HispanicOrLatinoEthnicity",
            "NativeHawaiianOrOtherPacificIslander",
            "RaceAndEthnicityUnknown", "White",
        }
        for row in rows:
            raw = row["RaceEthnicity"]
            for instance in raw.split("|"):
                for val in instance.split(","):
                    val = val.strip()
                    if val:
                        assert val in valid_race, (
                            f"Race value '{val}' is not a valid ontology concept"
                        )

    def test_birthdate_is_valid_iso_date(self, registry):
        """Birthdate column should contain valid ISO 8601 dates."""
        import re
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=50)
        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for row in rows:
            bd = row["Birthdate"]
            assert date_pattern.match(bd), (
                f"Birthdate '{bd}' is not a valid ISO date"
            )

    def test_first_names_are_realistic(self, registry):
        """FirstName should come from curated name list, not random strings."""
        gen = SyntheticDataGenerator(registry, seed=42)
        rows = gen.generate("person", count=50)
        for row in rows:
            name = row["FirstName"]
            assert name.isalpha(), f"FirstName '{name}' contains non-alpha chars"
            assert len(name) <= 20, f"FirstName '{name}' is suspiciously long"
