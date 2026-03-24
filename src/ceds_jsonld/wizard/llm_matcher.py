"""LLM-assisted matcher — Phase 3 of the matching pipeline.

Sends unresolved columns + target property descriptions to a local LLM
and parses the structured JSON response. Reuses SDG LLM infrastructure
(Ollama or transformers backend).
"""

from __future__ import annotations

import json
import re
from typing import Any

from ceds_jsonld.logging import get_logger
from ceds_jsonld.transforms import BUILTIN_TRANSFORMS
from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.concept_matcher import MatchCandidate
from ceds_jsonld.wizard.profiler import ColumnProfile

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _build_mapping_prompt(
    columns: list[ColumnProfile],
    targets: list[TargetProperty],
) -> str:
    """Build the LLM prompt for column-to-property mapping."""
    lines: list[str] = [
        "/no_think",
        "You are an expert at mapping education data to CEDS (Common Education Data Standards).",
        "",
        "## Source Columns (unmapped)",
        "",
    ]

    for col in columns:
        lines.append(f'Column: "{col.name}"')
        if col.sample_values:
            lines.append(f"  Samples: {col.sample_values[:5]}")
        lines.append(f"  Type: {col.inferred_type}")
        if col.distinct_values:
            lines.append(f"  Distinct: {col.distinct_values[:10]}")
        lines.append("")

    lines.append("## Available Target Properties")
    lines.append("")

    for target in targets:
        lines.append(f'Property: "{target.name}" (in {target.parent_shape})')
        if target.label:
            lines.append(f'  Label: "{target.label}"')
        if target.description:
            lines.append(f'  Description: "{target.description}"')
        if target.datatype:
            xsd = target.datatype.rsplit("#", 1)[-1] if "#" in target.datatype else target.datatype
            lines.append(f"  Datatype: {xsd}")
        if target.concept_values:
            lines.append(f"  Concept Values: {target.concept_values[:10]}")
        lines.append("")

    lines.append("## Available Transforms")
    for name in sorted(BUILTIN_TRANSFORMS.keys()):
        lines.append(f"- {name}")
    lines.append("")

    lines.append("## Instructions")
    lines.append("For each source column, suggest the best matching target property.")
    lines.append(
        'Return JSON: {"mappings": [{"source_column": "...", "target_property": "...", '
        '"target_shape": "...", "confidence": 0.0-1.0, "transform": "..." or null, "reason": "..."}]}'
    )
    lines.append("Only use property names and transforms from the lists above.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_llm_response(raw: str) -> list[dict[str, Any]]:
    """Parse LLM JSON response into a list of mapping dicts.

    Handles markdown code fences and extra text around JSON.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    match = re.search(r"\{[^{}]*\"mappings\"\s*:\s*\[.*\]\s*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            mappings = data.get("mappings", [])
            if isinstance(mappings, list):
                return mappings
        except json.JSONDecodeError:
            pass

    _log.warning("Failed to parse LLM mapping response")
    return []


def _validate_response(
    mappings: list[dict[str, Any]],
    valid_properties: set[str],
    valid_transforms: set[str],
) -> list[dict[str, Any]]:
    """Filter out hallucinated properties and transforms."""
    validated: list[dict[str, Any]] = []
    for m in mappings:
        prop = m.get("target_property", "")
        if prop not in valid_properties:
            _log.debug("Filtering hallucinated property: %s", prop)
            continue
        transform = m.get("transform")
        if transform and transform not in valid_transforms:
            _log.debug("Stripping hallucinated transform: %s", transform)
            m["transform"] = None
        validated.append(m)
    return validated


# ---------------------------------------------------------------------------
# LLM matcher
# ---------------------------------------------------------------------------


class LLMMatcher:
    """LLM-assisted column-to-property matcher.

    Reuses SDG LLM infrastructure. Requires ``[sdg]`` extras.

    Args:
        backend: "ollama" or "transformers", or ``None`` for auto-detect.
        model: Model name override, or ``None`` for default.
    """

    def __init__(
        self,
        backend: str | None = None,
        model: str | None = None,
    ) -> None:
        self._backend = backend
        self._model = model

    def match(
        self,
        columns: list[ColumnProfile],
        targets: list[TargetProperty],
    ) -> tuple[list[MatchCandidate], list[ColumnProfile], list[TargetProperty]]:
        """Send unresolved columns to LLM and parse the response."""
        prompt = _build_mapping_prompt(columns, targets)
        raw_response = self._call_llm(prompt)

        if not raw_response:
            return [], columns, targets

        parsed = _parse_llm_response(raw_response)
        if not parsed:
            return [], columns, targets

        valid_props = {t.name for t in targets}
        valid_transforms = set(BUILTIN_TRANSFORMS.keys())
        validated = _validate_response(parsed, valid_props, valid_transforms)

        matches: list[MatchCandidate] = []
        resolved_cols: set[str] = set()
        resolved_targets: set[str] = set()
        col_names = {c.name for c in columns}

        for m in validated:
            src = m.get("source_column", "")
            if src not in col_names or src in resolved_cols:
                continue
            tgt = m.get("target_property", "")
            if tgt in resolved_targets:
                continue

            matches.append(
                MatchCandidate(
                    source_column=src,
                    target_property=tgt,
                    target_shape=m.get("target_shape", ""),
                    confidence=float(m.get("confidence", 0.8)),
                    reasons=[m.get("reason", "LLM suggestion")],
                    strategy="llm",
                    suggested_transform=m.get("transform"),
                ),
            )
            resolved_cols.add(src)
            resolved_targets.add(tgt)

        remaining_cols = [c for c in columns if c.name not in resolved_cols]
        remaining_targets = [t for t in targets if t.name not in resolved_targets]
        return matches, remaining_cols, remaining_targets

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM backend. Tries Ollama first, falls back to transformers."""
        if self._backend in (None, "ollama"):
            result = self._try_ollama(prompt)
            if result:
                return result
            if self._backend == "ollama":
                _log.warning("Ollama specified but not available")
                return ""

        if self._backend in (None, "transformers"):
            return self._try_transformers(prompt)

        return ""

    def _try_ollama(self, prompt: str) -> str:
        """Try Ollama REST API."""
        try:
            import httpx

            from ceds_jsonld.sdg.llm_generator import _OLLAMA_BASE, DEFAULT_OLLAMA_MODEL

            model = self._model or DEFAULT_OLLAMA_MODEL
            resp = httpx.post(
                f"{_OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=120.0,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "")
        except Exception:
            _log.debug("Ollama not available", exc_info=True)
        return ""

    def _try_transformers(self, prompt: str) -> str:
        """Try transformers + torch in-process."""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            from ceds_jsonld.sdg.llm_generator import DEFAULT_MODEL

            model_name = self._model or DEFAULT_MODEL
            _log.info("Loading model %s for mapping wizard...", model_name)

            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype="auto",
                device_map="auto",
            )

            messages = [{"role": "user", "content": prompt}]
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            inputs = tokenizer([text], return_tensors="pt").to(model.device)

            outputs = model.generate(**inputs, max_new_tokens=2048, do_sample=False)
            generated = outputs[0][inputs["input_ids"].shape[-1] :]
            return tokenizer.decode(generated, skip_special_tokens=True)

        except ImportError:
            _log.warning("transformers not available — install ceds-jsonld[sdg]")
        except Exception:
            _log.warning("Transformers generation failed", exc_info=True)
        return ""
