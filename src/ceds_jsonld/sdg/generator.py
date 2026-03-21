"""Synthetic data generator — core orchestrator.

Generates fully valid, CEDS-conformant synthetic data for any registered shape.
Uses concept scheme extraction from the ontology for enum properties, and
a three-tier fallback for literal properties:

1. **LLM generation** (optional) — produces realistic values via a local LLM.
2. **File cache** — reuses previously generated LLM values from disk.
3. **Deterministic fallback** — XSD-type-aware random generators.

The generator produces flat dicts that match what a CSVAdapter would yield,
making them directly usable with the existing Pipeline.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from ceds_jsonld.introspector import SHACLIntrospector
from ceds_jsonld.logging import get_logger
from ceds_jsonld.registry import ShapeDefinition, ShapeRegistry
from ceds_jsonld.sdg.assembler import MappingAwareAssembler
from ceds_jsonld.sdg.concept_resolver import ConceptSchemeResolver, PropertyMetadata
from ceds_jsonld.sdg.fallback_generators import FallbackGenerators

_log = get_logger(__name__)


class SyntheticDataGenerator:
    """Generate synthetic CEDS-conformant data for any registered shape.

    The generator:
    1. Loads the shape's SHACL, context, and mapping config via the registry.
    2. Classifies each property as concept, literal, or structural.
    3. For concept properties — extracts valid values from the CEDS ontology.
    4. For literal properties — generates value pools using fallback generators.
    5. Assembles flat rows using the mapping config's field layout.

    Example:
        >>> from ceds_jsonld import ShapeRegistry
        >>> from ceds_jsonld.sdg import SyntheticDataGenerator
        >>> registry = ShapeRegistry()
        >>> registry.load_shape("person")
        >>> gen = SyntheticDataGenerator(registry)
        >>> rows = gen.generate("person", count=100)
        >>> len(rows)
        100
        >>> "FirstName" in rows[0]
        True
    """

    def __init__(
        self,
        registry: ShapeRegistry,
        *,
        seed: int | None = None,
        pool_size: int = 200,
        use_llm: bool = False,
        use_cache: bool = True,
        llm_model: str | None = None,
    ) -> None:
        """Initialize the generator.

        Args:
            registry: A ShapeRegistry with at least one shape loaded.
            seed: Random seed for reproducibility. If ``None``, non-deterministic.
            pool_size: Number of values to pre-generate per property pool.
            use_llm: If ``True``, use LLM-powered value generation for literal
                properties. Requires ``ceds-jsonld[sdg]`` extras. Default is
                ``False`` (deterministic generators only).
            use_cache: If ``True`` (default), cache LLM-generated values to disk
                for reuse across runs. Only relevant when ``use_llm=True``.
            llm_model: Model identifier for LLM generation. If ``None``, uses
                the default model (Qwen/Qwen3-4B for transformers, qwen3:4b
                for Ollama).
        """
        self._registry = registry
        self._seed = seed
        self._pool_size = pool_size
        self._use_llm = use_llm
        self._use_cache = use_cache
        self._llm_model = llm_model
        self._fallback = FallbackGenerators(seed=seed)
        self._resolver: ConceptSchemeResolver | None = None
        self._llm_gen: Any = None  # Lazy-initialized LLMValueGenerator

    def generate(
        self,
        shape_name: str,
        *,
        count: int = 10,
        instances_range: tuple[int, int] = (1, 4),
    ) -> list[dict[str, str]]:
        """Generate synthetic source rows for a shape.

        The returned rows are flat dicts with string values, mimicking what
        a CSVAdapter would yield. They can be fed directly into the Pipeline.

        Args:
            shape_name: Name of the shape (e.g. "person").
            count: Number of rows to generate.
            instances_range: Min/max instances for ``cardinality: multiple``
                sub-shapes.

        Returns:
            List of flat row dicts.
        """
        shape_def = self._registry.get_shape(shape_name)
        mapping_config = shape_def.mapping_config

        # Initialize concept resolver with shape-specific ontology files
        resolver = self._get_resolver(shape_def)

        # Introspect the SHACL shape
        introspector = SHACLIntrospector(shape_def.shacl_path)

        # Classify all properties in the shape tree
        classified = resolver.classify_shape_properties(introspector)
        _log.info(
            "Shape properties classified",
            shape=shape_name,
            sub_shapes=len(classified),
            total_props=sum(len(v) for v in classified.values()),
        )

        # Build value pools for each source column
        value_pools = self._build_value_pools(
            mapping_config, classified, shape_def.context,
        )

        # Assemble rows
        assembler = MappingAwareAssembler(
            mapping_config,
            value_pools,
            seed=self._seed,
            instances_range=instances_range,
        )
        rows = assembler.assemble_batch(count)

        _log.info("Synthetic data generated", shape=shape_name, rows=len(rows))
        return rows

    def generate_csv(
        self,
        shape_name: str,
        output_path: str | Path,
        *,
        count: int = 10,
    ) -> Path:
        """Generate synthetic data and write to CSV.

        Args:
            shape_name: Name of the shape.
            output_path: Path for the output CSV file.
            count: Number of rows.

        Returns:
            The output file path.
        """
        rows = self.generate(shape_name, count=count)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if not rows:
            path.write_text("", encoding="utf-8")
            return path

        fieldnames = list(rows[0].keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        _log.info("CSV written", path=str(path), rows=len(rows))
        return path

    def generate_ndjson(
        self,
        shape_name: str,
        output_path: str | Path,
        *,
        count: int = 10,
    ) -> Path:
        """Generate synthetic data and write to NDJSON.

        Args:
            shape_name: Name of the shape.
            output_path: Path for the output NDJSON file.
            count: Number of rows.

        Returns:
            The output file path.
        """
        try:
            import orjson

            def _dumps(obj: Any) -> bytes:
                return orjson.dumps(obj)
        except ImportError:
            import json

            def _dumps(obj: Any) -> bytes:
                return json.dumps(obj).encode()

        rows = self.generate(shape_name, count=count)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("wb") as f:
            for row in rows:
                f.write(_dumps(row))
                f.write(b"\n")

        _log.info("NDJSON written", path=str(path), rows=len(rows))
        return path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_resolver(self, shape_def: ShapeDefinition) -> ConceptSchemeResolver:
        """Get or create a ConceptSchemeResolver with shape-specific extensions."""
        base_dir = Path(__file__).parent.parent / "ontologies" / "base"

        # Find extension ontology files for this shape
        extension_files: list[Path] = []
        ext_ontology = shape_def.base_dir / f"Person_Extension_Ontology.ttl"

        # More generically, look for any *_Extension_Ontology.ttl or *_Ontology.ttl
        for ttl_file in shape_def.base_dir.glob("*_Ontology.ttl"):
            extension_files.append(ttl_file)

        # Also check base dir for the main extension ontology
        base_ext = base_dir / "Person_Extension_Ontology.ttl"
        if base_ext.exists() and base_ext not in extension_files:
            extension_files.append(base_ext)

        if self._resolver is None:
            self._resolver = ConceptSchemeResolver(
                ontology_dir=base_dir,
                extension_files=extension_files,
            )
        return self._resolver

    @staticmethod
    def _build_iri_to_context_name(context: dict[str, Any]) -> dict[str, str]:
        """Build a reverse lookup from full property IRI → context name.

        The JSON-LD context maps human names like ``hasSex`` to prefixed IRIs
        like ``ceds:P000255``. This expands the prefixes and inverts the
        mapping so we can go from a full IRI back to the target name that
        the mapping YAML uses.
        """
        ctx = context.get("@context", context)

        # Collect namespace prefixes first
        prefixes: dict[str, str] = {}
        for key, val in ctx.items():
            if key.startswith("@"):
                continue
            if isinstance(val, str) and not ":" in val.split("//", 1)[-1]:
                # This is a prefix definition (no colon in the path part)
                # e.g. "ceds" -> "http://ceds.ed.gov/terms#"
                prefixes[key] = val

        # More reliable: prefixes are entries whose values are base IRIs
        prefixes = {}
        for key, val in ctx.items():
            if key.startswith("@"):
                continue
            if isinstance(val, str) and (val.endswith("#") or val.endswith("/")):
                prefixes[key] = val

        def _expand(prefixed: str) -> str:
            """Expand a prefixed IRI like ceds:P000255 to full IRI."""
            if prefixed.startswith("http"):
                return prefixed
            if ":" in prefixed:
                prefix, local = prefixed.split(":", 1)
                if prefix in prefixes:
                    return prefixes[prefix] + local
            return prefixed

        iri_to_name: dict[str, str] = {}
        for key, val in ctx.items():
            if key.startswith("@") or key in prefixes:
                continue
            if isinstance(val, str):
                full_iri = _expand(val)
                iri_to_name[full_iri] = key
            elif isinstance(val, dict) and "@id" in val:
                full_iri = _expand(str(val["@id"]))
                iri_to_name[full_iri] = key

        return iri_to_name

    def _build_value_pools(
        self,
        mapping_config: dict[str, Any],
        classified: dict[str, list[PropertyMetadata]],
        context: dict[str, Any],
    ) -> dict[str, list[str]]:
        """Build value pools keyed by source column name.

        Uses the JSON-LD context to bridge SHACL property P-codes to the
        target names used in the mapping YAML, ensuring concept properties
        get their ontology-derived values instead of random strings.

        Args:
            mapping_config: The parsed mapping YAML.
            classified: Classified properties from ConceptSchemeResolver.
            context: The shape's JSON-LD context dict.

        Returns:
            Dict mapping source column name → list of generated values.
        """
        pools: dict[str, list[str]] = {}

        # Build IRI → context name lookup (e.g. "http://ceds.ed.gov/terms#P000255" → "hasSex")
        iri_to_name = self._build_iri_to_context_name(context)

        # Build a lookup: context target name → PropertyMetadata
        # PropertyMetadata.name is a P-code (e.g. "P000255") and path_iri is the full IRI.
        # We resolve the IRI to the context name for matching against mapping YAML targets.
        meta_by_target: dict[str, PropertyMetadata] = {}
        for sub_shape_props in classified.values():
            for meta in sub_shape_props:
                context_name = iri_to_name.get(meta.path_iri)
                if context_name:
                    meta_by_target[context_name] = meta
                # Also index by P-code as fallback
                meta_by_target[meta.name] = meta

        # Walk the mapping config to find source columns and match them
        properties = mapping_config.get("properties", {})
        for prop_name, prop_cfg in properties.items():
            fields = prop_cfg.get("fields", {})
            for field_name, field_cfg in fields.items():
                source_col = field_cfg.get("source", field_name)
                target = field_cfg.get("target", field_name)

                if source_col in pools:
                    continue  # Already generated

                meta = meta_by_target.get(target)
                if meta is None:
                    # Not classified (possibly structural) — use field config hints
                    meta = self._meta_from_field_config(field_name, field_cfg, prop_name)
                elif meta.xsd_datatype is None and field_cfg.get("datatype"):
                    # Enrich SHACL-classified meta with YAML datatype info
                    enriched = self._meta_from_field_config(field_name, field_cfg, prop_name)
                    meta = PropertyMetadata(
                        name=meta.name,
                        path_iri=meta.path_iri,
                        category=meta.category,
                        xsd_datatype=enriched.xsd_datatype,
                        label=meta.label,
                        parent_shape_name=meta.parent_shape_name,
                        allowed_values=meta.allowed_values,
                    )

                if meta.category == "concept" and meta.allowed_values:
                    pools[source_col] = list(meta.allowed_values)
                    _log.debug(
                        "Concept pool created",
                        source=source_col,
                        target=target,
                        values=len(meta.allowed_values),
                    )
                else:
                    # Three-tier fallback: LLM → cache → deterministic
                    llm_values = None
                    if self._use_llm:
                        llm_gen = self._get_llm_generator()
                        if llm_gen is not None:
                            llm_values = llm_gen.generate_values(
                                meta,
                                count=self._pool_size,
                                shape_name=mapping_config.get("shape", ""),
                                use_cache=self._use_cache,
                            )

                    if llm_values is not None:
                        pools[source_col] = llm_values
                        _log.debug(
                            "LLM pool created",
                            source=source_col,
                            target=target,
                            values=len(llm_values),
                        )
                    else:
                        pools[source_col] = self._fallback.generate_pool(
                            meta, count=self._pool_size,
                        )
                        _log.debug(
                            "Fallback pool created",
                            source=source_col,
                            target=target,
                            values=self._pool_size,
                        )

        return pools

    def _get_llm_generator(self) -> Any:
        """Lazy-initialize the LLM value generator.

        Returns ``None`` if LLM dependencies are not installed or no
        backend is available.
        """
        if self._llm_gen is not None:
            return self._llm_gen

        try:
            from ceds_jsonld.sdg.llm_generator import LLMValueGenerator
        except ImportError:
            _log.warning(
                "LLM generation requested but dependencies not installed. "
                "Install with: pip install ceds-jsonld[sdg]"
            )
            return None

        if self._resolver is None:
            return None

        self._llm_gen = LLMValueGenerator(
            ontology_graph=self._resolver._graph,
            model=self._llm_model,
        )

        if not self._llm_gen.available:
            _log.warning(
                "No LLM backend available — falling back to deterministic generators. "
                "Run Ollama or install ceds-jsonld[sdg] for LLM support."
            )
            self._llm_gen = None
            return None

        return self._llm_gen

    def _meta_from_field_config(
        self,
        field_name: str,
        field_cfg: dict[str, Any],
        parent_prop: str,
    ) -> PropertyMetadata:
        """Create a PropertyMetadata from mapping field config when SHACL data is unavailable."""
        datatype = field_cfg.get("datatype")
        xsd_prefix = "http://www.w3.org/2001/XMLSchema#"
        xsd_dt = None
        if datatype:
            if datatype.startswith("xsd:"):
                xsd_dt = f"{xsd_prefix}{datatype[4:]}"
            elif datatype.startswith("http"):
                xsd_dt = datatype
            else:
                xsd_dt = f"{xsd_prefix}{datatype}"

        return PropertyMetadata(
            name=field_name,
            path_iri="",
            category="literal",
            xsd_datatype=xsd_dt,
            label=field_name,
            parent_shape_name=parent_prop,
        )
