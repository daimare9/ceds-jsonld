"""Matching engine — three-phase orchestrator for column-to-property matching.

Phase 1: Concept-value matching (deterministic, <1ms)
Phase 2: Heuristic name matching (deterministic, <1ms)
Phase 3: LLM-assisted resolution (optional, 30-75s)

Columns resolved in earlier phases are not sent to later phases.
"""

from __future__ import annotations

from ceds_jsonld.logging import get_logger
from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.concept_matcher import ConceptValueMatcher, MatchCandidate
from ceds_jsonld.wizard.heuristic import HeuristicMatcher
from ceds_jsonld.wizard.profiler import ColumnProfile

_log = get_logger(__name__)


class MatchingEngine:
    """Three-phase matching engine.

    Args:
        use_llm: Whether to use LLM for Phase 3 (requires ``[sdg]`` extras).
        heuristic_threshold: Minimum heuristic confidence to accept a match.
        llm_backend: LLM backend name ("transformers" or "ollama"), or ``None`` for auto.
        llm_model: Model name override, or ``None`` for default.
    """

    def __init__(
        self,
        *,
        use_llm: bool = True,
        heuristic_threshold: float = 0.4,
        llm_backend: str | None = None,
        llm_model: str | None = None,
    ) -> None:
        self._use_llm = use_llm
        self._heuristic_threshold = heuristic_threshold
        self._llm_backend = llm_backend
        self._llm_model = llm_model
        self._concept_matcher = ConceptValueMatcher()
        self._heuristic_matcher = HeuristicMatcher()

    def match(
        self,
        columns: list[ColumnProfile],
        targets: list[TargetProperty],
    ) -> tuple[list[MatchCandidate], list[str], list[str]]:
        """Run the three-phase matching pipeline.

        Returns:
            Tuple of (accepted matches, unmatched column names,
            unmatched target property names).
        """
        matches: list[MatchCandidate] = []
        remaining_cols = list(columns)
        remaining_targets = list(targets)

        # --- Phase 1: Concept-value matching ---
        _log.info(
            "Phase 1: Concept-value matching (%d cols x %d targets)",
            len(remaining_cols),
            len(remaining_targets),
        )
        phase1, remaining_cols, remaining_targets = self._run_concept_phase(
            remaining_cols,
            remaining_targets,
        )
        matches.extend(phase1)
        _log.info("Phase 1 resolved %d columns", len(phase1))

        # --- Phase 2: Heuristic name matching ---
        _log.info(
            "Phase 2: Heuristic matching (%d cols x %d targets)",
            len(remaining_cols),
            len(remaining_targets),
        )
        phase2, remaining_cols, remaining_targets = self._run_heuristic_phase(
            remaining_cols,
            remaining_targets,
        )
        matches.extend(phase2)
        _log.info("Phase 2 resolved %d columns", len(phase2))

        # --- Phase 3: LLM-assisted (optional) ---
        if self._use_llm and remaining_cols and remaining_targets:
            _log.info(
                "Phase 3: LLM matching (%d cols x %d targets)",
                len(remaining_cols),
                len(remaining_targets),
            )
            phase3, remaining_cols, remaining_targets = self._run_llm_phase(
                remaining_cols,
                remaining_targets,
            )
            matches.extend(phase3)
            _log.info("Phase 3 resolved %d columns", len(phase3))

        unmatched_cols = [c.name for c in remaining_cols]
        unmatched_targets = [t.name for t in remaining_targets]
        return matches, unmatched_cols, unmatched_targets

    def _run_concept_phase(
        self,
        columns: list[ColumnProfile],
        targets: list[TargetProperty],
    ) -> tuple[list[MatchCandidate], list[ColumnProfile], list[TargetProperty]]:
        """Phase 1: concept-value matching."""
        matches: list[MatchCandidate] = []
        resolved_col_names: set[str] = set()
        resolved_target_names: set[str] = set()

        concept_targets = [t for t in targets if t.concept_values]

        for col in columns:
            if not col.distinct_values:
                continue
            best: MatchCandidate | None = None
            for target in concept_targets:
                if target.name in resolved_target_names:
                    continue
                candidate = self._concept_matcher.match(col, target)
                if candidate and (best is None or candidate.confidence > best.confidence):
                    best = candidate
            if best is not None:
                matches.append(best)
                resolved_col_names.add(col.name)
                resolved_target_names.add(best.target_property)

        remaining_cols = [c for c in columns if c.name not in resolved_col_names]
        remaining_targets = [t for t in targets if t.name not in resolved_target_names]
        return matches, remaining_cols, remaining_targets

    def _run_heuristic_phase(
        self,
        columns: list[ColumnProfile],
        targets: list[TargetProperty],
    ) -> tuple[list[MatchCandidate], list[ColumnProfile], list[TargetProperty]]:
        """Phase 2: heuristic name matching."""
        matches: list[MatchCandidate] = []
        resolved_col_names: set[str] = set()
        resolved_target_names: set[str] = set()

        for col in columns:
            best: MatchCandidate | None = None
            for target in targets:
                if target.name in resolved_target_names:
                    continue
                candidate = self._heuristic_matcher.score(col, target)
                if candidate.confidence >= self._heuristic_threshold and (
                    best is None or candidate.confidence > best.confidence
                ):
                    best = candidate
            if best is not None:
                matches.append(best)
                resolved_col_names.add(col.name)
                resolved_target_names.add(best.target_property)

        remaining_cols = [c for c in columns if c.name not in resolved_col_names]
        remaining_targets = [t for t in targets if t.name not in resolved_target_names]
        return matches, remaining_cols, remaining_targets

    def _run_llm_phase(
        self,
        columns: list[ColumnProfile],
        targets: list[TargetProperty],
    ) -> tuple[list[MatchCandidate], list[ColumnProfile], list[TargetProperty]]:
        """Phase 3: LLM-assisted matching."""
        try:
            from ceds_jsonld.wizard.llm_matcher import LLMMatcher

            llm = LLMMatcher(backend=self._llm_backend, model=self._llm_model)
            return llm.match(columns, targets)
        except ImportError:
            _log.warning("LLM matching unavailable — install ceds-jsonld[sdg] for LLM support")
            return [], columns, targets
        except Exception:
            _log.warning("LLM matching failed; returning unresolved columns", exc_info=True)
            return [], columns, targets
