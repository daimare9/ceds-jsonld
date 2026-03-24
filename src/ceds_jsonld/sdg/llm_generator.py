"""LLM-powered value generator for synthetic data.

Generates realistic literal values (names, dates, IDs) using a local LLM.
Supports two backends:

1. **Ollama** (auto-detected, preferred) — uses grammar-enforced JSON via
   the Ollama REST API. Detected via HTTP probe to ``localhost:11434``.
2. **Transformers** (fallback) — loads a HuggingFace model in-process using
   ``transformers`` + ``torch``. Slower but requires only ``pip install``.

The generator produces value pools (e.g. 200 first names) in a single LLM
call, then callers sample from the pool with ``random.choice()``.

Three-tier fallback:
    LLM generation → file cache → deterministic fallback generators
"""

from __future__ import annotations

import json
import re
import shutil
from typing import Any

from ceds_jsonld.logging import get_logger
from ceds_jsonld.sdg.cache import ValueCache
from ceds_jsonld.sdg.concept_resolver import PropertyMetadata
from ceds_jsonld.sdg.metadata_extractor import OntologyMetadataExtractor

_log = get_logger(__name__)

# Default model for transformers backend
DEFAULT_MODEL = "Qwen/Qwen3-4B"
# Default Ollama model tag
DEFAULT_OLLAMA_MODEL = "qwen3:4b"
# Ollama API base
_OLLAMA_BASE = "http://localhost:11434"


