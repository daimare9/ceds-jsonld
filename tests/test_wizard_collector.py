"""Tests for ShapeMetadataCollector — target property aggregation."""

from __future__ import annotations

from ceds_jsonld.wizard.collector import ShapeMetadataCollector, TargetProperty


class TestTargetProperty:
    """TargetProperty dataclass tests."""

    def test_target_property_fields(self) -> None:
        tp = TargetProperty(
            name="FirstName",
            path="ceds:P000115",
            parent_shape="PersonName",
            datatype="http://www.w3.org/2001/XMLSchema#string",
            label="First Name",
            description="The full legal first name.",
            is_required=False,
            concept_values=[],
            available_transforms=[],
        )
        assert tp.name == "FirstName"
        assert tp.parent_shape == "PersonName"
        assert tp.is_required is False


class TestShapeMetadataCollector:
    """ShapeMetadataCollector integration tests using real Person shape."""

    def test_collect_person_shape(self) -> None:
        from ceds_jsonld.registry import ShapeRegistry

        registry = ShapeRegistry()
        shape_def = registry.load_shape("person")

        collector = ShapeMetadataCollector(shape_def)
        targets = collector.collect()

        names = {t.name for t in targets}
        assert "FirstName" in names
        assert "LastOrSurname" in names
        assert "Birthdate" in names

    def test_concept_values_populated(self) -> None:
        from ceds_jsonld.registry import ShapeRegistry

        registry = ShapeRegistry()
        shape_def = registry.load_shape("person")

        collector = ShapeMetadataCollector(shape_def)
        targets = collector.collect()

        # hasPersonIdentificationSystem should have concept scheme values
        id_sys = [t for t in targets if t.name == "hasPersonIdentificationSystem"]
        assert len(id_sys) == 1
        assert len(id_sys[0].concept_values) > 0

    def test_available_transforms_populated(self) -> None:
        from ceds_jsonld.registry import ShapeRegistry

        registry = ShapeRegistry()
        shape_def = registry.load_shape("person")

        collector = ShapeMetadataCollector(shape_def)
        targets = collector.collect()

        for t in targets:
            assert isinstance(t.available_transforms, list)

    def test_parent_shape_assigned(self) -> None:
        from ceds_jsonld.registry import ShapeRegistry

        registry = ShapeRegistry()
        shape_def = registry.load_shape("person")

        collector = ShapeMetadataCollector(shape_def)
        targets = collector.collect()

        first = [t for t in targets if t.name == "FirstName"][0]
        assert "Name" in first.parent_shape
