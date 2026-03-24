"""Concept scheme resolver — extract valid enum values from CEDS ontology.

Resolves concept scheme properties in two ways:

* **Path A (sh:in):** SHACL property has an explicit ``sh:in`` list of IRI
  references — resolve each IRI to its ``skos:notation`` from the ontology.
* **Path B (rangeIncludes):** No ``sh:in`` list — follow the property's
  ``schema:rangeIncludes`` to a concept scheme class, then enumerate all
  ``owl:NamedIndividual`` members of that class via ``skos:inScheme`` or
  ``rdf:type``.

This module is NOT in the hot path — it runs once at generation time, not
per-record. The resulting value pools are cached for fast random sampling.
"""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from ceds_jsonld.exceptions import ShapeLoadError
from ceds_jsonld.introspector import NodeShapeInfo, PropertyInfo, SHACLIntrospector
from ceds_jsonld.logging import get_logger

_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------

CEDS = Namespace("http://ceds.ed.gov/terms#")
CEPI = Namespace("http://cepi-dev.state.mi.us/")
SCHEMA = Namespace("https://schema.org/")
DC = Namespace("http://purl.org/dc/elements/1.1/")

# Structural classes that get default values (not concept schemes)
_STRUCTURAL_CLASSES = frozenset(
    {
        str(CEDS["C200411"]),  # RecordStatus
        str(CEDS["C200410"]),  # DataCollection
    }
)


# ---------------------------------------------------------------------------
# Property metadata (used by generators)
# ---------------------------------------------------------------------------


class PropertyMetadata:
    """Metadata extracted for a single SHACL property.

    Attributes:
        name: Context name of the property (e.g. "FirstName", "hasSex").
        path_iri: Full IRI of the property path (e.g. "http://ceds.ed.gov/terms#P000115").
        category: One of "concept", "literal", or "structural".
        xsd_datatype: XSD datatype IRI for literal properties, or None.
        allowed_values: List of skos:notation strings for concept scheme properties.
        label: Human-readable label from rdfs:label.
        description: Description from dc:description.
        max_length: Maximum string length from the ontology, or None.
        text_format: Text format constraint (e.g. "Alphanumeric"), or None.
        parent_shape_name: Name of the parent sub-shape (e.g. "PersonName").
        node_class: Target class IRI for object properties, or None.
    """

    __slots__ = (
        "name",
        "path_iri",
        "category",
        "xsd_datatype",
        "allowed_values",
        "label",
        "description",
        "max_length",
        "text_format",
        "parent_shape_name",
        "node_class",
    )

    def __init__(
        self,
        name: str,
        path_iri: str,
        *,
        category: str = "literal",
        xsd_datatype: str | None = None,
        allowed_values: list[str] | None = None,
        label: str = "",
        description: str = "",
        max_length: int | None = None,
        text_format: str | None = None,
        parent_shape_name: str = "",
        node_class: str | None = None,
    ) -> None:
        self.name = name
        self.path_iri = path_iri
        self.category = category
        self.xsd_datatype = xsd_datatype
        self.allowed_values = allowed_values or []
        self.label = label
        self.description = description
        self.max_length = max_length
        self.text_format = text_format
        self.parent_shape_name = parent_shape_name
        self.node_class = node_class

    def __repr__(self) -> str:
        return f"PropertyMetadata(name={self.name!r}, category={self.category!r}, values={len(self.allowed_values)})"


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------


