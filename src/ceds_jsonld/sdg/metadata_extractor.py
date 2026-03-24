"""Ontology metadata extractor — enrich property metadata for LLM prompts.

Queries the CEDS ontology graph for additional metadata beyond what the
concept resolver provides: parent class labels, ``skos:notation``, and
``schema:domainIncludes`` class names. Formats everything into structured
dicts ready for LLM prompt templates.

This module is NOT in the hot path — it runs once per shape at generation
time, not per-record.
"""

from __future__ import annotations

from typing import Any

from rdflib import Graph, URIRef
from rdflib.namespace import RDFS, SKOS, XSD

from ceds_jsonld.logging import get_logger
from ceds_jsonld.sdg.concept_resolver import PropertyMetadata

_log = get_logger(__name__)

SCHEMA = URIRef("https://schema.org/")


# ---------------------------------------------------------------------------
# Human-readable XSD type names
# ---------------------------------------------------------------------------

_XSD_DISPLAY: dict[str, str] = {
    f"{XSD}string": "string",
    f"{XSD}token": "token",
    f"{XSD}date": "date (YYYY-MM-DD)",
    f"{XSD}dateTime": "dateTime (YYYY-MM-DDTHH:MM:SS)",
    f"{XSD}integer": "integer",
    f"{XSD}int": "integer",
    f"{XSD}long": "long integer",
    f"{XSD}decimal": "decimal",
    f"{XSD}float": "float",
    f"{XSD}double": "double",
    f"{XSD}boolean": "boolean (true/false)",
    f"{XSD}nonNegativeInteger": "non-negative integer",
    f"{XSD}positiveInteger": "positive integer",
}


class OntologyMetadataExtractor:
    """Extract and format ontology metadata for LLM prompt building.

    Uses the ontology graph (already loaded by :class:`ConceptSchemeResolver`)
    to enrich property metadata with parent class labels and human-readable
    datatype names, then formats it into structured dicts for prompt templates.

    Example:
        >>> extractor = OntologyMetadataExtractor(resolver._graph)
        >>> info = extractor.extract_prompt_metadata(prop_meta)
        >>> info["parent_class_label"]
        'Person Name'
    """

    def __init__(self, ontology_graph: Graph) -> None:
        self._graph = ontology_graph

    def get_parent_class_label(self, property_iri: str) -> str:
        """Get the human-readable label of the property's domain class.

        Follows ``schema:domainIncludes`` to find the class, then reads
        its ``rdfs:label``.

        Args:
            property_iri: Full IRI of the property.

        Returns:
            The parent class label, or empty string if not found.
        """
        prop_ref = URIRef(property_iri)
        domain_pred = URIRef("https://schema.org/domainIncludes")
        for domain_cls in self._graph.objects(prop_ref, domain_pred):
            label = self._graph.value(domain_cls, RDFS.label)
            if label:
                return str(label).strip()
        return ""

    def get_skos_notation(self, property_iri: str) -> str:
        """Get the ``skos:notation`` for a property.

        Args:
            property_iri: Full IRI of the property.

        Returns:
            The notation string (e.g. "FirstName"), or empty string.
        """
        prop_ref = URIRef(property_iri)
        notation = self._graph.value(prop_ref, SKOS.notation)
        return str(notation).strip() if notation else ""

    def extract_prompt_metadata(self, meta: PropertyMetadata) -> dict[str, Any]:
        """Extract all metadata needed for an LLM prompt.

        Combines the already-populated ``PropertyMetadata`` fields with
        additional ontology lookups (parent class label, notation).

        Args:
            meta: A ``PropertyMetadata`` for a literal property.

        Returns:
            Dict with keys: ``property_label``, ``description``,
            ``data_type``, ``format``, ``max_length``, ``parent_class``,
            ``notation``, ``path_iri``.
        """
        parent_label = self.get_parent_class_label(meta.path_iri)
        notation = self.get_skos_notation(meta.path_iri)

        # Human-readable datatype
        xsd_display = _XSD_DISPLAY.get(meta.xsd_datatype or "", "string")

        return {
            "property_label": meta.label or notation or meta.name,
            "description": meta.description,
            "data_type": xsd_display,
            "format": meta.text_format or "",
            "max_length": meta.max_length,
            "parent_class": parent_label or meta.parent_shape_name,
            "notation": notation or meta.name,
            "path_iri": meta.path_iri,
        }

    def build_prompt(
        self,
        meta: PropertyMetadata,
        count: int = 200,
    ) -> str:
        """Build a complete LLM prompt for generating values for a property.

        Uses the prompt template from the FEATURE4 research document.

        Args:
            meta: A ``PropertyMetadata`` for a literal property.
            count: Number of values to request from the LLM.

        Returns:
            The formatted prompt string.
        """
        info = self.extract_prompt_metadata(meta)

        lines = [
            "You are a synthetic data generator for education data systems.",
            "",
            f"Generate exactly {count} realistic values for the following CEDS "
            "(Common Education Data Standards) property:",
            "",
            f"Property: {info['property_label']}",
        ]

        if info["description"]:
            lines.append(f"Description: {info['description']}")
        lines.append(f"Data Type: {info['data_type']}")
        if info["format"]:
            lines.append(f"Format: {info['format']}")
        if info["max_length"]:
            lines.append(f"Max Length: {info['max_length']}")
        lines.append(f"Parent Class: {info['parent_class']}")

        lines.extend(
            [
                "",
                "Context: This data is used in US K-12 and postsecondary education "
                "records managed by state education agencies.",
                "",
                "Requirements:",
                "- Values must be realistic and diverse (not repetitive)",
                "- Values must conform to the data type and format constraints",
            ]
        )

        if "string" in info["data_type"] and info["max_length"]:
            lines.append(f"- For string values: respect the max length of {info['max_length']}")
        if "date" in info["data_type"].lower():
            lines.append("- For date values: use ISO 8601 format (YYYY-MM-DD)")
        if "token" in info["data_type"]:
            lines.append("- For numeric tokens: generate realistic ID numbers")

        lines.extend(
            [
                "- Return ONLY the JSON object, no explanation",
                "",
                'Return your response as a JSON object: {"values": ["val1", "val2", ...]}',
            ]
        )

        return "\n".join(lines)
