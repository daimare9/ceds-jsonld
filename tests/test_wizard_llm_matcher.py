"""Tests for LLMMatcher — LLM-assisted column matching.

These test the prompt builder, response parser, and response validator.
Actual LLM calls require torch/transformers or a running Ollama instance
so are mocked here (true external service boundary).
"""

from __future__ import annotations

import json

import pytest

from ceds_jsonld.wizard.llm_matcher import (
    LLMMatcher,
    _build_mapping_prompt,
    _parse_llm_response,
    _validate_response,
)
from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.profiler import ColumnProfile


def _col(
    name: str, samples: list[str] | None = None, inferred_type: str = "string",
) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        normalized=name.lower(),
        sample_values=samples or ["val1", "val2"],
        inferred_type=inferred_type,
        distinct_values=samples[:5] if samples else [],
    )


def _target(
    name: str, parent: str, label: str = "", description: str = "",
) -> TargetProperty:
    return TargetProperty(
        name=name,
        path=f"ceds:{name}",
        parent_shape=parent,
        label=label,
        description=description,
    )


class TestBuildMappingPrompt:
    def test_prompt_contains_columns(self) -> None:
        cols = [_col("FIRST_NM", ["Jane", "John"])]
        targets = [_target("FirstName", "PersonName", label="First Name")]
        prompt = _build_mapping_prompt(cols, targets)
        assert "FIRST_NM" in prompt
        assert "Jane" in prompt

    def test_prompt_contains_targets(self) -> None:
        cols = [_col("DOB")]
        targets = [_target("Birthdate", "PersonBirth", label="Birthdate")]
        prompt = _build_mapping_prompt(cols, targets)
        assert "Birthdate" in prompt
        assert "PersonBirth" in prompt

    def test_prompt_lists_transforms(self) -> None:
        cols = [_col("X")]
        targets = [_target("Y", "Z")]
        prompt = _build_mapping_prompt(cols, targets)
        assert "sex_prefix" in prompt
        assert "date_format" in prompt


class TestParseLLMResponse:
    def test_parse_valid_json(self) -> None:
        raw = json.dumps({
            "mappings": [
                {
                    "source_column": "FIRST_NM",
                    "target_property": "FirstName",
                    "target_shape": "PersonName",
                    "confidence": 0.95,
                    "transform": None,
                    "reason": "name match",
                },
            ],
        })
        result = _parse_llm_response(raw)
        assert len(result) == 1
        assert result[0]["source_column"] == "FIRST_NM"

    def test_parse_json_with_fences(self) -> None:
        inner = json.dumps({
            "mappings": [
                {
                    "source_column": "X",
                    "target_property": "Y",
                    "confidence": 0.8,
                    "reason": "test",
                },
            ],
        })
        raw = f"```json\n{inner}\n```"
        result = _parse_llm_response(raw)
        assert len(result) == 1

    def test_parse_invalid_returns_empty(self) -> None:
        result = _parse_llm_response("not json at all")
        assert result == []


class TestValidateResponse:
    def test_valid_mapping_passes(self) -> None:
        mappings = [
            {
                "source_column": "X",
                "target_property": "FirstName",
                "target_shape": "PersonName",
                "confidence": 0.9,
                "transform": "int_clean",
                "reason": "test",
            },
        ]
        valid_properties = {"FirstName"}
        valid_transforms = {"int_clean", "date_format"}
        result = _validate_response(mappings, valid_properties, valid_transforms)
        assert len(result) == 1

    def test_hallucinated_property_filtered(self) -> None:
        mappings = [
            {
                "source_column": "X",
                "target_property": "FakeProperty",
                "confidence": 0.9,
                "reason": "test",
            },
        ]
        valid_properties = {"FirstName"}
        result = _validate_response(mappings, valid_properties, set())
        assert len(result) == 0

    def test_hallucinated_transform_stripped(self) -> None:
        mappings = [
            {
                "source_column": "X",
                "target_property": "FirstName",
                "confidence": 0.9,
                "transform": "fake_transform",
                "reason": "test",
            },
        ]
        valid_properties = {"FirstName"}
        valid_transforms = {"int_clean"}
        result = _validate_response(mappings, valid_properties, valid_transforms)
        assert len(result) == 1
        assert result[0]["transform"] is None