def _parse_json_values(text: str) -> list[str] | None:
    """Extract a list of string values from LLM JSON output.

    Handles common LLM output quirks: markdown fences, leading text, etc.

    Args:
        text: Raw LLM output text.

    Returns:
        List of string values, or ``None`` if parsing fails.
    """
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # Try to find a JSON object with a "values" key
    # The LLM might output extra text before/after
    match = re.search(r"\{[^{}]*\"values\"\s*:\s*\[.*?\]\s*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            values = data.get("values")
            if isinstance(values, list):
                return [str(v) for v in values if v is not None and str(v).strip()]
        except json.JSONDecodeError:
            pass

    # Fallback: try to parse as a bare JSON array
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            values = json.loads(match.group())
            if isinstance(values, list):
                return [str(v) for v in values if v is not None and str(v).strip()]
        except json.JSONDecodeError:
            pass

    return None


class LLMValueGenerator:
    """Generate realistic literal values using a local LLM.

    Auto-detects Ollama if running; falls back to in-process transformers.
    Values are cached to disk for reuse across sessions.

    Example:
        >>> from rdflib import Graph
        >>> gen = LLMValueGenerator(ontology_graph=graph)
        >>> values = gen.generate_values(prop_meta, count=200)
        >>> len(values)
        200

    Args:
        ontology_graph: rdflib Graph with the CEDS ontology loaded
            (for prompt metadata extraction).
        model: Model identifier. For transformers: HuggingFace repo ID
            (default ``Qwen/Qwen3-4B``). For Ollama: model tag
            (default ``qwen3:4b``).
        use_ollama: If ``True`` (default), auto-detect Ollama and
            prefer it. Set ``False`` to force transformers.
        cache: Optional ``ValueCache`` instance. If ``None``, a default
            cache is created.
        max_retries: Maximum attempts for JSON parsing from LLM output.
    """

    def __init__(
        self,
        ontology_graph: Any,
        *,
        model: str | None = None,
        use_ollama: bool = True,
        cache: ValueCache | None = None,
        max_retries: int = 3,
    ) -> None:
        self._extractor = OntologyMetadataExtractor(ontology_graph)
        self._model = model
        self._use_ollama = use_ollama
        self._cache = cache or ValueCache()
        self._max_retries = max_retries

        # Backend state (lazy-initialized)
        self._backend: str | None = None  # "ollama" or "transformers"
        self._ollama_client: Any = None
        self._hf_model: Any = None
        self._hf_tokenizer: Any = None
        self._hf_device: str = "cpu"

    @property
    def backend(self) -> str:
        """The active backend name: ``"ollama"`` or ``"transformers"``."""
        if self._backend is None:
            self._detect_backend()
        return self._backend  # type: ignore[return-value]

    @property
    def model_name(self) -> str:
        """The model identifier being used."""
        if self.backend == "ollama":
            return self._model or DEFAULT_OLLAMA_MODEL
        return self._model or DEFAULT_MODEL

    # ------------------------------------------------------------------
    # Backend detection
    # ------------------------------------------------------------------

    def _detect_backend(self) -> None:
        """Auto-detect the best available LLM backend."""
        if self._use_ollama and self._check_ollama():
            self._backend = "ollama"
            _log.info("LLM backend: Ollama (auto-detected)")
            return

        if self._check_transformers():
            self._backend = "transformers"
            _log.info("LLM backend: transformers + torch")
            return

        self._backend = "none"
        _log.warning("No LLM backend available. Install torch+transformers or run Ollama for LLM generation.")

    def _check_ollama(self) -> bool:
        """Check if Ollama is reachable on localhost."""
        # Quick check: is the binary on PATH?
        if not shutil.which("ollama"):
            return False

        try:
            import httpx  # noqa: F811

            resp = httpx.get(f"{_OLLAMA_BASE}/api/version", timeout=2.0)
            if resp.status_code == 200:
                _log.debug("Ollama detected", version=resp.json().get("version"))
                return True
        except Exception:
            pass
        return False

    def _check_transformers(self) -> bool:
        """Check if transformers + torch are importable."""
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401

            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # LLM invocation
    # ------------------------------------------------------------------

    def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API with structured JSON output."""
        import ollama as ollama_lib

        if self._ollama_client is None:
            self._ollama_client = ollama_lib.Client(host=_OLLAMA_BASE)

        model_tag = self._model or DEFAULT_OLLAMA_MODEL
        response = self._ollama_client.chat(
            model=model_tag,
            messages=[{"role": "user", "content": prompt}],
            format={
                "type": "object",
                "properties": {
                    "values": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["values"],
            },
        )
        return str(response["message"]["content"])

    def _call_transformers(self, prompt: str) -> str:
        """Call an in-process HuggingFace model."""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        model_id = self._model or DEFAULT_MODEL

        if self._hf_model is None:
            _log.info("Loading transformers model", model=model_id)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.bfloat16 if device == "cuda" else torch.float32

            self._hf_tokenizer = AutoTokenizer.from_pretrained(model_id)
            self._hf_model = AutoModelForCausalLM.from_pretrained(
                model_id,
                torch_dtype=dtype,
                device_map="auto",
            )
            self._hf_device = device
            _log.info("Model loaded", model=model_id, device=device)

        messages = [{"role": "user", "content": prompt}]

        # Apply chat template — use enable_thinking=False for speed
        # if the tokenizer supports it (Qwen3 models)
        template_kwargs: dict[str, Any] = {
            "return_tensors": "pt",
            "add_generation_prompt": True,
        }
        try:
            inputs = self._hf_tokenizer.apply_chat_template(
                messages,
                enable_thinking=False,
                **template_kwargs,
            )
        except TypeError:
            # Tokenizer doesn't support enable_thinking
            inputs = self._hf_tokenizer.apply_chat_template(
                messages,
                **template_kwargs,
            )

        inputs = inputs.to(self._hf_device)

        with torch.no_grad():
            output = self._hf_model.generate(
                inputs,
                max_new_tokens=4096,
                temperature=0.8,
                top_p=0.95,
                repetition_penalty=1.1,
                do_sample=True,
            )

        response = self._hf_tokenizer.decode(
            output[0][inputs.shape[1] :],
            skip_special_tokens=True,
        )
        return str(response)

    def _call_llm(self, prompt: str) -> str:
        """Route to the appropriate backend."""
        if self.backend == "ollama":
            return self._call_ollama(prompt)
        if self.backend == "transformers":
            return self._call_transformers(prompt)
        msg = "No LLM backend available. Install 'ceds-jsonld[sdg]' for transformers+torch, or run Ollama locally."
        raise RuntimeError(msg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Whether any LLM backend is available."""
        return self.backend != "none"

    def generate_values(
        self,
        meta: PropertyMetadata,
        *,
        count: int = 200,
        shape_name: str = "",
        use_cache: bool = True,
    ) -> list[str] | None:
        """Generate a pool of values for a literal property.

        Tries the three-tier fallback:
        1. LLM generation (if backend available)
        2. File cache (if ``use_cache=True`` and cache hit exists)
        3. Returns ``None`` (caller should use fallback generators)

        Args:
            meta: Property metadata for the literal property.
            count: Number of values to generate.
            shape_name: Shape name for cache keying.
            use_cache: Whether to check/populate the file cache.

        Returns:
            List of generated string values, or ``None`` if generation
            fails (caller should fall back to deterministic generators).
        """
        model = self.model_name

        # Tier 2: Check cache first (avoid unnecessary LLM calls)
        if use_cache:
            cached = self._cache.get(shape_name, meta.path_iri, model)
            if cached:
                _log.debug(
                    "Using cached values",
                    property=meta.name,
                    count=len(cached),
                )
                return cached

        # Tier 1: LLM generation
        if not self.available:
            return None

        prompt = self._extractor.build_prompt(meta, count=count)
        _log.info(
            "Generating values via LLM",
            property=meta.label or meta.name,
            backend=self.backend,
            model=model,
            count=count,
        )

        for attempt in range(1, self._max_retries + 1):
            try:
                raw = self._call_llm(prompt)
                values = _parse_json_values(raw)
                if values and len(values) >= count // 2:
                    # Cache the result
                    if use_cache:
                        self._cache.put(
                            shape_name,
                            meta.path_iri,
                            meta.label or meta.name,
                            model,
                            values,
                        )
                    _log.info(
                        "LLM values generated",
                        property=meta.label or meta.name,
                        count=len(values),
                        attempt=attempt,
                    )
                    return values

                _log.warning(
                    "LLM output parsing failed or too few values",
                    property=meta.name,
                    attempt=attempt,
                    parsed_count=len(values) if values else 0,
                )
            except Exception as exc:
                _log.warning(
                    "LLM call failed",
                    property=meta.name,
                    attempt=attempt,
                    error=str(exc),
                )

        _log.warning(
            "All LLM attempts exhausted, falling back",
            property=meta.name,
            retries=self._max_retries,
        )
        return None
