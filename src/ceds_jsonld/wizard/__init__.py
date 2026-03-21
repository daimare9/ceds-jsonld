"""AI-Assisted Mapping Wizard — auto-map source columns to CEDS shapes.

Three-phase matching pipeline:
1. Concept-value matching (deterministic, <1ms)
2. Heuristic name matching (deterministic, <1ms)
3. LLM-assisted resolution (optional, 30-75s)

Example:
    >>> from ceds_jsonld.wizard import MappingWizard
    >>> wizard = MappingWizard()
    >>> result = wizard.suggest("students.csv", shape="person")
    >>> result.save("person_mapping.yaml")
"""

from __future__ import annotations

from ceds_jsonld.logging import get_logger
from ceds_jsonld.registry import ShapeRegistry
from ceds_jsonld.wizard.assembler import MappingAssembler, WizardResult
from ceds_jsonld.wizard.collector import ShapeMetadataCollector
from ceds_jsonld.wizard.engine import MatchingEngine
from ceds_jsonld.wizard.profiler import ColumnProfiler

_log = get_logger(__name__)


class MappingWizard:
    """Top-level orchestrator for the AI-assisted mapping wizard.

    Ties together profiling, metadata collection, matching, and assembly.

    Args:
        use_llm: Enable LLM-assisted Phase 3. Requires ``[sdg]`` extras.
        heuristic_threshold: Minimum heuristic confidence (default 0.4).
        llm_backend: "ollama" or "transformers", or ``None`` for auto.
        llm_model: Model name override, or ``None`` for default.
        shapes_dir: Additional directory to search for shape folders.
    """

    def __init__(
        self,
        *,
        use_llm: bool = True,
        heuristic_threshold: float = 0.4,
        llm_backend: str | None = None,
        llm_model: str | None = None,
        shapes_dir: str | None = None,
    ) -> None:
        self._use_llm = use_llm
        self._heuristic_threshold = heuristic_threshold
        self._llm_backend = llm_backend
        self._llm_model = llm_model
        self._registry = ShapeRegistry()
        if shapes_dir:
            self._registry.add_search_dir(shapes_dir)
        self._profiler = ColumnProfiler()

    def suggest(
        self,
        input_path: str,
        *,
        shape: str,
    ) -> WizardResult:
        """Generate a mapping YAML suggestion for the given data + shape.

        Args:
            input_path: Path to CSV or Excel file.
            shape: Shape name (e.g. "person").

        Returns:
            WizardResult with mapping config, confidence report, and YAML text.
        """
        # 1. Profile source columns
        columns = self._profiler.profile_from_csv(input_path)
        _log.info("Profiled %d columns from %s", len(columns), input_path)

        # 2. Load shape and collect target properties
        shape_def = self._registry.load_shape(shape)
        collector = ShapeMetadataCollector(shape_def)
        targets = collector.collect()
        _log.info("Collected %d target properties for shape '%s'", len(targets), shape)

        # 3. Run three-phase matching engine
        engine = MatchingEngine(
            use_llm=self._use_llm,
            heuristic_threshold=self._heuristic_threshold,
            llm_backend=self._llm_backend,
            llm_model=self._llm_model,
        )
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)
        _log.info(
            "Matching complete: %d matched, %d unmatched cols, %d unmatched targets",
            len(matches),
            len(unmatched_cols),
            len(unmatched_targets),
        )

        # 4. Assemble result
        assembler = MappingAssembler(shape)
        return assembler.assemble(
            matches=matches,
            unmapped_columns=unmatched_cols,
            unmapped_properties=unmatched_targets,
        )

    def detect_shape(
        self,
        input_path: str,
    ) -> list[tuple[str, float]]:
        """Auto-detect the best shape for the given data.

        Profiles columns and scores overlap against each available shape.

        Args:
            input_path: Path to CSV or Excel file.

        Returns:
            Sorted list of (shape_name, score) tuples, highest first.
        """
        columns = self._profiler.profile_from_csv(input_path)
        col_names_normalized = {c.normalized for c in columns}

        available = self._registry.list_available()
        scores: list[tuple[str, float]] = []

        for shape_name in available:
            try:
                shape_def = self._registry.load_shape(shape_name)
                collector = ShapeMetadataCollector(shape_def)
                targets = collector.collect()
                target_names_normalized = {t.name.lower().replace("_", "") for t in targets}

                if not target_names_normalized:
                    continue

                overlap = len(col_names_normalized & target_names_normalized)
                score = overlap / len(target_names_normalized)
                scores.append((shape_name, score))
            except Exception:
                _log.debug("Skipping shape '%s' during detection", shape_name, exc_info=True)

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def preview(
        self,
        input_path: str,
        result: WizardResult,
        *,
        count: int = 5,
    ) -> list[dict]:
        """Run a preview of the generated mapping through Pipeline.

        Args:
            input_path: Path to the same CSV/Excel file.
            result: WizardResult from a previous ``suggest()`` call.
            count: Max number of records to preview.

        Returns:
            List of JSON-LD document dicts.
        """
        from ceds_jsonld.adapters import CSVAdapter
        from ceds_jsonld.pipeline import Pipeline

        shape_name = result.mapping_config.get("shape", "")
        if not shape_name:
            return []

        # Load the shape and temporarily override its mapping_config
        shape_def = self._registry.load_shape(shape_name)
        original_config = shape_def.mapping_config
        object.__setattr__(shape_def, "mapping_config", result.mapping_config)

        try:
            adapter = CSVAdapter(input_path)
            pipeline = Pipeline(
                source=adapter,
                shape=shape_name,
                registry=self._registry,
            )
            docs: list[dict] = []
            for doc in pipeline.stream():
                docs.append(doc)
                if len(docs) >= count:
                    break
            return docs
        except Exception:
            _log.warning("Preview failed", exc_info=True)
            return []
        finally:
            object.__setattr__(shape_def, "mapping_config", original_config)


__all__: list[str] = ["MappingWizard", "WizardResult"]
