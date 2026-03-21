"""Heuristic matcher — Phase 2 of the three-phase matching pipeline.

Deterministic name-based and type-based matching using normalized name
comparison, fuzzy substring containment, and datatype compatibility.
Handles the cases where column names are recognizable variants of CEDS
property names.
"""

from __future__ import annotations

import re

from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.concept_matcher import MatchCandidate
from ceds_jsonld.wizard.profiler import ColumnProfile, _normalize

# Common education-data abbreviations that help fuzzy matching
_ABBREVIATIONS: dict[str, list[str]] = {
    "nm": ["name"],
    "fname": ["firstname"],
    "lname": ["lastname", "lastorsurname"],
    "mname": ["middlename"],
    "dob": ["birthdate", "dateofbirth"],
    "bdate": ["birthdate"],
    "birthdt": ["birthdate"],
    "ssn": ["personidentifier"],
    "gender": ["sex", "hassex"],
    "race": ["raceand", "hasraceand"],
    "eth": ["ethnicity", "raceand"],
    "id": ["identifier", "personidentifier"],
}

# XSD type compatibility matrix: inferred_type -> compatible XSD local names
_TYPE_COMPAT: dict[str, set[str]] = {
    "string": {"string", "token", "normalizedString"},
    "date": {"date", "dateTime"},
    "integer": {"integer", "int", "long", "nonNegativeInteger", "positiveInteger", "token", "string"},
    "float": {"float", "double", "decimal"},
    "boolean": {"boolean"},
}


class HeuristicMatcher:
    """Score column-to-property matches using deterministic heuristics.

    Scoring components:
    1. Exact name match (case-insensitive, normalized) -> +0.50
    2. Fuzzy substring containment -> +0.30
    3. Abbreviation match -> +0.25
    4. Datatype compatibility -> +0.20
    5. Value pattern match -> +0.15
    """

    def score(
        self,
        column: ColumnProfile,
        target: TargetProperty,
    ) -> MatchCandidate:
        """Score a column against a target property.

        Returns:
            MatchCandidate with computed confidence and reasons.
        """
        score = 0.0
        reasons: list[str] = []
        col_norm = column.normalized
        target_norm = _normalize(target.name)

        # 1. Exact normalized name match
        if col_norm == target_norm:
            score += 0.50
            reasons.append("exact_name_match")

        # 2. Fuzzy substring containment (either direction)
        elif len(col_norm) >= 3 and len(target_norm) >= 3:
            if col_norm in target_norm or target_norm in col_norm:
                score += 0.30
                reasons.append("fuzzy_substring_match")
            else:
                # Check if any word from column appears in the target
                col_words = re.split(r"[^a-z0-9]+", col_norm)
                for w in col_words:
                    if len(w) >= 3 and w in target_norm:
                        score += 0.20
                        reasons.append(f"word_overlap ({w})")
                        break

        # 3. Abbreviation expansion
        if not reasons:  # Only if no name match yet
            for abbr, expansions in _ABBREVIATIONS.items():
                if abbr in col_norm:
                    for exp in expansions:
                        if exp in target_norm:
                            score += 0.25
                            reasons.append(f"abbreviation_match ({abbr}\u2192{exp})")
                            break
                    if reasons:
                        break

        # 4. Datatype compatibility
        if target.datatype:
            xsd_local = target.datatype.rsplit("#", 1)[-1] if "#" in target.datatype else ""
            compatible = _TYPE_COMPAT.get(column.inferred_type, set())
            if xsd_local in compatible:
                score += 0.20
                reasons.append("type_compatible")

        # 5. Value pattern -> type match (e.g., date pattern -> date property)
        if column.value_pattern and target.datatype:
            xsd_local = target.datatype.rsplit("#", 1)[-1] if "#" in target.datatype else ""
            if "date" in column.inferred_type.lower() and xsd_local in ("date", "dateTime"):
                score += 0.15
                reasons.append("pattern_match")

        return MatchCandidate(
            source_column=column.name,
            target_property=target.name,
            target_shape=target.parent_shape,
            confidence=min(score, 1.0),
            reasons=reasons,
            strategy="heuristic",
            suggested_transform=self._suggest_transform(column, target),
        )

    def _suggest_transform(
        self,
        column: ColumnProfile,
        target: TargetProperty,
    ) -> str | None:
        """Suggest a transform based on column and target characteristics."""
        target_lower = target.name.lower()

        # Date transform
        if column.inferred_type == "date" and target.datatype:
            xsd = target.datatype.rsplit("#", 1)[-1] if "#" in target.datatype else ""
            if xsd in ("date", "dateTime"):
                return "date_format"

        # Integer to token/string (float artifact cleanup)
        if column.inferred_type == "integer" and target.datatype:
            xsd = target.datatype.rsplit("#", 1)[-1] if "#" in target.datatype else ""
            if xsd in ("token", "string"):
                return "int_clean"

        # Sex prefix
        if "sex" in target_lower:
            return "sex_prefix"

        # Race prefix
        if "race" in target_lower or "ethnicity" in target_lower:
            return "race_prefix"

        # Pipe-split detection
        if column.contains_delimiter == "|":
            return "first_pipe_split"

        return None
