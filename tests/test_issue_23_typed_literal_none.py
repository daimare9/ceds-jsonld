"""Tests for issue #23 — _typed_literal(None) must not produce '@value: None'.

Root cause: _typed_literal() called str(value) unconditionally, so None became
the string "None" and float('nan') became "nan".
"""

from __future__ import annotations

from ceds_jsonld import JSONLDBuilder, ShapeRegistry


def _get_builder() -> JSONLDBuilder:
    registry = ShapeRegistry()
    registry.load_shape("person")
    shape = registry.get_shape("person")
    return JSONLDBuilder(shape)


class TestTypedLiteralNoneHandling:
    """_typed_literal must return None (not string 'None') for null/nan/inf."""

    def test_none_returns_none(self) -> None:
        builder = _get_builder()
        result = builder._typed_literal(None, "xsd:string")
        assert result is None

    def test_nan_returns_none(self) -> None:
        builder = _get_builder()
        result = builder._typed_literal(float("nan"), "xsd:date")
        assert result is None

    def test_inf_returns_none(self) -> None:
        builder = _get_builder()
        result = builder._typed_literal(float("inf"), "xsd:date")
        assert result is None

    def test_neg_inf_returns_none(self) -> None:
        builder = _get_builder()
        result = builder._typed_literal(float("-inf"), "xsd:date")
        assert result is None

    def test_valid_string_produces_typed_literal(self) -> None:
        builder = _get_builder()
        result = builder._typed_literal("2000-01-01", "xsd:date")
        assert result == {"@type": "xsd:date", "@value": "2000-01-01"}

    def test_valid_int_produces_typed_literal(self) -> None:
        builder = _get_builder()
        result = builder._typed_literal(42, "xsd:integer")
        assert result == {"@type": "xsd:integer", "@value": "42"}

    def test_list_with_none_filters_nulls(self) -> None:
        builder = _get_builder()
        result = builder._typed_literal([None, "2000-01-01", None], "xsd:date")
        assert result == [{"@type": "xsd:date", "@value": "2000-01-01"}]

    def test_list_all_none_returns_none(self) -> None:
        builder = _get_builder()
        result = builder._typed_literal([None, None], "xsd:date")
        assert result is None

    def test_list_with_nan_filters_nan(self) -> None:
        builder = _get_builder()
        result = builder._typed_literal([float("nan"), "hello", float("inf")], "xsd:string")
        assert result == ["hello"]
