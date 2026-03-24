"""Tests for Issue #43: Simplify structure when element is of type xsd:string.

When ``datatype`` is ``"xsd:string"``, the builder should emit the plain string
value instead of the verbose ``{"@type": "xsd:string", "@value": "..."}`` form.
Non-string types (``xsd:date``, ``xsd:decimal``, ``xsd:token``, etc.) must
continue to use the typed-literal wrapper.
"""

from __future__ import annotations

from typing import Any

from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeDefinition, ShapeRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_builder() -> JSONLDBuilder:
    registry = ShapeRegistry()
    registry.load_shape("person")
    shape = registry.get_shape("person")
    return JSONLDBuilder(shape)


def _make_shape_def(properties: dict[str, Any]) -> ShapeDefinition:
    config: dict[str, Any] = {
        "shape": "TestShape",
        "context_url": "https://example.org/context.json",
        "base_uri": "ex:test/",
        "id_source": "Id",
        "type": "TestType",
        "properties": properties,
    }
    return ShapeDefinition(
        name="test",
        base_dir=None,  # type: ignore[arg-type]
        shacl_path=None,  # type: ignore[arg-type]
        context={},
        mapping_config=config,
    )


# ---------------------------------------------------------------------------
# Tests — _typed_literal with xsd:string returns plain value
# ---------------------------------------------------------------------------


class TestTypedLiteralStringSimplification:
    """xsd:string should return plain string, not typed-literal dict."""

    def test_string_value_returns_plain(self):
        builder = _get_builder()
        result = builder._typed_literal("hello", "xsd:string")
        assert result == "hello"

    def test_string_none_still_returns_none(self):
        builder = _get_builder()
        result = builder._typed_literal(None, "xsd:string")
        assert result is None

    def test_string_nan_still_returns_none(self):
        builder = _get_builder()
        result = builder._typed_literal(float("nan"), "xsd:string")
        assert result is None

    def test_string_list_returns_plain_strings(self):
        builder = _get_builder()
        result = builder._typed_literal(["a", "b", "c"], "xsd:string")
        assert result == ["a", "b", "c"]

    def test_string_list_filters_none(self):
        builder = _get_builder()
        result = builder._typed_literal([None, "hello", None], "xsd:string")
        assert result == ["hello"]

    def test_string_list_filters_nan(self):
        builder = _get_builder()
        result = builder._typed_literal([float("nan"), "hello", float("inf")], "xsd:string")
        assert result == ["hello"]

    def test_string_list_all_none_returns_none(self):
        builder = _get_builder()
        result = builder._typed_literal([None, None], "xsd:string")
        assert result is None

    def test_string_integer_coerced_to_str(self):
        """Numeric values with xsd:string datatype are stringified."""
        builder = _get_builder()
        result = builder._typed_literal(42, "xsd:string")
        assert result == "42"


# ---------------------------------------------------------------------------
# Tests — non-string types still use typed-literal wrapper
# ---------------------------------------------------------------------------


class TestNonStringTypesUnchanged:
    """xsd:date, xsd:decimal, xsd:token, etc. must still wrap."""

    def test_date_still_wrapped(self):
        builder = _get_builder()
        result = builder._typed_literal("2000-01-01", "xsd:date")
        assert result == {"@type": "xsd:date", "@value": "2000-01-01"}

    def test_decimal_still_wrapped(self):
        builder = _get_builder()
        result = builder._typed_literal("42.5", "xsd:decimal")
        assert result == {"@type": "xsd:decimal", "@value": "42.5"}

    def test_token_still_wrapped(self):
        builder = _get_builder()
        result = builder._typed_literal("989897099", "xsd:token")
        assert result == {"@type": "xsd:token", "@value": "989897099"}

    def test_datetime_still_wrapped(self):
        builder = _get_builder()
        result = builder._typed_literal("1900-01-01T00:00:00", "xsd:dateTime")
        assert result == {"@type": "xsd:dateTime", "@value": "1900-01-01T00:00:00"}

    def test_integer_still_wrapped(self):
        builder = _get_builder()
        result = builder._typed_literal(42, "xsd:integer")
        assert result == {"@type": "xsd:integer", "@value": "42"}


