"""Tests for MappingAssembler — YAML config assembly from matches."""

from __future__ import annotations

import yaml
import pytest

from ceds_jsonld.wizard.assembler import MappingAssembler, WizardResult
from ceds_jsonld.wizard.concept_matcher import MatchCandidate


class TestWizardResult:
    def test_wizard_result_fields(self) -> None:
        r = WizardResult(
            mapping_config={"shape": "PersonShape"},
            confidence_report=[],
            unmapped_columns=[],
            unmapped_properties=["GenerationCodeOrSuffix"],
            yaml_text="shape: PersonShape\n",
        )
        assert r.mapping_config["shape"] == "PersonShape"
        assert "GenerationCodeOrSuffix" in r.unmapped_properties

    def test_save(self, tmp_path) -> None:
        r = WizardResult(
            mapping_config={"shape": "PersonShape"},
            confidence_report=[],
            unmapped_columns=[],
            unmapped_properties=[],
            yaml_text="shape: PersonShape\n",
        )
        out = tmp_path / "test.yaml"
        r.save(str(out))
        assert out.read_text(encoding="utf-8") == "shape: PersonShape\n"


class TestMappingAssembler:
    def test_assemble_basic(self) -> None:
        matches = [
            MatchCandidate(
                source_column="FIRST_NM",
                target_property="FirstName",
                target_shape="PersonName",
                confidence=0.95,
                reasons=["exact_name_match"],
                strategy="heuristic",
            ),
        ]
        assembler = MappingAssembler(
            shape_name="PersonShape",
            context_url="https://example.com/context.json",
            base_uri="cepi:person/",
        )
        result = assembler.assemble(
            matches=matches,
            unmapped_columns=[],
            unmapped_properties=["Birthdate"],
        )

        assert isinstance(result, WizardResult)
        assert result.mapping_config["shape"] == "PersonShape"
        assert "Birthdate" in result.unmapped_properties

    def test_yaml_text_parseable(self) -> None:
        matches = [
            MatchCandidate(
                source_column="FIRST_NM",
                target_property="FirstName",
                target_shape="PersonName",
                confidence=0.95,
                reasons=["heuristic"],
                strategy="heuristic",
            ),
            MatchCandidate(
                source_column="DOB",
                target_property="Birthdate",
                target_shape="PersonBirth",
                confidence=0.98,
                reasons=["heuristic"],
                strategy="heuristic",
                suggested_transform="date_format",
            ),
        ]
        assembler = MappingAssembler(
            shape_name="PersonShape",
            context_url="",
            base_uri="",
        )
        result = assembler.assemble(
            matches=matches, unmapped_columns=[], unmapped_properties=[],
        )

        parsed = yaml.safe_load(result.yaml_text)
        assert parsed is not None
        assert parsed["shape"] == "PersonShape"

    def test_transform_included(self) -> None:
        matches = [
            MatchCandidate(
                source_column="GENDER",
                target_property="hasSex",
                target_shape="PersonSexGender",
                confidence=0.95,
                strategy="concept",
                suggested_transform="sex_prefix",
            ),
        ]
        assembler = MappingAssembler(
            shape_name="PersonShape", context_url="", base_uri="",
        )
        result = assembler.assemble(
            matches=matches, unmapped_columns=[], unmapped_properties=[],
        )

        config = result.mapping_config
        found = False
        for prop_data in config.get("properties", {}).values():
            if isinstance(prop_data, dict):
                for field_data in prop_data.get("fields", {}).values():
                    if isinstance(field_data, dict) and field_data.get("source") == "GENDER":
                        assert field_data.get("transform") == "sex_prefix"
                        found = True
        assert found
