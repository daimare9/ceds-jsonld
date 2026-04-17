"""Tests for the id_is_uri feature.

When ``id_is_uri: true`` is set in a mapping config, the source value for the
document identifier is already a fully qualified URI.  The builder should use
it verbatim as ``@id`` — no ``base_uri`` prefix, no ``sanitize_iri_component``.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeDefinition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_shape_def(*, id_is_uri: bool = False, base_uri: str = "ex:test/") -> ShapeDefinition:
    """Build a minimal ShapeDefinition with configurable id_is_uri."""
    config: dict[str, Any] = {
        "shape": "TestShape",
        "context_url": "https://example.org/context.json",
        "base_uri": base_uri,
        "id_source": "PersonURI",
        "id_is_uri": id_is_uri,
        "type": "Person",
        "properties": {},
    }
    return ShapeDefinition(
        name="test",
        base_dir=None,  # type: ignore[arg-type]
        shacl_path=None,  # type: ignore[arg-type]
        context={},
        mapping_config=config,
    )


def _build_doc(shape_def: ShapeDefinition, raw_row: dict[str, Any]) -> dict[str, Any]:
    """Map + build a single document."""
    mapper = FieldMapper(shape_def.mapping_config)
    builder = JSONLDBuilder(shape_def)
    return builder.build_one(mapper.map(raw_row))


# ---------------------------------------------------------------------------
# Tests — id_is_uri: true
# ---------------------------------------------------------------------------


class TestIdIsUriEnabled:
    """When id_is_uri is true, the source value should be @id verbatim."""

    def test_http_uri_used_verbatim(self):
        shape = _make_shape_def(id_is_uri=True)
        doc = _build_doc(shape, {"PersonURI": "https://example.org/person/12345"})
        assert doc["@id"] == "https://example.org/person/12345"

    def test_urn_uri_used_verbatim(self):
        shape = _make_shape_def(id_is_uri=True)
        doc = _build_doc(shape, {"PersonURI": "urn:ceds:person:99887766"})
        assert doc["@id"] == "urn:ceds:person:99887766"

    def test_base_uri_is_ignored(self):
        """Even when base_uri is set, id_is_uri means it's not prefixed."""
        shape = _make_shape_def(id_is_uri=True, base_uri="cepi:person/")
        doc = _build_doc(shape, {"PersonURI": "https://example.org/person/42"})
        assert doc["@id"] == "https://example.org/person/42"
        assert not doc["@id"].startswith("cepi:person/")

    def test_slashes_not_percent_encoded(self):
        """Slashes in a full URI must NOT be percent-encoded."""
        shape = _make_shape_def(id_is_uri=True)
        doc = _build_doc(shape, {"PersonURI": "https://example.org/person/42"})
        assert "%2F" not in doc["@id"]
        assert "://" in doc["@id"]

    def test_colons_not_percent_encoded(self):
        """Colons in a full URI must NOT be percent-encoded."""
        shape = _make_shape_def(id_is_uri=True)
        doc = _build_doc(shape, {"PersonURI": "https://example.org/person/42"})
        assert "%3A" not in doc["@id"]

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace should be stripped from the URI."""
        shape = _make_shape_def(id_is_uri=True)
        doc = _build_doc(shape, {"PersonURI": "  https://example.org/person/42  "})
        assert doc["@id"] == "https://example.org/person/42"

    def test_context_and_type_still_present(self):
        """Other document keys are unaffected by id_is_uri."""
        shape = _make_shape_def(id_is_uri=True)
        doc = _build_doc(shape, {"PersonURI": "https://example.org/person/1"})
        assert doc["@context"] == "https://example.org/context.json"
        assert doc["@type"] == "Person"


# ---------------------------------------------------------------------------
# Tests — id_is_uri: false (default behaviour unchanged)
# ---------------------------------------------------------------------------


class TestIdIsUriDisabled:
    """Default behaviour: base_uri + sanitized ID."""

    def test_default_prefixes_base_uri(self):
        shape = _make_shape_def(id_is_uri=False)
        doc = _build_doc(shape, {"PersonURI": "12345"})
        assert doc["@id"] == "ex:test/12345"

    def test_omitted_flag_defaults_to_false(self):
        """If id_is_uri is not in the config at all, default is prefixed."""
        config: dict[str, Any] = {
            "shape": "TestShape",
            "context_url": "https://example.org/context.json",
            "base_uri": "ex:test/",
            "id_source": "PersonURI",
            # id_is_uri is intentionally absent
            "type": "Person",
            "properties": {},
        }
        shape = ShapeDefinition(
            name="test",
            base_dir=None,  # type: ignore[arg-type]
            shacl_path=None,  # type: ignore[arg-type]
            context={},
            mapping_config=config,
        )
        doc = _build_doc(shape, {"PersonURI": "12345"})
        assert doc["@id"] == "ex:test/12345"


# ---------------------------------------------------------------------------
# Tests — warning on non-URI values
# ---------------------------------------------------------------------------


class TestIdIsUriWarnings:
    """When id_is_uri is true but value doesn't look like a URI, warn."""

    def test_warns_on_plain_string(self, caplog):
        shape = _make_shape_def(id_is_uri=True)
        with caplog.at_level(logging.WARNING):
            doc = _build_doc(shape, {"PersonURI": "just-a-plain-id"})
        # Document should still be built — value passes through
        assert doc["@id"] == "just-a-plain-id"
        assert any("id_is_uri" in r.message or "does not look like a URI" in r.message for r in caplog.records)

    def test_no_warning_on_valid_http_uri(self, caplog):
        shape = _make_shape_def(id_is_uri=True)
        with caplog.at_level(logging.WARNING):
            _build_doc(shape, {"PersonURI": "https://example.org/person/1"})
        uri_warnings = [r for r in caplog.records if "id_is_uri" in r.message or "does not look like a URI" in r.message]
        assert len(uri_warnings) == 0

    def test_no_warning_on_urn(self, caplog):
        shape = _make_shape_def(id_is_uri=True)
        with caplog.at_level(logging.WARNING):
            _build_doc(shape, {"PersonURI": "urn:ceds:person:42"})
        uri_warnings = [r for r in caplog.records if "id_is_uri" in r.message or "does not look like a URI" in r.message]
        assert len(uri_warnings) == 0


# ---------------------------------------------------------------------------
# Tests — id_is_uri with id_transform
# ---------------------------------------------------------------------------


class TestIdIsUriWithTransform:
    """id_transform should still be applied before using the URI."""

    def test_first_pipe_split_with_uri(self):
        config: dict[str, Any] = {
            "shape": "TestShape",
            "context_url": "https://example.org/context.json",
            "base_uri": "ex:test/",
            "id_source": "PersonURI",
            "id_transform": "first_pipe_split",
            "id_is_uri": True,
            "type": "Person",
            "properties": {},
        }
        shape = ShapeDefinition(
            name="test",
            base_dir=None,  # type: ignore[arg-type]
            shacl_path=None,  # type: ignore[arg-type]
            context={},
            mapping_config=config,
        )
        doc = _build_doc(shape, {"PersonURI": "https://example.org/person/1|https://example.org/person/2"})
        assert doc["@id"] == "https://example.org/person/1"
