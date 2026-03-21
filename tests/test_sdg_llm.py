"""Tests for SDG LLM-powered generation modules.

Covers:
- ValueCache: file-based caching of LLM-generated values
- OntologyMetadataExtractor: ontology metadata extraction for prompts
- LLMValueGenerator: backend detection, prompt building, JSON parsing
- Three-tier fallback integration in SyntheticDataGenerator
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ceds_jsonld.introspector import SHACLIntrospector
from ceds_jsonld.registry import ShapeRegistry
from ceds_jsonld.sdg.cache import ValueCache, _safe_filename
from ceds_jsonld.sdg.concept_resolver import (
    ConceptSchemeResolver,
    PropertyMetadata,
)
from ceds_jsonld.sdg.generator import SyntheticDataGenerator
from ceds_jsonld.sdg.llm_generator import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_MODEL,
    LLMValueGenerator,
    _parse_json_values,
)
from ceds_jsonld.sdg.metadata_extractor import OntologyMetadataExtractor


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry() -> ShapeRegistry:
    reg = ShapeRegistry()
    reg.load_shape("person")
    return reg


@pytest.fixture(scope="module")
def resolver() -> ConceptSchemeResolver:
    base_dir = Path(__file__).parent.parent / "src" / "ceds_jsonld" / "ontologies" / "base"
    ext = base_dir / "Person_Extension_Ontology.ttl"
    extensions = [ext] if ext.exists() else []
    return ConceptSchemeResolver(ontology_dir=base_dir, extension_files=extensions)


@pytest.fixture(scope="module")
def ontology_graph(resolver):
    return resolver._graph


@pytest.fixture(scope="module")
def classified_properties(resolver, registry) -> dict[str, list[PropertyMetadata]]:
    shape_def = registry.get_shape("person")
    introspector = SHACLIntrospector(shape_def.shacl_path)
    return resolver.classify_shape_properties(introspector)


@pytest.fixture(scope="module")
def literal_meta(classified_properties) -> PropertyMetadata:
    """Find a literal property to test with (e.g. First Name)."""
    for props in classified_properties.values():
        for meta in props:
            if meta.category == "literal" and meta.label:
                return meta
    pytest.skip("No literal property found in classified properties")


@pytest.fixture()
def cache(tmp_path) -> ValueCache:
    return ValueCache(cache_dir=tmp_path / "cache")


# ==================================================================
# _safe_filename helper
# ==================================================================

class TestSafeFilename:

    def test_iri_with_fragment(self):
        assert _safe_filename("http://ceds.ed.gov/terms#P000115") == "P000115"

    def test_iri_with_path(self):
        assert _safe_filename("http://example.com/foo/bar") == "bar"

    def test_plain_name(self):
        assert _safe_filename("FirstName") == "FirstName"

    def test_special_chars_replaced(self):
        result = _safe_filename("a b:c/d#e")
        assert all(c.isalnum() or c in ("_", "-") for c in result)


# ==================================================================
# ValueCache
# ==================================================================

class TestValueCache:

    def test_miss_returns_none(self, cache):
        assert cache.get("person", "http://example.com/P1", "test-model") is None

    def test_put_and_get(self, cache):
        values = ["Maria", "James", "Sophia"]
        path = cache.put(
            "person",
            "http://ceds.ed.gov/terms#P000115",
            "First Name",
            "test-model",
            values,
        )
        assert path.exists()

        result = cache.get("person", "http://ceds.ed.gov/terms#P000115", "test-model")
        assert result == values

    def test_has_returns_true_after_put(self, cache):
        cache.put("person", "http://example.com/P2", "Test", "m1", ["a", "b"])
        assert cache.has("person", "http://example.com/P2", "m1")

    def test_has_returns_false_on_miss(self, cache):
        assert not cache.has("person", "http://example.com/nonexist", "m1")

    def test_different_models_different_cache(self, cache):
        cache.put("person", "http://example.com/P3", "Prop", "modelA", ["x"])
        cache.put("person", "http://example.com/P3", "Prop", "modelB", ["y"])

        assert cache.get("person", "http://example.com/P3", "modelA") == ["x"]
        assert cache.get("person", "http://example.com/P3", "modelB") == ["y"]

    def test_cache_file_format(self, cache):
        cache.put("person", "http://example.com/P4", "Label", "m1", ["val1"])
        path = cache._cache_path("person", "http://example.com/P4", "m1")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["property_iri"] == "http://example.com/P4"
        assert data["property_label"] == "Label"
        assert data["model"] == "m1"
        assert data["count"] == 1
        assert "generated_at" in data
        assert data["values"] == ["val1"]

    def test_clear_shape(self, cache):
        cache.put("person", "http://example.com/P5", "X", "m1", ["a"])
        cache.put("org", "http://example.com/P6", "Y", "m1", ["b"])

        removed = cache.clear("person")
        assert removed >= 1
        assert cache.get("person", "http://example.com/P5", "m1") is None
        # Other shapes unaffected
        assert cache.get("org", "http://example.com/P6", "m1") == ["b"]

    def test_clear_all(self, cache):
        cache.put("person", "http://example.com/P7", "X", "m1", ["a"])
        cache.put("org", "http://example.com/P8", "Y", "m1", ["b"])

        removed = cache.clear()
        assert removed >= 2

    def test_corrupt_cache_returns_none(self, cache):
        cache.put("person", "http://example.com/Pcorrupt", "X", "m1", ["a"])
        path = cache._cache_path("person", "http://example.com/Pcorrupt", "m1")
        path.write_text("not json at all", encoding="utf-8")

        assert cache.get("person", "http://example.com/Pcorrupt", "m1") is None


# ==================================================================
# _parse_json_values
# ==================================================================

class TestParseJsonValues:

    def test_plain_json_object(self):
        text = '{"values": ["Alice", "Bob", "Charlie"]}'
        assert _parse_json_values(text) == ["Alice", "Bob", "Charlie"]

    def test_markdown_fenced(self):
        text = '```json\n{"values": ["one", "two"]}\n```'
        assert _parse_json_values(text) == ["one", "two"]

    def test_bare_array(self):
        text = '["x", "y", "z"]'
        assert _parse_json_values(text) == ["x", "y", "z"]

    def test_extra_text_around(self):
        text = 'Here are the values:\n{"values": ["val1"]}\nDone!'
        assert _parse_json_values(text) == ["val1"]

    def test_none_on_garbage(self):
        assert _parse_json_values("This is not JSON at all") is None

    def test_empty_string(self):
        assert _parse_json_values("") is None

    def test_filters_none_and_blank(self):
        text = '{"values": ["good", null, "", "  ", "also_good"]}'
        result = _parse_json_values(text)
        assert "good" in result
        assert "also_good" in result
        # None and blank strings should be filtered
        assert "" not in result

    def test_numeric_values_converted_to_str(self):
        text = '{"values": [1, 2, 3]}'
        result = _parse_json_values(text)
        assert result == ["1", "2", "3"]


# ==================================================================
# OntologyMetadataExtractor
# ==================================================================

class TestOntologyMetadataExtractor:

    def test_extract_prompt_metadata_returns_dict(self, ontology_graph, literal_meta):
        extractor = OntologyMetadataExtractor(ontology_graph)
        info = extractor.extract_prompt_metadata(literal_meta)
        assert isinstance(info, dict)
        assert "property_label" in info
        assert "data_type" in info
        assert "parent_class" in info
        assert "path_iri" in info

    def test_property_label_populated(self, ontology_graph, literal_meta):
        extractor = OntologyMetadataExtractor(ontology_graph)
        info = extractor.extract_prompt_metadata(literal_meta)
        # Should have a non-empty label
        assert info["property_label"]

    def test_build_prompt_returns_string(self, ontology_graph, literal_meta):
        extractor = OntologyMetadataExtractor(ontology_graph)
        prompt = extractor.build_prompt(literal_meta, count=10)
        assert isinstance(prompt, str)
        assert "10" in prompt  # count should appear
        assert "synthetic data" in prompt.lower() or "generate" in prompt.lower()

    def test_build_prompt_contains_property_info(self, ontology_graph, literal_meta):
        extractor = OntologyMetadataExtractor(ontology_graph)
        prompt = extractor.build_prompt(literal_meta, count=50)
        # Should contain property label somewhere
        info = extractor.extract_prompt_metadata(literal_meta)
        assert info["property_label"] in prompt

    def test_get_skos_notation(self, ontology_graph, literal_meta):
        extractor = OntologyMetadataExtractor(ontology_graph)
        # May or may not have notation, but should not raise
        notation = extractor.get_skos_notation(literal_meta.path_iri)
        assert isinstance(notation, str)

    def test_get_parent_class_label(self, ontology_graph, literal_meta):
        extractor = OntologyMetadataExtractor(ontology_graph)
        label = extractor.get_parent_class_label(literal_meta.path_iri)
        assert isinstance(label, str)


# ==================================================================
# LLMValueGenerator — backend detection
# ==================================================================

class TestLLMBackendDetection:
    """Test backend detection without requiring LLM deps."""

    def test_backend_none_when_nothing_available(self, ontology_graph):
        """When no backends are available, backend should be 'none'."""
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=False):
            gen = LLMValueGenerator(ontology_graph)
            assert gen.backend == "none"
            assert not gen.available

    def test_prefers_ollama_when_both_available(self, ontology_graph):
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=True), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=True):
            gen = LLMValueGenerator(ontology_graph)
            assert gen.backend == "ollama"

    def test_falls_back_to_transformers(self, ontology_graph):
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=True):
            gen = LLMValueGenerator(ontology_graph)
            assert gen.backend == "transformers"

    def test_model_name_default_ollama(self, ontology_graph):
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=True):
            gen = LLMValueGenerator(ontology_graph)
            assert gen.model_name == DEFAULT_OLLAMA_MODEL

    def test_model_name_default_transformers(self, ontology_graph):
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=True):
            gen = LLMValueGenerator(ontology_graph)
            assert gen.model_name == DEFAULT_MODEL

    def test_custom_model_name(self, ontology_graph):
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=True):
            gen = LLMValueGenerator(ontology_graph, model="custom/model")
            assert gen.model_name == "custom/model"


# ==================================================================
# LLMValueGenerator — generate_values with mocked LLM
# ==================================================================

class TestLLMGeneration:
    """Test the generation flow with mocked LLM calls."""

    def test_generate_values_returns_list(self, ontology_graph, literal_meta, tmp_path):
        cache = ValueCache(cache_dir=tmp_path / "cache")
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=True):
            gen = LLMValueGenerator(ontology_graph, cache=cache)
            gen._call_llm = MagicMock(
                return_value='{"values": ["Alice", "Bob", "Charlie", "Diana", "Eve"]}'
            )
            result = gen.generate_values(
                literal_meta, count=5, shape_name="person",
            )
            assert result is not None
            assert len(result) >= 3  # At least count // 2
            gen._call_llm.assert_called_once()

    def test_caches_generated_values(self, ontology_graph, literal_meta, tmp_path):
        cache = ValueCache(cache_dir=tmp_path / "cache")
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=True):
            gen = LLMValueGenerator(ontology_graph, cache=cache)
            gen._call_llm = MagicMock(
                return_value='{"values": ["v1", "v2", "v3"]}'
            )
            gen.generate_values(
                literal_meta, count=5, shape_name="person",
            )
            # Second call should hit cache, not LLM
            gen._call_llm.reset_mock()
            result2 = gen.generate_values(
                literal_meta, count=5, shape_name="person",
            )
            assert result2 is not None
            gen._call_llm.assert_not_called()

    def test_returns_none_when_no_backend(self, ontology_graph, literal_meta, tmp_path):
        cache = ValueCache(cache_dir=tmp_path / "cache")
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=False):
            gen = LLMValueGenerator(ontology_graph, cache=cache)
            result = gen.generate_values(
                literal_meta, count=5, shape_name="person",
            )
            assert result is None

    def test_retries_on_bad_json(self, ontology_graph, literal_meta, tmp_path):
        cache = ValueCache(cache_dir=tmp_path / "cache")
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=True):
            gen = LLMValueGenerator(ontology_graph, cache=cache, max_retries=3)
            gen._call_llm = MagicMock(
                side_effect=[
                    "garbage output",
                    "still bad",
                    '{"values": ["success1", "success2", "success3"]}',
                ]
            )
            result = gen.generate_values(
                literal_meta, count=5, shape_name="person",
            )
            assert result is not None
            assert gen._call_llm.call_count == 3

    def test_returns_none_after_exhausted_retries(
        self, ontology_graph, literal_meta, tmp_path,
    ):
        cache = ValueCache(cache_dir=tmp_path / "cache")
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=True):
            gen = LLMValueGenerator(ontology_graph, cache=cache, max_retries=2)
            gen._call_llm = MagicMock(return_value="not json")
            result = gen.generate_values(
                literal_meta, count=5, shape_name="person",
            )
            assert result is None
            assert gen._call_llm.call_count == 2

    def test_skip_cache_when_disabled(self, ontology_graph, literal_meta, tmp_path):
        cache = ValueCache(cache_dir=tmp_path / "cache")
        # Pre-populate cache
        cache.put(
            "person", literal_meta.path_iri, "label",
            DEFAULT_MODEL, ["cached1"],
        )
        with patch.object(LLMValueGenerator, "_check_ollama", return_value=False), \
             patch.object(LLMValueGenerator, "_check_transformers", return_value=True):
            gen = LLMValueGenerator(ontology_graph, cache=cache)
            gen._call_llm = MagicMock(
                return_value='{"values": ["fresh1", "fresh2", "fresh3"]}'
            )
            result = gen.generate_values(
                literal_meta, count=5, shape_name="person", use_cache=False,
            )
            assert result is not None
            # Should have called LLM even though cache exists
            gen._call_llm.assert_called_once()


# ==================================================================
# Three-tier fallback in SyntheticDataGenerator
# ==================================================================

class TestThreeTierFallback:

    def test_default_no_llm(self, registry):
        """Default constructor should NOT use LLM."""
        gen = SyntheticDataGenerator(registry, seed=42)
        assert not gen._use_llm
        assert gen._llm_gen is None

    def test_use_llm_flag_stored(self, registry):
        gen = SyntheticDataGenerator(registry, seed=42, use_llm=True)
        assert gen._use_llm

    def test_generate_works_without_llm(self, registry):
        """Deterministic-only path should still work."""
        gen = SyntheticDataGenerator(registry, seed=42, pool_size=20)
        rows = gen.generate("person", count=5)
        assert len(rows) == 5
        assert "FirstName" in rows[0]

    def test_generate_with_llm_mocked(self, registry, tmp_path):
        """With mocked LLM backend, literal values should come from LLM."""
        from ceds_jsonld.sdg.generator import SyntheticDataGenerator

        gen = SyntheticDataGenerator(
            registry, seed=42, pool_size=10, use_llm=True,
        )
        # Mock the _get_llm_generator to return a fake that always works
        mock_llm = MagicMock()
        mock_llm.generate_values.return_value = [
            f"LLMValue{i}" for i in range(10)
        ]
        gen._get_llm_generator = MagicMock(return_value=mock_llm)

        rows = gen.generate("person", count=3)
        assert len(rows) == 3
        # The mock should have been called for literal properties
        assert mock_llm.generate_values.call_count > 0

    def test_llm_fallback_to_deterministic(self, registry):
        """When LLM returns None, fallback generators should kick in."""
        gen = SyntheticDataGenerator(
            registry, seed=42, pool_size=10, use_llm=True,
        )
        mock_llm = MagicMock()
        mock_llm.generate_values.return_value = None  # Simulate LLM failure
        gen._get_llm_generator = MagicMock(return_value=mock_llm)

        rows = gen.generate("person", count=3)
        assert len(rows) == 3
        # Should still have valid data from fallback
        assert "FirstName" in rows[0]
        assert rows[0]["FirstName"]  # Non-empty

    def test_sdg_imports_from_init(self):
        """New classes should be importable from ceds_jsonld.sdg."""
        from ceds_jsonld.sdg import (
            LLMValueGenerator,
            OntologyMetadataExtractor,
            ValueCache,
        )
        assert LLMValueGenerator is not None
        assert OntologyMetadataExtractor is not None
        assert ValueCache is not None
