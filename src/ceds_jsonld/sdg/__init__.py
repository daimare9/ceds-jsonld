"""Synthetic Data Generator — generate realistic CEDS-conformant test data.

This sub-package provides tools to generate synthetic education data that
conforms to any registered SHACL shape. It works by combining ontology-derived
concept scheme values (deterministic random selection) with fallback generators
for literal properties (names, dates, IDs).

Example:
    >>> from ceds_jsonld.sdg import SyntheticDataGenerator
    >>> from ceds_jsonld import ShapeRegistry
    >>> registry = ShapeRegistry()
    >>> registry.load_shape("person")
    >>> gen = SyntheticDataGenerator(registry)
    >>> rows = gen.generate("person", count=100)
    >>> len(rows)
    100
"""

from __future__ import annotations

from ceds_jsonld.sdg.concept_resolver import ConceptSchemeResolver
from ceds_jsonld.sdg.fallback_generators import FallbackGenerators
from ceds_jsonld.sdg.generator import SyntheticDataGenerator

__all__ = [
    "ConceptSchemeResolver",
    "FallbackGenerators",
    "SyntheticDataGenerator",
]