# ---------------------------------------------------------------------------
# Tests — end-to-end builder output with xsd:string fields
# ---------------------------------------------------------------------------


class TestBuilderEndToEndStringFields:
    """Full build_one output must have plain strings for xsd:string fields."""

    def test_org_name_is_plain_string(self):
        props = {
            "hasOrganizationTitle": {
                "type": "OrganizationTitle",
                "cardinality": "single",
                "fields": {
                    "OrganizationName": {
                        "source": "OrgName",
                        "target": "OrganizationName",
                        "datatype": "xsd:string",
                    },
                },
            },
        }
        shape = _make_shape_def(props)
        builder = JSONLDBuilder(shape)
        mapper = FieldMapper(shape.mapping_config)
        row = {"OrgName": "Washington Area ESA", "Id": "1"}
        doc = builder.build_one(mapper.map(row))
        title = doc["hasOrganizationTitle"]
        assert title["OrganizationName"] == "Washington Area ESA"
        assert isinstance(title["OrganizationName"], str)

    def test_date_field_still_wrapped_in_full_build(self):
        """Non-string datatype remains wrapped in the same build."""
        props = {
            "hasBirth": {
                "type": "Birth",
                "cardinality": "single",
                "fields": {
                    "Birthdate": {
                        "source": "DOB",
                        "target": "Birthdate",
                        "datatype": "xsd:date",
                    },
                },
            },
        }
        shape = _make_shape_def(props)
        builder = JSONLDBuilder(shape)
        mapper = FieldMapper(shape.mapping_config)
        row = {"DOB": "1990-01-15", "Id": "1"}
        doc = builder.build_one(mapper.map(row))
        assert doc["hasBirth"]["Birthdate"] == {"@type": "xsd:date", "@value": "1990-01-15"}

    def test_mixed_string_and_nonstring_in_same_shape(self):
        """Shape with both xsd:string and xsd:decimal fields."""
        props = {
            "hasLocation": {
                "type": "Location",
                "cardinality": "single",
                "fields": {
                    "AddressCity": {
                        "source": "City",
                        "target": "AddressCity",
                        "datatype": "xsd:string",
                    },
                    "Latitude": {
                        "source": "Lat",
                        "target": "Latitude",
                        "datatype": "xsd:decimal",
                    },
                },
            },
        }
        shape = _make_shape_def(props)
        builder = JSONLDBuilder(shape)
        mapper = FieldMapper(shape.mapping_config)
        row = {"City": "Lansing", "Lat": "42.7325", "Id": "1"}
        doc = builder.build_one(mapper.map(row))
        loc = doc["hasLocation"]
        # String field → plain value
        assert loc["AddressCity"] == "Lansing"
        assert isinstance(loc["AddressCity"], str)
        # Decimal field → typed literal
        assert loc["Latitude"] == {"@type": "xsd:decimal", "@value": "42.7325"}


# ---------------------------------------------------------------------------
# Tests — Person shape regression (no xsd:string fields in Person)
# ---------------------------------------------------------------------------


class TestPersonShapeRegression:
    """Person shape has no xsd:string fields — output must be unchanged."""

    def test_person_birthdate_still_wrapped(self, person_shape_def, sample_person_row_full):
        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)
        doc = builder.build_one(mapper.map(sample_person_row_full))
        assert doc["hasPersonBirth"]["Birthdate"] == {"@type": "xsd:date", "@value": "1965-05-15"}

    def test_person_identifier_still_wrapped(self, person_shape_def, sample_person_row_full):
        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)
        doc = builder.build_one(mapper.map(sample_person_row_full))
        ids = doc["hasPersonIdentification"]
        assert ids[0]["PersonIdentifier"] == {"@type": "xsd:token", "@value": "989897099"}

    def test_person_name_still_plain(self, person_shape_def, sample_person_row_full):
        """Name fields have no datatype — must remain plain strings."""
        mapper = FieldMapper(person_shape_def.mapping_config)
        builder = JSONLDBuilder(person_shape_def)
        doc = builder.build_one(mapper.map(sample_person_row_full))
        assert doc["hasPersonName"]["FirstName"] == "EDITH"
        assert isinstance(doc["hasPersonName"]["FirstName"], str)