class ConceptSchemeResolver:
    """Resolve concept scheme values from CEDS ontology files.

    Loads the CEDS ontology (RDF/XML), Common.ttl, and any shape-specific
    extension ontologies into a single rdflib Graph. Then, for each concept
    scheme property in a SHACL shape, resolves the valid ``skos:notation``
    values.

    Example:
        >>> resolver = ConceptSchemeResolver(
        ...     ontology_dir=Path("src/ceds_jsonld/ontologies/base"),
        ...     extension_files=[Path("src/ceds_jsonld/ontologies/base/Person_Extension_Ontology.ttl")],
        ... )
        >>> values = resolver.resolve_property_values(
        ...     property_iri="http://ceds.ed.gov/terms#P001571",
        ...     allowed_value_iris=["http://ceds.ed.gov/terms#NI001571173132", ...],
        ... )
        >>> "SSN" in values
        True
    """

    def __init__(
        self,
        ontology_dir: Path | None = None,
        *,
        extension_files: list[Path] | None = None,
    ) -> None:
        """Initialize the resolver and load ontology files.

        Args:
            ontology_dir: Directory containing CEDS-Ontology.rdf and Common.ttl.
                Defaults to the shipped ``ontologies/base`` directory.
            extension_files: Additional Turtle files to load (e.g.
                Person_Extension_Ontology.ttl).
        """
        if ontology_dir is None:
            ontology_dir = Path(__file__).parent.parent / "ontologies" / "base"

        self._ontology_dir = ontology_dir
        self._graph = Graph()
        self._loaded = False
        self._extension_files = extension_files or []
        self._load_ontology()

    def _load_ontology(self) -> None:
        """Load CEDS ontology plus extensions into a single graph."""
        rdf_path = self._ontology_dir / "CEDS-Ontology.rdf"
        common_path = self._ontology_dir / "Common.ttl"

        if not rdf_path.exists():
            msg = (
                f"CEDS ontology not found at {rdf_path}. "
                f"Ensure the ontologies/base/ directory contains CEDS-Ontology.rdf."
            )
            raise ShapeLoadError(msg)

        _log.info("Loading CEDS ontology", path=str(rdf_path))
        self._graph.parse(str(rdf_path), format="xml")
        _log.info(
            "CEDS ontology loaded",
            triples=len(self._graph),
        )

        if common_path.exists():
            self._graph.parse(str(common_path), format="turtle")
            _log.debug("Loaded Common.ttl")

        for ext_path in self._extension_files:
            if ext_path.exists():
                fmt = "turtle" if ext_path.suffix == ".ttl" else "xml"
                self._graph.parse(str(ext_path), format=fmt)
                _log.debug("Loaded extension", path=str(ext_path))

        self._graph.bind("ceds", CEDS)
        self._graph.bind("cepi", CEPI)
        self._graph.bind("skos", SKOS)
        self._loaded = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_sh_in_values(self, allowed_value_iris: list[str]) -> list[str]:
        """Resolve ``sh:in`` IRI references to ``skos:notation`` strings.

        Path A: The SHACL property has an explicit ``sh:in`` list. Resolve
        each IRI to its ``skos:notation`` from the ontology.

        Args:
            allowed_value_iris: List of IRI strings from ``sh:in``.

        Returns:
            List of ``skos:notation`` values (e.g. ``["SSN", "EducatorID", ...]``).
        """
        notations: list[str] = []
        for iri_str in allowed_value_iris:
            iri = URIRef(iri_str)
            notation = self._get_notation(iri)
            if notation:
                notations.append(notation)
            else:
                _log.warning(
                    "Could not resolve skos:notation for IRI",
                    iri=iri_str,
                )
        return notations

    def resolve_concept_class_members(self, class_iri: str) -> list[str]:
        """Resolve all NamedIndividual members of a concept scheme class.

        Path B: No ``sh:in`` list — find all ``owl:NamedIndividual`` instances
        that are members of the given class (via ``rdf:type`` or ``skos:inScheme``).

        Args:
            class_iri: IRI of the concept scheme class (e.g. ``ceds:C000255``).

        Returns:
            List of ``skos:notation`` values for all members.
        """
        class_ref = URIRef(class_iri)
        notations: list[str] = []

        # Find NamedIndividuals that are rdf:type of this class
        for individual in self._graph.subjects(RDF.type, class_ref):
            # Confirm it's an owl:NamedIndividual
            if (individual, RDF.type, OWL.NamedIndividual) in self._graph:
                notation = self._get_notation(individual)
                if notation:
                    notations.append(notation)

        if not notations:
            # Fallback: try skos:inScheme
            for individual in self._graph.subjects(SKOS.inScheme, class_ref):
                if (individual, RDF.type, OWL.NamedIndividual) in self._graph:
                    notation = self._get_notation(individual)
                    if notation:
                        notations.append(notation)

        return sorted(set(notations))

    def resolve_range_class(self, property_iri: str) -> str | None:
        """Find the range class for a property via ``schema:rangeIncludes``.

        Args:
            property_iri: Full IRI of the property.

        Returns:
            The range class IRI, or ``None`` if not found or if range is an XSD type.
        """
        prop_ref = URIRef(property_iri)
        for range_obj in self._graph.objects(prop_ref, SCHEMA.rangeIncludes):
            range_str = str(range_obj)
            # Skip XSD datatypes — those are literal properties
            if range_str.startswith(str(XSD)):
                continue
            return range_str
        return None

    def get_property_label(self, property_iri: str) -> str:
        """Get the ``rdfs:label`` for a property.

        Args:
            property_iri: Full IRI of the property.

        Returns:
            The label string, or empty string if not found.
        """
        prop_ref = URIRef(property_iri)
        for label in self._graph.objects(prop_ref, RDFS.label):
            return str(label).strip()
        return ""

    def get_property_description(self, property_iri: str) -> str:
        """Get the ``dc:description`` for a property.

        Args:
            property_iri: Full IRI of the property.

        Returns:
            The description string, or empty string if not found.
        """
        prop_ref = URIRef(property_iri)
        for desc in self._graph.objects(prop_ref, DC.description):
            return str(desc).strip()
        return ""

    def get_property_max_length(self, property_iri: str) -> int | None:
        """Get the ``maxLength`` annotation for a property.

        Args:
            property_iri: Full IRI of the property.

        Returns:
            The max length integer, or ``None`` if not annotated.
        """
        prop_ref = URIRef(property_iri)
        max_len_pred = URIRef("http://ceds.ed.gov/terms#maxLength")
        for val in self._graph.objects(prop_ref, max_len_pred):
            try:
                return int(str(val))
            except (ValueError, TypeError):
                pass
        return None

    def get_property_text_format(self, property_iri: str) -> str | None:
        """Get the ``textFormat`` annotation for a property.

        Args:
            property_iri: Full IRI of the property.

        Returns:
            The text format string, or ``None`` if not annotated.
        """
        prop_ref = URIRef(property_iri)
        fmt_pred = URIRef("http://ceds.ed.gov/terms#textFormat")
        for val in self._graph.objects(prop_ref, fmt_pred):
            return str(val).strip()
        return None

    def classify_and_resolve(
        self,
        prop_info: PropertyInfo,
        parent_shape: NodeShapeInfo,
    ) -> PropertyMetadata:
        """Classify a SHACL property and resolve its values if concept-based.

        Uses the algorithm from the PoC:
        - If the property has ``sh:in`` allowed values → CONCEPT (Path A)
        - If the property has a ``node_class`` in structural classes → STRUCTURAL
        - If the property's range is a non-XSD class → CONCEPT (Path B)
        - Otherwise → LITERAL

        Args:
            prop_info: Introspected property from SHACL.
            parent_shape: The parent NodeShape containing this property.

        Returns:
            PropertyMetadata with category and resolved values.
        """
        path_iri = prop_info.path

        # Path A: sh:in is present — direct concept enum
        if prop_info.allowed_values:
            values = self.resolve_sh_in_values(prop_info.allowed_values)
            return PropertyMetadata(
                name=prop_info.name,
                path_iri=path_iri,
                category="concept",
                allowed_values=values,
                label=self.get_property_label(path_iri),
                description=self.get_property_description(path_iri),
                parent_shape_name=parent_shape.local_name,
            )

        # Structural: RecordStatus, DataCollection
        if prop_info.node_class and str(prop_info.node_class) in _STRUCTURAL_CLASSES:
            return PropertyMetadata(
                name=prop_info.name,
                path_iri=path_iri,
                category="structural",
                node_class=str(prop_info.node_class),
                parent_shape_name=parent_shape.local_name,
            )

        # Object property with node reference (sub-shape) — not a leaf
        if prop_info.node_shape:
            return PropertyMetadata(
                name=prop_info.name,
                path_iri=path_iri,
                category="structural",
                node_class=str(prop_info.node_class) if prop_info.node_class else None,
                parent_shape_name=parent_shape.local_name,
            )

        # Path B: No sh:in — check rangeIncludes for concept scheme class
        range_class = self.resolve_range_class(path_iri)
        if range_class and not range_class.startswith(str(XSD)):
            values = self.resolve_concept_class_members(range_class)
            if values:
                return PropertyMetadata(
                    name=prop_info.name,
                    path_iri=path_iri,
                    category="concept",
                    allowed_values=values,
                    label=self.get_property_label(path_iri),
                    description=self.get_property_description(path_iri),
                    parent_shape_name=parent_shape.local_name,
                )

        # Default: literal property
        return PropertyMetadata(
            name=prop_info.name,
            path_iri=path_iri,
            category="literal",
            xsd_datatype=prop_info.datatype,
            label=self.get_property_label(path_iri),
            description=self.get_property_description(path_iri),
            max_length=self.get_property_max_length(path_iri),
            text_format=self.get_property_text_format(path_iri),
            parent_shape_name=parent_shape.local_name,
        )

    def classify_shape_properties(
        self,
        introspector: SHACLIntrospector,
    ) -> dict[str, list[PropertyMetadata]]:
        """Classify all properties in a shape tree.

        Walks the full shape tree from root, classifying each leaf property
        in each sub-shape.

        Args:
            introspector: A loaded SHACLIntrospector for the target shape.

        Returns:
            Dict mapping sub-shape local name → list of PropertyMetadata.
            Only includes sub-shapes with classifiable leaf properties.
        """
        root = introspector.shape_tree()
        result: dict[str, list[PropertyMetadata]] = {}

        for root_prop in root.properties:
            if root_prop.name not in root.children:
                continue
            child_shape = root.children[root_prop.name]

            # Skip structural (RecordStatus/DataCollection) sub-shapes
            if child_shape.target_class and str(child_shape.target_class) in _STRUCTURAL_CLASSES:
                continue

            props: list[PropertyMetadata] = []
            for child_prop in child_shape.properties:
                meta = self.classify_and_resolve(child_prop, child_shape)
                if meta.category != "structural":
                    props.append(meta)

            if props:
                result[child_shape.local_name] = props

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_notation(self, iri: URIRef) -> str | None:
        """Get ``skos:notation`` for an IRI, falling back to ``rdfs:label``."""
        for notation in self._graph.objects(iri, SKOS.notation):
            return str(notation)
        for label in self._graph.objects(iri, RDFS.label):
            return str(label).strip()
        return None
