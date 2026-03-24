"""Integration tests for MappingWizard — end-to-end CSV→YAML."""

from __future__ import annotations

import csv

import pytest
import yaml

from ceds_jsonld.wizard import MappingWizard


class TestMappingWizardHeuristicOnly:
    """End-to-end tests using heuristic-only mode (no LLM)."""

    @pytest.fixture()
    def sample_csv(self, tmp_path):
        path = tmp_path / "students.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["FirstName", "LastName", "DOB", "Gender"])
            w.writeheader()
            w.writerow({"FirstName": "Jane", "LastName": "Doe", "DOB": "1990-01-15", "Gender": "Female"})
            w.writerow({"FirstName": "John", "LastName": "Smith", "DOB": "1985-03-22", "Gender": "Male"})
        return str(path)

    def test_suggest_returns_result(self, sample_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(sample_csv, shape="person")
        assert result is not None
        assert result.mapping_config is not None
        assert isinstance(result.yaml_text, str)
        assert len(result.yaml_text) > 0

    def test_suggest_maps_known_columns(self, sample_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(sample_csv, shape="person")

        # Should map at least FirstName
        mapped_sources = {m.source_column for m in result.confidence_report}
        assert "FirstName" in mapped_sources

    def test_suggest_yaml_is_valid(self, sample_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(sample_csv, shape="person")

        # YAML should be parseable
        parsed = yaml.safe_load(result.yaml_text)
        assert parsed is not None
        assert "shape" in parsed

    def test_suggest_with_output_file(self, sample_csv, tmp_path) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(sample_csv, shape="person")
        out = tmp_path / "mapping.yaml"
        result.save(str(out))
        assert out.exists()
        content = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert content["shape"] is not None


class TestMappingWizardAutoDetect:
    """Test shape auto-detection."""

    @pytest.fixture()
    def person_csv(self, tmp_path):
        path = tmp_path / "people.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["FirstName", "LastName", "Birthdate"])
            w.writeheader()
            w.writerow({"FirstName": "Jane", "LastName": "Doe", "Birthdate": "1990-01-15"})
        return str(path)

    def test_detect_shape_returns_person(self, person_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        detected = wizard.detect_shape(person_csv)
        assert len(detected) > 0
        # Person should be the top match
        assert detected[0][0] == "person"


def test_import_from_top_level() -> None:
    from ceds_jsonld import MappingWizard as Wiz

    assert Wiz is not None


class TestPreview:
    @pytest.fixture()
    def person_csv(self, tmp_path):
        path = tmp_path / "people.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["FirstName", "LastName", "Birthdate"])
            w.writeheader()
            w.writerow({"FirstName": "Jane", "LastName": "Doe", "Birthdate": "1990-01-15"})
            w.writerow({"FirstName": "John", "LastName": "Smith", "Birthdate": "1985-03-22"})
        return str(path)

    def test_preview_returns_docs(self, person_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(person_csv, shape="person")
        docs = wizard.preview(person_csv, result, count=2)
        assert isinstance(docs, list)


class TestEndToEndJourney:
    """Prove wizard-generated YAML is usable with the pipeline."""

    @pytest.fixture()
    def person_csv(self, tmp_path):
        path = tmp_path / "people.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["FirstName", "LastName", "Birthdate"])
            w.writeheader()
            w.writerow({"FirstName": "Jane", "LastName": "Doe", "Birthdate": "1990-01-15"})
            w.writerow({"FirstName": "John", "LastName": "Smith", "Birthdate": "1985-03-22"})
        return str(path)

    def test_wizard_yaml_through_pipeline(self, person_csv, tmp_path) -> None:
        """CSV -> Wizard (no LLM) -> YAML -> Pipeline -> JSON-LD."""
        import yaml

        from ceds_jsonld.mapping import FieldMapper

        # 1. Run wizard
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(person_csv, shape="person")

        # 2. Verify YAML is valid
        config = yaml.safe_load(result.yaml_text)
        assert config is not None
        assert config["shape"] is not None

        # 3. At least some columns should be mapped
        assert len(result.confidence_report) > 0

        # 4. Save and reload through FieldMapper
        yaml_path = tmp_path / "wizard_mapping.yaml"
        result.save(str(yaml_path))
        with open(yaml_path) as f:
            loaded_config = yaml.safe_load(f)
        mapper = FieldMapper(loaded_config)
        assert mapper is not None
