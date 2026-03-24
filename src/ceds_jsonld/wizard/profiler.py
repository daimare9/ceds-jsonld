"""Column profiler — analyze source data columns for mapping.

Reads source data (CSV, Excel, or list of dicts) and extracts per-column
metadata: sample values, inferred types, null rates, delimiter detection,
and cardinality analysis. This metadata drives the matching engine.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ColumnProfile:
    """Profile of a single source column for mapping analysis.

    Attributes:
        name: Original column name from the source data.
        normalized: Lowercased, separators stripped for fuzzy matching.
        sample_values: First N non-null values (strings).
        inferred_type: One of ``"string"``, ``"date"``, ``"integer"``, ``"float"``, ``"boolean"``.
        null_rate: Fraction of rows with null/empty values (0.0-1.0).
        unique_rate: Fraction of distinct values among non-null values (0.0-1.0).
        contains_delimiter: Detected delimiter (``"|"``, ``","``) if multi-value, else ``None``.
        value_pattern: Detected pattern string (e.g. ``"YYYY-MM-DD"``), or ``None``.
        distinct_values: Unique non-null values if cardinality <= threshold, else ``[]``.
    """

    name: str
    normalized: str
    sample_values: list[str] = field(default_factory=list)
    inferred_type: str = "string"
    null_rate: float = 0.0
    unique_rate: float = 0.0
    contains_delimiter: str | None = None
    value_pattern: str | None = None
    distinct_values: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_SEP_RE = re.compile(r"[\s_\-./]+")


def _normalize(name: str) -> str:
    """Normalize a column name for fuzzy matching."""
    return _SEP_RE.sub("", name).lower()


# ---------------------------------------------------------------------------
# Type inference patterns
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}$"
    r"|^\d{2}/\d{2}/\d{4}$"
    r"|^\d{2}-\d{2}-\d{4}$"
)
_BOOL_VALUES = frozenset({"true", "false", "yes", "no", "0", "1"})
_IEEE_SPECIAL = frozenset({"nan", "inf", "-inf", "infinity", "-infinity"})


def _is_ieee_special(value: str) -> bool:
    """Check if a string is an IEEE 754 special value (NaN, Infinity)."""
    return value.strip().lower() in _IEEE_SPECIAL


def _infer_type(values: list[str]) -> str:
    """Infer the column type from non-null string values."""
    if not values:
        return "string"

    date_count = sum(1 for v in values if _DATE_RE.match(v.strip()))
    if date_count / len(values) >= 0.8:
        return "date"

    try:
        for v in values:
            int(v.strip())
        return "integer"
    except (ValueError, TypeError):
        pass

    try:
        for v in values:
            float(v.strip())
        # If ALL values are IEEE 754 specials, classify as string
        if all(_is_ieee_special(v) for v in values):
            return "string"
        return "float"
    except (ValueError, TypeError):
        pass

    if all(v.strip().lower() in _BOOL_VALUES for v in values):
        return "boolean"

    return "string"


def _detect_delimiter(values: list[str], threshold: float = 0.1) -> str | None:
    """Detect multi-value delimiter in column values."""
    if not values:
        return None
    for delim in ("|", ","):
        count = sum(1 for v in values if delim in v)
        if count / len(values) > threshold:
            return delim
    return None


def _detect_date_pattern(values: list[str]) -> str | None:
    """Detect date format pattern if values are dates."""
    if not values:
        return None
    sample = values[0].strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", sample):
        return "YYYY-MM-DD"
    if re.match(r"^\d{2}/\d{2}/\d{4}$", sample):
        return "MM/DD/YYYY"
    if re.match(r"^\d{2}-\d{2}-\d{4}$", sample):
        return "MM-DD-YYYY"
    return None


class ColumnProfiler:
    """Analyze source data columns for the mapping wizard.

    Args:
        sample_size: Maximum number of rows to sample for profiling.
        distinct_threshold: Maximum distinct value count to store in
            ``distinct_values``. Columns with more distinct values get
            an empty list (high cardinality).
    """

    def __init__(
        self,
        sample_size: int = 100,
        distinct_threshold: int = 20,
    ) -> None:
        self._sample_size = sample_size
        self._distinct_threshold = distinct_threshold

    def profile_from_dicts(self, rows: list[dict[str, Any]]) -> list[ColumnProfile]:
        """Profile columns from a list of row dicts."""
        if not rows:
            return []

        sample = rows[: self._sample_size]
        columns = list(sample[0].keys())

        profiles: list[ColumnProfile] = []
        for col in columns:
            raw_values = [row.get(col) for row in sample]
            profiles.append(self._build_profile(col, raw_values))
        return profiles

    def profile_from_csv(self, path: str) -> list[ColumnProfile]:
        """Profile columns from a CSV file."""
        rows: list[dict[str, str]] = []
        with Path(path).open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i >= self._sample_size:
                    break
                rows.append(row)
        return self.profile_from_dicts(rows)

    def _build_profile(self, name: str, raw_values: list[Any]) -> ColumnProfile:
        """Build a ColumnProfile from raw column values."""
        total = len(raw_values)
        nulls = sum(1 for v in raw_values if v is None or (isinstance(v, str) and v.strip() == ""))
        null_rate = nulls / total if total > 0 else 0.0

        non_null = [str(v).strip() for v in raw_values if v is not None and str(v).strip() != ""]

        sample_values = non_null[: self._sample_size]

        distinct_set = sorted(set(non_null))
        unique_rate = len(distinct_set) / len(non_null) if non_null else 0.0

        if len(distinct_set) <= self._distinct_threshold:
            distinct_values = distinct_set
        else:
            distinct_values = []

        inferred_type = _infer_type(non_null)
        contains_delimiter = _detect_delimiter(non_null)
        value_pattern = _detect_date_pattern(non_null) if inferred_type == "date" else None

        return ColumnProfile(
            name=name,
            normalized=_normalize(name),
            sample_values=sample_values,
            inferred_type=inferred_type,
            null_rate=null_rate,
            unique_rate=unique_rate,
            contains_delimiter=contains_delimiter,
            value_pattern=value_pattern,
            distinct_values=distinct_values,
        )
