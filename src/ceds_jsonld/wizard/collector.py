"""Shape metadata collector — aggregate target property info for matching.

Combines data from SHACLIntrospector and ConceptSchemeResolver to build
a flat list of TargetProperty objects that the matching engine scores
against source columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ceds_jsonld.introspector import NodeShapeInfo, PropertyInfo, SHACLIntrospector
from ceds_jsonld.logging import get_logger
from ceds_jsonld.registry import ShapeDefinition
from ceds_jsonld.transforms import BUILTIN_TRANSFORMS

_log = get_logger(__name__)


@dataclass
class TargetProperty:
    """A candidate target property from a CEDS shape.

    Attributes:
        name: Human-readable property name (e.g. ``"FirstName"``).
        path: CEDS IRI path (e.g. ``"ceds:P000115"``).
        parent_shape: Sub-shape name (e.g. ``"PersonNameShape"``).
        datatype: XSD type IRI if literal, ``None`` if object property.
        label: Human-readable label, defaults to name.
        description: Description string.
        is_required: ``True`` if ``sh:minCount > 0``.
        concept_values: List of ``skos:notation`` strings for concept schemes.
        available_transforms: List of compatible builtin transform names.
    """

    name: str
    path: str
    parent_shape: str
    datatype: str | None = None
    label: str = ""
    description: str = ""
    is_required: bool = False
    concept_values: list[str] = field(default_factory=list)
    available_transforms: list[str] = field(default_factory=list)


class ShapeMetadataCollector:
    """Collect target property metadata for a shape.

    Aggregates information from the SHACL introspector and concept scheme
    resolver into a flat list of TargetProperty objects.

    Args:
        shape_def: A loaded ShapeDefinition from the registry.
    """

    def __init__(self, shape_def: ShapeDefinition) -> None:
        self._shape_def = shape_def
        self._introspector = SHACLIntrospector(str(shape_def.shacl_path))
        self._concept_resolver = self._build_concept_resolver(shape_def)

    def collect(self) -> list[TargetProperty]:
        """Collect all leaf properties from the shape tree.

        Returns:
            List of TargetProperty, one per leaf SHACL property.
        """
        tree = self._introspector.shape_tree()
        iri_to_name = self._build_iri_to_name()
        targets: list[TargetProperty] = []
        self._walk_shape(tree, targets, iri_to_name)
        return targets

    def _walk_shape(
        self,
        shape: NodeShapeInfo,
        targets: list[TargetProperty],
        iri_to_name: dict[str, str],
        parent_name: str = "",
    ) -> None:
        """Recursively walk the shape tree and extract leaf properties."""
        shape_name = parent_name or shape.local_name

        for prop in shape.properties:
            # If this property has a nested sub-shape, recurse
            if prop.name in shape.children or prop.node_shape:
                child = shape.children.get(prop.name)
                if child is not None:
                    self._walk_shape(child, targets, iri_to_name, parent_name=child.local_name)
                continue

            # Leaf property — resolve friendly name from context
            friendly_name = iri_to_name.get(prop.path, prop.name or prop.path_local)
            concept_values = self._resolve_concept_values(prop)

            targets.append(
                TargetProperty(
                    name=friendly_name,
                    path=prop.path,
                    parent_shape=shape_name,
                    datatype=prop.datatype,
                    label=friendly_name,
                    description="",
                    is_required=bool(prop.min_count and prop.min_count > 0),
                    concept_values=concept_values,
                    available_transforms=sorted(BUILTIN_TRANSFORMS.keys()),
                )
            )

    def _resolve_concept_values(self, prop: PropertyInfo) -> list[str]:
        """Resolve concept scheme values for a property."""
        if not prop.allowed_values or not self._concept_resolver:
            # If no resolver but we have allowed_value IRIs, extract local names
            if prop.allowed_values:
                return [v.rsplit("/", 1)[-1].rsplit("#", 1)[-1] for v in prop.allowed_values]
            return []

        try:
            return list(self._concept_resolver.resolve_sh_in_values(prop.allowed_values))
        except Exception:
            _log.debug("Failed to resolve concept values", property=prop.path)
            # Fallback: extract local names from IRIs
            return [v.rsplit("/", 1)[-1].rsplit("#", 1)[-1] for v in prop.allowed_values]

    def _build_concept_resolver(self, shape_def: ShapeDefinition) -> Any:
        """Build a ConceptSchemeResolver if ontology files are available."""
        try:
            from ceds_jsonld.sdg.concept_resolver import ConceptSchemeResolver

            ontology_dir = Path(shape_def.shacl_path).parent.parent / "base"
            if not ontology_dir.exists():
                return None

            shape_dir = Path(shape_def.shacl_path).parent
            extension_files = list(shape_dir.glob("*_Extension_Ontology.ttl"))

            return ConceptSchemeResolver(
                ontology_dir=ontology_dir,
                extension_files=extension_files if extension_files else None,
            )
        except Exception:
            _log.debug("ConceptSchemeResolver not available; concept values will be empty")
            return None

    def _build_iri_to_name(self) -> dict[str, str]:
        """Build IRI→friendly-name lookup from the shape's JSON-LD context."""
        ctx = self._shape_def.context
        if not ctx:
            return {}

        ctx_inner = ctx.get("@context", ctx)
        if not isinstance(ctx_inner, dict):
            return {}

        result: dict[str, str] = {}
        for name, value in ctx_inner.items():
            if name.startswith("@"):
                continue
            if isinstance(value, str):
                iri = value
                # Resolve prefixed IRIs
                for prefix_name, prefix_iri in ctx_inner.items():
                    if isinstance(prefix_iri, str) and ":" in iri and not iri.startswith("http"):
                        parts = iri.split(":", 1)
                        if parts[0] == prefix_name:
                            iri = prefix_iri + parts[1]
                            break
                result[iri] = name
            elif isinstance(value, dict) and "@id" in value:
                id_val = str(value["@id"])
                # Resolve prefixed @id
                for prefix_name, prefix_iri in ctx_inner.items():
                    if isinstance(prefix_iri, str) and ":" in id_val and not id_val.startswith("http"):
                        parts = id_val.split(":", 1)
                        if parts[0] == prefix_name:
                            id_val = prefix_iri + parts[1]
                            break
                result[id_val] = name
        return result
