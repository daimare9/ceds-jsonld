# AI-Assisted Mapping Wizard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an AI-assisted mapping wizard that reads CSV/Excel column headers and sample values, matches them to CEDS shape properties using a three-phase pipeline (concept-value → heuristic → LLM), and generates a complete annotated `_mapping.yaml` config.

**Architecture:** Three-phase matching pipeline. Phase 1 compares source column distinct values against CEDS concept-scheme enums (deterministic, <1ms). Phase 2 uses normalized name matching + datatype compatibility (deterministic, <1ms). Phase 3 sends unresolved columns to a local LLM with ontology context (30-75s). Results are assembled into annotated YAML matching the existing `_mapping.yaml` format with confidence scores and review markers.

**Tech Stack:** Python 3.14, rdflib (ontology queries), PyYAML (YAML output), Click (CLI), transformers+torch (LLM backend, optional via `[sdg]` extras), Ollama (auto-detected alternative). Reuses Phase 1 components: `ConceptSchemeResolver`, `OntologyMetadataExtractor`, `LLMValueGenerator`.

**Branch:** `feature/mapping-wizard` from `dev`

**Research:** `ResearchFiles/FEATURE1_AI_MAPPING_WIZARD_RESEARCH.md` (1400 lines, PoC-validated: 100% accuracy on 34 columns across 3 test CSVs)

---

## Existing Code Reference

- **`src/ceds_jsonld/introspector.py`** — `SHACLIntrospector` class with `PropertyInfo`/`NodeShapeInfo` dataclasses, `generate_mapping_template()`, `validate_mapping()`, `shape_tree()`, `all_shapes()`, `get_shape(local_name)`. Parses SHACL TTL into structured Python.
- **`src/ceds_jsonld/sdg/concept_resolver.py`** — `ConceptSchemeResolver` resolves `sh:in` and `schema:rangeIncludes` concept values. `PropertyMetadata` dataclass.
- **`src/ceds_jsonld/sdg/metadata_extractor.py`** — `OntologyMetadataExtractor` with `extract_prompt_metadata()`, `get_parent_class_label()`, `get_skos_notation()`.
- **`src/ceds_jsonld/sdg/llm_generator.py`** — `LLMValueGenerator` with Ollama+transformers backends. `DEFAULT_MODEL="Qwen/Qwen3-4B"`, `DEFAULT_OLLAMA_MODEL="qwen3:4b"`, `_parse_json_values()`.
- **`src/ceds_jsonld/transforms.py`** — `BUILTIN_TRANSFORMS` dict (`sex_prefix`, `race_prefix`, `first_pipe_split`, `int_clean`, `date_format`). `get_transform()` function.
- **`src/ceds_jsonld/cli.py`** — Click-based CLI with `@cli.group()`, existing commands: `convert`, `validate`, `introspect`, `generate-mapping`, `list-shapes`, `benchmark`.
- **`src/ceds_jsonld/registry.py`** — `ShapeRegistry` with `list_available()`, `load_shape()`, `add_search_dir()`. `ShapeDefinition` dataclass.
- **`src/ceds_jsonld/ontologies/person/person_mapping.yaml`** — Reference mapping YAML format: `shape`, `context_url`, `context_file`, `base_uri`, `id_source`, `id_transform`, `type`, `properties` → sub-shapes → `fields` with `source`/`target`/`transform`/`datatype`/`optional`/`cardinality`/`split_on`/`multi_value_split`.
- **`src/ceds_jsonld/__init__.py`** — Public API: all classes importable from top-level `ceds_jsonld`. Version: `0.11.0`.

---

## Task List

### Task 1: Create branch and wizard package skeleton

**Files:**
- Create: `src/ceds_jsonld/wizard/__init__.py`
- Create: `src/ceds_jsonld/wizard/profiler.py` (empty placeholder)
- Create: `src/ceds_jsonld/wizard/collector.py` (empty placeholder)
- Create: `src/ceds_jsonld/wizard/heuristic.py` (empty placeholder)
- Create: `src/ceds_jsonld/wizard/concept_matcher.py` (empty placeholder)
- Create: `src/ceds_jsonld/wizard/engine.py` (empty placeholder)
- Create: `src/ceds_jsonld/wizard/assembler.py` (empty placeholder)
- Create: `src/ceds_jsonld/wizard/llm_matcher.py` (empty placeholder)
- Create: `tests/test_wizard_profiler.py` (empty placeholder)

**Step 1: Create branch**

```powershell
git checkout dev
git pull origin dev
git checkout -b feature/mapping-wizard
```

**Step 2: Create package skeleton**

Create `src/ceds_jsonld/wizard/__init__.py`:
```python
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

__all__: list[str] = []
```

Create the other files as empty modules with a docstring only.

**Step 3: Commit**

```powershell
git add src/ceds_jsonld/wizard/
git commit -m "feat(wizard): add mapping wizard package skeleton"
```

---

### Task 2: `ColumnProfile` dataclass and `ColumnProfiler` class

**Files:**
- Create: `src/ceds_jsonld/wizard/profiler.py`
- Create: `tests/test_wizard_profiler.py`

**Step 1: Write the failing test**

```python
# tests/test_wizard_profiler.py
"""Tests for ColumnProfiler — source column analysis."""

from __future__ import annotations

import pytest

from ceds_jsonld.wizard.profiler import ColumnProfile, ColumnProfiler


class TestColumnProfile:
    """ColumnProfile dataclass basic tests."""

    def test_column_profile_fields(self) -> None:
        p = ColumnProfile(
            name="DOB",
            normalized="dob",
            sample_values=["1990-01-15", "1985-03-22"],
            inferred_type="date",
            null_rate=0.0,
            unique_rate=1.0,
            contains_delimiter=None,
            value_pattern="YYYY-MM-DD",
            distinct_values=["1990-01-15", "1985-03-22"],
        )
        assert p.name == "DOB"
        assert p.inferred_type == "date"


class TestColumnProfiler:
    """ColumnProfiler analysis tests."""

    def test_profile_from_dicts_basic(self) -> None:
        rows = [
            {"FirstName": "Jane", "Age": "25", "DOB": "1990-01-15"},
            {"FirstName": "John", "Age": "30", "DOB": "1985-03-22"},
            {"FirstName": "Alice", "Age": "28", "DOB": "1992-07-10"},
        ]
        profiler = ColumnProfiler(sample_size=10)
        profiles = profiler.profile_from_dicts(rows)

        assert len(profiles) == 3
        by_name = {p.name: p for p in profiles}
        assert "FirstName" in by_name
        assert "DOB" in by_name

    def test_type_inference_date(self) -> None:
        rows = [
            {"DOB": "1990-01-15"},
            {"DOB": "1985-03-22"},
            {"DOB": "1992-07-10"},
            {"DOB": "2000-12-01"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        dob = profiles[0]
        assert dob.inferred_type == "date"

    def test_type_inference_integer(self) -> None:
        rows = [{"Age": "25"}, {"Age": "30"}, {"Age": "28"}]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].inferred_type == "integer"

    def test_type_inference_float(self) -> None:
        rows = [{"GPA": "3.5"}, {"GPA": "2.8"}, {"GPA": "3.9"}]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].inferred_type == "float"

    def test_type_inference_boolean(self) -> None:
        rows = [{"Active": "true"}, {"Active": "false"}, {"Active": "true"}]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].inferred_type == "boolean"

    def test_null_rate(self) -> None:
        rows = [
            {"Name": "Jane"},
            {"Name": ""},
            {"Name": None},
            {"Name": "John"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].null_rate == pytest.approx(0.5)

    def test_delimiter_detection_pipe(self) -> None:
        rows = [
            {"IDs": "SSN|12345"},
            {"IDs": "DL|67890"},
            {"IDs": "SSN|11111"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].contains_delimiter == "|"

    def test_low_cardinality_distinct_values(self) -> None:
        rows = [
            {"Gender": "Male"},
            {"Gender": "Female"},
            {"Gender": "Male"},
            {"Gender": "Female"},
            {"Gender": "Male"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert set(profiles[0].distinct_values) == {"Male", "Female"}

    def test_high_cardinality_no_distinct(self) -> None:
        rows = [{"Name": f"Person_{i}"} for i in range(50)]
        profiler = ColumnProfiler(distinct_threshold=15)
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].distinct_values == []

    def test_unique_rate(self) -> None:
        rows = [
            {"ID": "A"},
            {"ID": "B"},
            {"ID": "C"},
            {"ID": "A"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].unique_rate == pytest.approx(0.75)

    def test_profile_from_csv(self, tmp_path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("Name,Age\nJane,25\nJohn,30\n", encoding="utf-8")
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_csv(str(csv_file))
        assert len(profiles) == 2
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_profiler.py -v --tb=short`
Expected: FAIL — `ImportError: cannot import name 'ColumnProfile'`

**Step 3: Write implementation**

```python
# src/ceds_jsonld/wizard/profiler.py
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
        inferred_type: One of "string", "date", "integer", "float", "boolean".
        null_rate: Fraction of rows with null/empty values (0.0–1.0).
        unique_rate: Fraction of distinct values among non-null values (0.0–1.0).
        contains_delimiter: Detected delimiter ("|", ",") if multi-value, else None.
        value_pattern: Detected pattern string (e.g. "YYYY-MM-DD"), or None.
        distinct_values: Unique non-null values if cardinality <= threshold, else [].
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
    """Normalize a column name for fuzzy matching.

    Lowercases, strips separators (whitespace, underscore, hyphen, dot, slash).
    """
    return _SEP_RE.sub("", name).lower()


# ---------------------------------------------------------------------------
# Type inference patterns
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}$"   # YYYY-MM-DD
    r"|^\d{2}/\d{2}/\d{4}$"  # MM/DD/YYYY
    r"|^\d{2}-\d{2}-\d{4}$"  # MM-DD-YYYY
)
_BOOL_VALUES = frozenset({"true", "false", "yes", "no", "0", "1"})


def _infer_type(values: list[str]) -> str:
    """Infer the column type from non-null string values.

    Rules (in order):
    - ≥80% match date regex → "date"
    - All values parse as int → "integer"
    - All values parse as float → "float"
    - All values in boolean set → "boolean"
    - Else → "string"
    """
    if not values:
        return "string"

    # Date check (≥80%)
    date_count = sum(1 for v in values if _DATE_RE.match(v.strip()))
    if date_count / len(values) >= 0.8:
        return "date"

    # Integer check
    try:
        for v in values:
            int(v.strip())
        return "integer"
    except (ValueError, TypeError):
        pass

    # Float check
    try:
        for v in values:
            float(v.strip())
        return "float"
    except (ValueError, TypeError):
        pass

    # Boolean check
    if all(v.strip().lower() in _BOOL_VALUES for v in values):
        return "boolean"

    return "string"


def _detect_delimiter(values: list[str], threshold: float = 0.1) -> str | None:
    """Detect multi-value delimiter in column values.

    Returns "|" or "," if more than threshold fraction of values contain it.
    Pipe takes precedence over comma.
    """
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
            ``distinct_values``. Columns with more distinct values get an
            empty list (high cardinality).
    """

    def __init__(
        self,
        sample_size: int = 100,
        distinct_threshold: int = 20,
    ) -> None:
        self._sample_size = sample_size
        self._distinct_threshold = distinct_threshold

    def profile_from_dicts(self, rows: list[dict[str, Any]]) -> list[ColumnProfile]:
        """Profile columns from a list of row dicts.

        Args:
            rows: List of dicts where keys are column names.

        Returns:
            List of ColumnProfile, one per column.
        """
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
        """Profile columns from a CSV file.

        Args:
            path: Path to the CSV file.

        Returns:
            List of ColumnProfile, one per column.
        """
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
        nulls = sum(
            1 for v in raw_values
            if v is None or (isinstance(v, str) and v.strip() == "")
        )
        null_rate = nulls / total if total > 0 else 0.0

        # Non-null string values
        non_null = [
            str(v).strip()
            for v in raw_values
            if v is not None and str(v).strip() != ""
        ]

        # Sample values (first N non-null)
        sample_values = non_null[: self._sample_size]

        # Distinct values
        distinct_set = sorted(set(non_null))
        unique_rate = len(distinct_set) / len(non_null) if non_null else 0.0

        if len(distinct_set) <= self._distinct_threshold:
            distinct_values = distinct_set
        else:
            distinct_values = []

        # Type inference
        inferred_type = _infer_type(non_null)

        # Delimiter detection
        contains_delimiter = _detect_delimiter(non_null)

        # Date pattern
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
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_profiler.py -v --tb=short`
Expected: PASS — all tests green

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/wizard/profiler.py tests/test_wizard_profiler.py
git commit -m "feat(wizard): add ColumnProfiler with type inference and profiling"
```

---

### Task 3: `TargetProperty` dataclass and `ShapeMetadataCollector`

**Files:**
- Create: `src/ceds_jsonld/wizard/collector.py`
- Create: `tests/test_wizard_collector.py`

**Step 1: Write the failing test**

```python
# tests/test_wizard_collector.py
"""Tests for ShapeMetadataCollector — target property aggregation."""

from __future__ import annotations

import pytest

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

        # PersonShape has known properties
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

        # hasSex should have concept scheme values
        sex_props = [t for t in targets if t.name == "hasSex"]
        assert len(sex_props) == 1
        assert len(sex_props[0].concept_values) > 0

    def test_available_transforms_populated(self) -> None:
        from ceds_jsonld.registry import ShapeRegistry

        registry = ShapeRegistry()
        shape_def = registry.load_shape("person")

        collector = ShapeMetadataCollector(shape_def)
        targets = collector.collect()

        # All targets should list available transforms
        for t in targets:
            assert isinstance(t.available_transforms, list)

    def test_parent_shape_assigned(self) -> None:
        from ceds_jsonld.registry import ShapeRegistry

        registry = ShapeRegistry()
        shape_def = registry.load_shape("person")

        collector = ShapeMetadataCollector(shape_def)
        targets = collector.collect()

        # FirstName belongs to PersonName sub-shape
        first = [t for t in targets if t.name == "FirstName"][0]
        assert "PersonName" in first.parent_shape or "Name" in first.parent_shape
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_collector.py -v --tb=short`
Expected: FAIL — `ImportError: cannot import name 'ShapeMetadataCollector'`

**Step 3: Write implementation**

```python
# src/ceds_jsonld/wizard/collector.py
"""Shape metadata collector — aggregate target property info for matching.

Combines data from SHACLIntrospector, ConceptSchemeResolver, and
OntologyMetadataExtractor to build a flat list of TargetProperty objects
that the matching engine scores against source columns.
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
        name: Human-readable property name (e.g. "FirstName").
        path: CEDS IRI path (e.g. "ceds:P000115").
        parent_shape: Sub-shape name (e.g. "PersonName").
        datatype: XSD type IRI if literal, None if object property.
        label: rdfs:label from ontology, or empty string.
        description: dc:description from ontology, or empty string.
        is_required: True if sh:minCount > 0.
        concept_values: List of skos:notation strings for concept schemes.
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

    Aggregates information from the SHACL introspector, concept scheme
    resolver, and ontology metadata extractor into a flat list of
    TargetProperty objects.

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

        # Build context lookup for property names
        context_lookup = self._load_context_lookup()

        targets: list[TargetProperty] = []
        self._walk_shape(tree, targets, context_lookup)
        return targets

    def _walk_shape(
        self,
        shape: NodeShapeInfo,
        targets: list[TargetProperty],
        context_lookup: dict[str, str] | None,
        parent_name: str = "",
    ) -> None:
        """Recursively walk the shape tree and extract leaf properties."""
        shape_name = parent_name or shape.local_name

        for prop in shape.properties:
            # If this property has a nested sub-shape, recurse
            if prop.name in shape.children or prop.node_shape:
                child = shape.children.get(prop.name)
                if child is not None:
                    self._walk_shape(child, targets, context_lookup, shape_name=child.local_name)
                continue

            # Leaf property — build TargetProperty
            name = prop.name or prop.path_local
            concept_values = self._resolve_concept_values(prop)

            targets.append(
                TargetProperty(
                    name=name,
                    path=prop.path,
                    parent_shape=shape_name,
                    datatype=prop.datatype,
                    label=name,  # Will be enriched if ontology metadata available
                    description="",
                    is_required=bool(prop.min_count and prop.min_count > 0),
                    concept_values=concept_values,
                    available_transforms=sorted(BUILTIN_TRANSFORMS.keys()),
                )
            )

    def _resolve_concept_values(self, prop: PropertyInfo) -> list[str]:
        """Resolve concept scheme values for a property."""
        if not prop.allowed_values and not self._concept_resolver:
            return []

        if prop.allowed_values and self._concept_resolver:
            try:
                values = self._concept_resolver.resolve_property_values(
                    property_iri=prop.path,
                    allowed_value_iris=prop.allowed_values,
                )
                return values
            except Exception:
                _log.debug("Failed to resolve concept values for %s", prop.path)

        # If sh:in IRIs exist but resolver couldn't resolve, return raw local names
        if prop.allowed_values:
            return [v.rsplit("/", 1)[-1].rsplit("#", 1)[-1] for v in prop.allowed_values]

        return []

    def _build_concept_resolver(self, shape_def: ShapeDefinition) -> Any:
        """Build a ConceptSchemeResolver if ontology files are available."""
        try:
            from ceds_jsonld.sdg.concept_resolver import ConceptSchemeResolver

            ontology_dir = Path(shape_def.shacl_path).parent.parent / "base"
            if not ontology_dir.exists():
                return None

            # Find extension files
            shape_dir = Path(shape_def.shacl_path).parent
            extension_files = list(shape_dir.glob("*_Extension_Ontology.ttl"))

            return ConceptSchemeResolver(
                ontology_dir=ontology_dir,
                extension_files=extension_files if extension_files else None,
            )
        except Exception:
            _log.debug("ConceptSchemeResolver not available; concept values will be empty")
            return None

    def _load_context_lookup(self) -> dict[str, str] | None:
        """Load JSON-LD context file for IRI→name mapping."""
        import json

        context_path = self._shape_def.context_path
        if context_path is None or not Path(context_path).exists():
            return None

        try:
            ctx_data = json.loads(Path(context_path).read_text(encoding="utf-8"))
            if isinstance(ctx_data, dict) and "@context" in ctx_data:
                ctx = ctx_data["@context"]
                if isinstance(ctx, dict):
                    return ctx
        except Exception:
            pass
        return None
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_collector.py -v --tb=short`
Expected: PASS — all tests green

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/wizard/collector.py tests/test_wizard_collector.py
git commit -m "feat(wizard): add ShapeMetadataCollector with concept value resolution"
```

---

### Task 4: `ConceptValueMatcher` — Phase 1 of matching pipeline

**Files:**
- Create: `src/ceds_jsonld/wizard/concept_matcher.py`
- Create: `tests/test_wizard_concept_matcher.py`

**Step 1: Write the failing test**

```python
# tests/test_wizard_concept_matcher.py
"""Tests for ConceptValueMatcher — deterministic concept-value matching."""

from __future__ import annotations

import pytest

from ceds_jsonld.wizard.concept_matcher import ConceptValueMatcher, MatchCandidate
from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.profiler import ColumnProfile


def _make_profile(name: str, distinct: list[str], **kw) -> ColumnProfile:
    """Helper to build a ColumnProfile."""
    return ColumnProfile(
        name=name,
        normalized=name.lower(),
        sample_values=distinct[:10],
        distinct_values=distinct,
        **kw,
    )


def _make_target(name: str, parent: str, concept_values: list[str], **kw) -> TargetProperty:
    """Helper to build a TargetProperty."""
    return TargetProperty(
        name=name,
        path=f"ceds:{name}",
        parent_shape=parent,
        concept_values=concept_values,
        **kw,
    )


class TestConceptValueMatcher:
    """ConceptValueMatcher scoring tests."""

    def test_direct_match(self) -> None:
        col = _make_profile("GENDER", ["Male", "Female"])
        target = _make_target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is not None
        assert result.confidence >= 0.9
        assert "direct" in result.strategy

    def test_prefixed_match(self) -> None:
        col = _make_profile("Type", ["PersonIdentifierType_PersonIdentifier", "PersonIdentifierType_StaffMemberIdentifier"])
        target = _make_target("hasPersonIdentifierType", "PersonIdentification", ["PersonIdentifier", "StaffMemberIdentifier"])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is not None
        assert result.confidence >= 0.9

    def test_abbreviation_match(self) -> None:
        col = _make_profile("Sex", ["M", "F"])
        target = _make_target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is not None
        assert result.confidence >= 0.7

    def test_no_match(self) -> None:
        col = _make_profile("FirstName", ["Jane", "John", "Alice"])
        target = _make_target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is None

    def test_empty_distinct_values_no_match(self) -> None:
        col = _make_profile("Name", [], inferred_type="string")
        target = _make_target("hasSex", "PersonSexGender", ["Male", "Female"])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is None

    def test_empty_concept_values_no_match(self) -> None:
        col = _make_profile("Gender", ["Male", "Female"])
        target = _make_target("FirstName", "PersonName", [])

        matcher = ConceptValueMatcher()
        result = matcher.match(col, target)

        assert result is None

    def test_match_candidate_fields(self) -> None:
        c = MatchCandidate(
            source_column="GENDER",
            target_property="hasSex",
            target_shape="PersonSexGender",
            confidence=0.95,
            reasons=["concept_direct_match"],
            strategy="concept_direct",
            suggested_transform=None,
        )
        assert c.source_column == "GENDER"
        assert c.target_property == "hasSex"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_concept_matcher.py -v --tb=short`
Expected: FAIL — `ImportError: cannot import name 'ConceptValueMatcher'`

**Step 3: Write implementation**

```python
# src/ceds_jsonld/wizard/concept_matcher.py
"""Concept-value matcher — Phase 1 of the three-phase matching pipeline.

Compares source column distinct values against CEDS concept scheme enumerations.
Three overlap strategies: direct match, CEDS-prefixed match, abbreviation-prefix.

This is the highest-ROI phase: resolves ~40% of columns in <1ms with zero
LLM cost and 1.00 confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.profiler import ColumnProfile


@dataclass
class MatchCandidate:
    """A scored column→property match candidate.

    Attributes:
        source_column: Original column name from source data.
        target_property: Matched target property name.
        target_shape: Parent sub-shape name.
        confidence: Match confidence 0.0–1.0.
        reasons: List of reason strings explaining the score.
        strategy: Matching strategy that produced this candidate.
        suggested_transform: Transform function name, or None.
    """

    source_column: str
    target_property: str
    target_shape: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    strategy: str = ""
    suggested_transform: str | None = None


# Threshold: fraction of column distinct values that must match a concept scheme
_OVERLAP_THRESHOLD = 0.7


class ConceptValueMatcher:
    """Match columns to concept-scheme properties by value overlap.

    Three strategies (tried in order of precision):
    1. **direct** — source value == concept value (case-insensitive)
    2. **prefixed** — source value == Prefix_ConceptValue (CEDS naming)
    3. **abbreviation** — source value is a case-insensitive prefix of a concept value
    """

    def match(
        self,
        column: ColumnProfile,
        target: TargetProperty,
    ) -> MatchCandidate | None:
        """Score a column against a concept-scheme target property.

        Args:
            column: Profiled source column.
            target: Target property with concept scheme values.

        Returns:
            MatchCandidate if overlap >= threshold, else None.
        """
        if not column.distinct_values or not target.concept_values:
            return None

        src_values = [v.strip().lower() for v in column.distinct_values]
        concept_lower = [v.lower() for v in target.concept_values]

        # Strategy 1: Direct match
        overlap = self._direct_overlap(src_values, concept_lower)
        if overlap >= _OVERLAP_THRESHOLD:
            return MatchCandidate(
                source_column=column.name,
                target_property=target.name,
                target_shape=target.parent_shape,
                confidence=min(overlap, 1.0),
                reasons=[f"concept_direct_match ({overlap:.0%} overlap)"],
                strategy="concept_direct",
                suggested_transform=self._suggest_transform(target),
            )

        # Strategy 2: Prefixed match (e.g. "PersonIdentifierType_PersonIdentifier")
        overlap = self._prefixed_overlap(src_values, concept_lower)
        if overlap >= _OVERLAP_THRESHOLD:
            return MatchCandidate(
                source_column=column.name,
                target_property=target.name,
                target_shape=target.parent_shape,
                confidence=min(overlap, 1.0),
                reasons=[f"concept_prefixed_match ({overlap:.0%} overlap)"],
                strategy="concept_prefixed",
                suggested_transform=self._suggest_transform(target),
            )

        # Strategy 3: Abbreviation match (e.g. "M" → "Male")
        overlap = self._abbreviation_overlap(src_values, concept_lower)
        if overlap >= _OVERLAP_THRESHOLD:
            return MatchCandidate(
                source_column=column.name,
                target_property=target.name,
                target_shape=target.parent_shape,
                confidence=min(overlap * 0.9, 1.0),  # Slightly lower confidence
                reasons=[f"concept_abbreviation_match ({overlap:.0%} overlap)"],
                strategy="concept_abbreviation",
                suggested_transform=self._suggest_transform(target),
            )

        return None

    def _direct_overlap(self, src: list[str], concepts: list[str]) -> float:
        """Fraction of source values that exactly match a concept value."""
        if not src:
            return 0.0
        concept_set = set(concepts)
        matches = sum(1 for v in src if v in concept_set)
        return matches / len(src)

    def _prefixed_overlap(self, src: list[str], concepts: list[str]) -> float:
        """Fraction of source values that match Prefix_ConceptValue pattern."""
        if not src:
            return 0.0
        concept_set = set(concepts)
        matches = 0
        for v in src:
            # Extract the part after the last underscore-separated prefix
            parts = v.rsplit("_", 1)
            if len(parts) == 2 and parts[1] in concept_set:
                matches += 1
        return matches / len(src)

    def _abbreviation_overlap(self, src: list[str], concepts: list[str]) -> float:
        """Fraction of source values that are prefixes of concept values."""
        if not src:
            return 0.0
        matches = 0
        for v in src:
            if not v:
                continue
            for c in concepts:
                if c.startswith(v) and len(v) >= 1:
                    matches += 1
                    break
        return matches / len(src)

    def _suggest_transform(self, target: TargetProperty) -> str | None:
        """Suggest a transform based on the target property name."""
        name_lower = target.name.lower()
        if "sex" in name_lower:
            return "sex_prefix"
        if "race" in name_lower or "ethnicity" in name_lower:
            return "race_prefix"
        return None
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_concept_matcher.py -v --tb=short`
Expected: PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/wizard/concept_matcher.py tests/test_wizard_concept_matcher.py
git commit -m "feat(wizard): add ConceptValueMatcher with 3-strategy value overlap"
```

---

### Task 5: `HeuristicMatcher` — Phase 2 of matching pipeline

**Files:**
- Create: `src/ceds_jsonld/wizard/heuristic.py`
- Create: `tests/test_wizard_heuristic.py`

**Step 1: Write the failing test**

```python
# tests/test_wizard_heuristic.py
"""Tests for HeuristicMatcher — deterministic name+type matching."""

from __future__ import annotations

import pytest

from ceds_jsonld.wizard.heuristic import HeuristicMatcher
from ceds_jsonld.wizard.concept_matcher import MatchCandidate
from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.profiler import ColumnProfile


def _col(name: str, inferred_type: str = "string", **kw) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        normalized=name.lower().replace("_", "").replace(" ", "").replace("-", ""),
        inferred_type=inferred_type,
        **kw,
    )


def _target(name: str, datatype: str | None = None, **kw) -> TargetProperty:
    dt = f"http://www.w3.org/2001/XMLSchema#{datatype}" if datatype else None
    return TargetProperty(
        name=name,
        path=f"ceds:{name}",
        parent_shape="TestShape",
        datatype=dt,
        **kw,
    )


class TestHeuristicMatcher:

    def test_exact_name_match(self) -> None:
        col = _col("FirstName")
        target = _target("FirstName", "string")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.confidence >= 0.6
        assert "exact_name_match" in result.reasons

    def test_normalized_name_match(self) -> None:
        col = _col("first_name")
        target = _target("FirstName", "string")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.confidence >= 0.4
        assert "exact_name_match" in result.reasons

    def test_fuzzy_substring_match(self) -> None:
        col = _col("LAST_NM")  # normalized: "lastnm"
        target = _target("LastOrSurname", "string")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        # "last" substring should match
        assert result.confidence > 0.0

    def test_type_compatible_boost(self) -> None:
        col = _col("DOB", inferred_type="date")
        target = _target("Birthdate", "date")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert any("type_compatible" in r for r in result.reasons)

    def test_type_incompatible_no_boost(self) -> None:
        col = _col("Name", inferred_type="string")
        target = _target("Birthdate", "date")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert all("type_compatible" not in r for r in result.reasons)

    def test_zero_score_unrelated(self) -> None:
        col = _col("XYZ_UNKNOWN")
        target = _target("FirstName", "string")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.confidence < 0.3

    def test_date_transform_suggestion(self) -> None:
        col = _col("DOB", inferred_type="date", value_pattern="YYYY-MM-DD")
        target = _target("Birthdate", "date")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.suggested_transform == "date_format"

    def test_integer_transform_suggestion(self) -> None:
        col = _col("SSN", inferred_type="integer")
        target = _target("PersonIdentifier", "token")
        matcher = HeuristicMatcher()
        result = matcher.score(col, target)
        assert result.suggested_transform == "int_clean"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_heuristic.py -v --tb=short`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/ceds_jsonld/wizard/heuristic.py
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

# XSD type compatibility matrix: inferred_type → compatible XSD local names
_TYPE_COMPAT: dict[str, set[str]] = {
    "string": {"string", "token", "normalizedString"},
    "date": {"date", "dateTime"},
    "integer": {"integer", "int", "long", "nonNegativeInteger", "positiveInteger", "token", "string"},
    "float": {"float", "double", "decimal"},
    "boolean": {"boolean"},
}


class HeuristicMatcher:
    """Score column→property matches using deterministic heuristics.

    Scoring components:
    1. Exact name match (case-insensitive, normalized) → +0.50
    2. Fuzzy substring containment → +0.30
    3. Abbreviation match → +0.25
    4. Datatype compatibility → +0.20
    5. Value pattern match → +0.15
    """

    def score(
        self,
        column: ColumnProfile,
        target: TargetProperty,
    ) -> MatchCandidate:
        """Score a column against a target property.

        Args:
            column: Profiled source column.
            target: Target CEDS property.

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
                            reasons.append(f"abbreviation_match ({abbr}→{exp})")
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

        # 5. Value pattern → type match (e.g., date pattern → date property)
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
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_heuristic.py -v --tb=short`
Expected: PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/wizard/heuristic.py tests/test_wizard_heuristic.py
git commit -m "feat(wizard): add HeuristicMatcher with name/type/abbreviation scoring"
```

---

### Task 6: `MatchingEngine` — three-phase orchestrator

**Files:**
- Create: `src/ceds_jsonld/wizard/engine.py`
- Create: `tests/test_wizard_engine.py`

**Step 1: Write the failing test**

```python
# tests/test_wizard_engine.py
"""Tests for MatchingEngine — three-phase matching orchestrator."""

from __future__ import annotations

import pytest

from ceds_jsonld.wizard.engine import MatchingEngine
from ceds_jsonld.wizard.concept_matcher import MatchCandidate
from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.profiler import ColumnProfile


def _col(name: str, distinct: list[str] | None = None, inferred_type: str = "string", **kw) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        normalized=name.lower().replace("_", "").replace(" ", "").replace("-", ""),
        inferred_type=inferred_type,
        distinct_values=distinct or [],
        sample_values=distinct[:5] if distinct else [],
        **kw,
    )


def _target(
    name: str, parent: str, concept_values: list[str] | None = None, datatype: str | None = None,
) -> TargetProperty:
    dt = f"http://www.w3.org/2001/XMLSchema#{datatype}" if datatype else None
    return TargetProperty(
        name=name,
        path=f"ceds:{name}",
        parent_shape=parent,
        concept_values=concept_values or [],
        datatype=dt,
    )


class TestMatchingEngine:

    def test_concept_phase_resolves_first(self) -> None:
        columns = [_col("GENDER", ["Male", "Female"])]
        targets = [
            _target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"]),
            _target("FirstName", "PersonName", datatype="string"),
        ]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert len(matches) == 1
        assert matches[0].target_property == "hasSex"
        assert matches[0].strategy.startswith("concept")

    def test_heuristic_phase_for_name_match(self) -> None:
        columns = [_col("FirstName", inferred_type="string")]
        targets = [
            _target("FirstName", "PersonName", datatype="string"),
            _target("Birthdate", "PersonBirth", datatype="date"),
        ]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert len(matches) == 1
        assert matches[0].target_property == "FirstName"
        assert matches[0].strategy == "heuristic"

    def test_unmatched_columns_returned(self) -> None:
        columns = [_col("XYZ_UNKNOWN_COL")]
        targets = [_target("FirstName", "PersonName", datatype="string")]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert len(matches) == 0
        assert "XYZ_UNKNOWN_COL" in unmatched_cols

    def test_unmatched_targets_returned(self) -> None:
        columns = [_col("FirstName")]
        targets = [
            _target("FirstName", "PersonName", datatype="string"),
            _target("Birthdate", "PersonBirth", datatype="date"),
        ]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert "Birthdate" in unmatched_targets

    def test_multi_column_matching(self) -> None:
        columns = [
            _col("FirstName"),
            _col("GENDER", ["Male", "Female"]),
            _col("DOB", inferred_type="date", value_pattern="YYYY-MM-DD"),
        ]
        targets = [
            _target("FirstName", "PersonName", datatype="string"),
            _target("hasSex", "PersonSexGender", ["Male", "Female", "NotSelected"]),
            _target("Birthdate", "PersonBirth", datatype="date"),
        ]
        engine = MatchingEngine(use_llm=False)
        matches, unmatched_cols, unmatched_targets = engine.match(columns, targets)

        assert len(matches) == 3
        assert len(unmatched_cols) == 0
        assert len(unmatched_targets) == 0

    def test_confidence_threshold(self) -> None:
        columns = [_col("X")]  # Very short name, weak match
        targets = [_target("FirstName", "PersonName", datatype="string")]
        engine = MatchingEngine(use_llm=False, heuristic_threshold=0.5)
        matches, unmatched_cols, _ = engine.match(columns, targets)

        assert len(matches) == 0
        assert "X" in unmatched_cols
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_engine.py -v --tb=short`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/ceds_jsonld/wizard/engine.py
"""Matching engine — three-phase orchestrator for column→property matching.

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
        llm_backend: LLM backend name ("transformers" or "ollama"), or None for auto.
        llm_model: Model name override, or None for default.
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

        Args:
            columns: Profiled source columns.
            targets: Target properties from the shape.

        Returns:
            Tuple of:
            - List of accepted MatchCandidates.
            - List of unmatched column names.
            - List of unmatched target property names.
        """
        matches: list[MatchCandidate] = []
        remaining_cols = list(columns)
        remaining_targets = list(targets)

        # --- Phase 1: Concept-value matching ---
        _log.info("Phase 1: Concept-value matching (%d cols × %d targets)", len(remaining_cols), len(remaining_targets))
        phase1_matches, remaining_cols, remaining_targets = self._run_concept_phase(remaining_cols, remaining_targets)
        matches.extend(phase1_matches)
        _log.info("Phase 1 resolved %d columns", len(phase1_matches))

        # --- Phase 2: Heuristic name matching ---
        _log.info("Phase 2: Heuristic matching (%d cols × %d targets)", len(remaining_cols), len(remaining_targets))
        phase2_matches, remaining_cols, remaining_targets = self._run_heuristic_phase(remaining_cols, remaining_targets)
        matches.extend(phase2_matches)
        _log.info("Phase 2 resolved %d columns", len(phase2_matches))

        # --- Phase 3: LLM-assisted (optional) ---
        if self._use_llm and remaining_cols and remaining_targets:
            _log.info("Phase 3: LLM matching (%d cols × %d targets)", len(remaining_cols), len(remaining_targets))
            phase3_matches, remaining_cols, remaining_targets = self._run_llm_phase(remaining_cols, remaining_targets)
            matches.extend(phase3_matches)
            _log.info("Phase 3 resolved %d columns", len(phase3_matches))

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

        # Only consider targets with concept values
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
                if candidate.confidence >= self._heuristic_threshold:
                    if best is None or candidate.confidence > best.confidence:
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
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_engine.py -v --tb=short`
Expected: PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/wizard/engine.py tests/test_wizard_engine.py
git commit -m "feat(wizard): add MatchingEngine three-phase orchestrator"
```

---

### Task 7: `MappingAssembler` and `WizardResult`

**Files:**
- Create: `src/ceds_jsonld/wizard/assembler.py`
- Create: `tests/test_wizard_assembler.py`

**Step 1: Write the failing test**

```python
# tests/test_wizard_assembler.py
"""Tests for MappingAssembler — YAML config assembly from matches."""

from __future__ import annotations

import yaml
import pytest

from ceds_jsonld.wizard.assembler import MappingAssembler, WizardResult
from ceds_jsonld.wizard.concept_matcher import MatchCandidate


class TestWizardResult:

    def test_wizard_result_fields(self) -> None:
        r = WizardResult(
            mapping_config={"shape": "PersonShape"},
            confidence_report=[],
            unmapped_columns=[],
            unmapped_properties=["GenerationCodeOrSuffix"],
            yaml_text="shape: PersonShape\n",
        )
        assert r.mapping_config["shape"] == "PersonShape"
        assert "GenerationCodeOrSuffix" in r.unmapped_properties

    def test_save(self, tmp_path) -> None:
        r = WizardResult(
            mapping_config={"shape": "PersonShape"},
            confidence_report=[],
            unmapped_columns=[],
            unmapped_properties=[],
            yaml_text="shape: PersonShape\n",
        )
        out = tmp_path / "test.yaml"
        r.save(str(out))
        assert out.read_text(encoding="utf-8") == "shape: PersonShape\n"


class TestMappingAssembler:

    def test_assemble_basic(self) -> None:
        matches = [
            MatchCandidate(
                source_column="FIRST_NM",
                target_property="FirstName",
                target_shape="PersonName",
                confidence=0.95,
                reasons=["exact_name_match"],
                strategy="heuristic",
            ),
        ]
        assembler = MappingAssembler(
            shape_name="PersonShape",
            context_url="https://example.com/context.json",
            base_uri="cepi:person/",
        )
        result = assembler.assemble(
            matches=matches,
            unmapped_columns=[],
            unmapped_properties=["Birthdate"],
        )

        assert isinstance(result, WizardResult)
        assert result.mapping_config["shape"] == "PersonShape"
        assert "Birthdate" in result.unmapped_properties

    def test_yaml_text_parseable(self) -> None:
        matches = [
            MatchCandidate(
                source_column="FIRST_NM",
                target_property="FirstName",
                target_shape="PersonName",
                confidence=0.95,
                reasons=["heuristic"],
                strategy="heuristic",
            ),
            MatchCandidate(
                source_column="DOB",
                target_property="Birthdate",
                target_shape="PersonBirth",
                confidence=0.98,
                reasons=["heuristic"],
                strategy="heuristic",
                suggested_transform="date_format",
            ),
        ]
        assembler = MappingAssembler(
            shape_name="PersonShape",
            context_url="",
            base_uri="",
        )
        result = assembler.assemble(matches=matches, unmapped_columns=[], unmapped_properties=[])

        # Should be valid YAML
        parsed = yaml.safe_load(result.yaml_text)
        assert parsed is not None
        assert parsed["shape"] == "PersonShape"

    def test_transform_included(self) -> None:
        matches = [
            MatchCandidate(
                source_column="GENDER",
                target_property="hasSex",
                target_shape="PersonSexGender",
                confidence=0.95,
                strategy="concept",
                suggested_transform="sex_prefix",
            ),
        ]
        assembler = MappingAssembler(shape_name="PersonShape", context_url="", base_uri="")
        result = assembler.assemble(matches=matches, unmapped_columns=[], unmapped_properties=[])

        # Find the field in the config
        config = result.mapping_config
        found = False
        for prop_data in config.get("properties", {}).values():
            if isinstance(prop_data, dict):
                for field_data in prop_data.get("fields", {}).values():
                    if isinstance(field_data, dict) and field_data.get("source") == "GENDER":
                        assert field_data.get("transform") == "sex_prefix"
                        found = True
        assert found
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_assembler.py -v --tb=short`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/ceds_jsonld/wizard/assembler.py
"""Mapping assembler — build YAML config from match results.

Takes scored MatchCandidates and assembles a complete mapping YAML
that follows the same structure as ``person_mapping.yaml``, with
confidence annotations as YAML comments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ceds_jsonld.wizard.concept_matcher import MatchCandidate


@dataclass
class WizardResult:
    """Result of a mapping wizard run.

    Attributes:
        mapping_config: The complete YAML-ready mapping dict.
        confidence_report: Per-column match details.
        unmapped_columns: Source columns with no match.
        unmapped_properties: Target properties with no source mapping.
        yaml_text: Pre-formatted YAML string with confidence comments.
    """

    mapping_config: dict[str, Any]
    confidence_report: list[MatchCandidate]
    unmapped_columns: list[str]
    unmapped_properties: list[str]
    yaml_text: str = ""

    def save(self, path: str) -> None:
        """Write the YAML text to a file.

        Args:
            path: Output file path.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.yaml_text, encoding="utf-8")


# Confidence tiers for YAML annotation
_TIER_AUTO = 0.90    # ✓ auto-accept
_TIER_REVIEW = 0.70  # ? review suggested
_TIER_LOW = 0.50     # ✗ low confidence


def _confidence_marker(conf: float) -> str:
    """Return a confidence marker string for YAML comments."""
    if conf >= _TIER_AUTO:
        return f"# ✓ {conf:.2f}"
    if conf >= _TIER_REVIEW:
        return f"# ? {conf:.2f} — REVIEW"
    return f"# ✗ {conf:.2f} — LOW CONFIDENCE"


class MappingAssembler:
    """Assemble match results into a valid mapping YAML config.

    Args:
        shape_name: Shape name (e.g. "PersonShape").
        context_url: JSON-LD @context URL.
        base_uri: Base URI prefix for @id values.
    """

    def __init__(
        self,
        shape_name: str,
        context_url: str = "",
        base_uri: str = "",
    ) -> None:
        self._shape_name = shape_name
        self._context_url = context_url
        self._base_uri = base_uri

    def assemble(
        self,
        matches: list[MatchCandidate],
        unmapped_columns: list[str],
        unmapped_properties: list[str],
    ) -> WizardResult:
        """Build a mapping config from match candidates.

        Groups matches by target_shape into the nested properties structure
        expected by FieldMapper.

        Args:
            matches: Accepted match candidates.
            unmapped_columns: Columns with no match.
            unmapped_properties: Target properties with no source.

        Returns:
            WizardResult with config, YAML text, and reports.
        """
        # Group matches by target sub-shape
        by_shape: dict[str, list[MatchCandidate]] = {}
        for m in matches:
            by_shape.setdefault(m.target_shape, []).append(m)

        # Build the mapping config dict
        properties: dict[str, Any] = {}
        for shape_name, shape_matches in by_shape.items():
            prop_key = self._shape_to_property_key(shape_name)
            fields: dict[str, Any] = {}
            for m in shape_matches:
                field_entry: dict[str, Any] = {
                    "source": m.source_column,
                    "target": m.target_property,
                }
                if m.suggested_transform:
                    field_entry["transform"] = m.suggested_transform
                fields[m.target_property] = field_entry

            properties[prop_key] = {
                "type": shape_name,
                "cardinality": "single",
                "fields": fields,
            }

        config: dict[str, Any] = {
            "shape": self._shape_name,
            "context_url": self._context_url,
            "base_uri": self._base_uri,
            "type": self._shape_name.replace("Shape", ""),
            "properties": properties,
        }

        # Build annotated YAML text
        yaml_text = self._build_annotated_yaml(config, matches, unmapped_columns, unmapped_properties)

        return WizardResult(
            mapping_config=config,
            confidence_report=matches,
            unmapped_columns=unmapped_columns,
            unmapped_properties=unmapped_properties,
            yaml_text=yaml_text,
        )

    def _shape_to_property_key(self, shape_name: str) -> str:
        """Convert a sub-shape name to its property key.

        E.g. "PersonName" → "hasPersonName", "PersonBirth" → "hasPersonBirth".
        """
        if shape_name.startswith("has"):
            return shape_name
        return f"has{shape_name}"

    def _build_annotated_yaml(
        self,
        config: dict[str, Any],
        matches: list[MatchCandidate],
        unmapped_columns: list[str],
        unmapped_properties: list[str],
    ) -> str:
        """Build YAML text with confidence annotations as comments."""
        # Header comment
        lines: list[str] = [
            f"# Generated by ceds-jsonld mapping wizard",
            f"# Shape: {self._shape_name}",
            "#",
            "# Confidence Legend:",
            "#   ✓ = auto-accepted (≥0.90)",
            "#   ? = review suggested (0.70-0.89)",
            "#   ✗ = low confidence (<0.70)",
            "#",
        ]
        if unmapped_columns:
            lines.append(f"# Unmapped source columns: {', '.join(unmapped_columns)}")
        if unmapped_properties:
            lines.append(f"# Unmapped target properties: {', '.join(unmapped_properties)}")
        lines.append("")

        # YAML body
        yaml_body = yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)

        # Annotate source lines with confidence markers
        match_by_source = {m.source_column: m for m in matches}
        annotated_lines: list[str] = []
        for line in yaml_body.splitlines():
            # Check if this line has a "source: COLUMN_NAME" pattern
            stripped = line.strip()
            if stripped.startswith("source:"):
                col_name = stripped.split(":", 1)[1].strip().strip("'\"")
                m = match_by_source.get(col_name)
                if m:
                    marker = _confidence_marker(m.confidence)
                    line = f"{line}  {marker}"
            annotated_lines.append(line)

        lines.extend(annotated_lines)
        return "\n".join(lines) + "\n"
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_assembler.py -v --tb=short`
Expected: PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/wizard/assembler.py tests/test_wizard_assembler.py
git commit -m "feat(wizard): add MappingAssembler with annotated YAML output"
```

---

### Task 8: `LLMMatcher` — Phase 3 LLM integration

**Files:**
- Create: `src/ceds_jsonld/wizard/llm_matcher.py`
- Create: `tests/test_wizard_llm_matcher.py`

**Step 1: Write the failing test**

```python
# tests/test_wizard_llm_matcher.py
"""Tests for LLMMatcher — LLM-assisted column matching.

These tests use mocked LLM responses since actual LLM calls require
torch/transformers or a running Ollama instance.
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from ceds_jsonld.wizard.llm_matcher import LLMMatcher, _build_mapping_prompt, _parse_llm_response, _validate_response
from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.profiler import ColumnProfile


def _col(name: str, samples: list[str] | None = None, inferred_type: str = "string") -> ColumnProfile:
    return ColumnProfile(
        name=name,
        normalized=name.lower(),
        sample_values=samples or ["val1", "val2"],
        inferred_type=inferred_type,
        distinct_values=samples[:5] if samples else [],
    )


def _target(name: str, parent: str, label: str = "", description: str = "") -> TargetProperty:
    return TargetProperty(
        name=name, path=f"ceds:{name}", parent_shape=parent,
        label=label, description=description,
    )


class TestBuildMappingPrompt:

    def test_prompt_contains_columns(self) -> None:
        cols = [_col("FIRST_NM", ["Jane", "John"])]
        targets = [_target("FirstName", "PersonName", label="First Name")]
        prompt = _build_mapping_prompt(cols, targets)
        assert "FIRST_NM" in prompt
        assert "Jane" in prompt

    def test_prompt_contains_targets(self) -> None:
        cols = [_col("DOB")]
        targets = [_target("Birthdate", "PersonBirth", label="Birthdate")]
        prompt = _build_mapping_prompt(cols, targets)
        assert "Birthdate" in prompt
        assert "PersonBirth" in prompt

    def test_prompt_lists_transforms(self) -> None:
        cols = [_col("X")]
        targets = [_target("Y", "Z")]
        prompt = _build_mapping_prompt(cols, targets)
        assert "sex_prefix" in prompt
        assert "date_format" in prompt


class TestParseLLMResponse:

    def test_parse_valid_json(self) -> None:
        raw = json.dumps({
            "mappings": [
                {"source_column": "FIRST_NM", "target_property": "FirstName",
                 "target_shape": "PersonName", "confidence": 0.95,
                 "transform": None, "reason": "name match"},
            ]
        })
        result = _parse_llm_response(raw)
        assert len(result) == 1
        assert result[0]["source_column"] == "FIRST_NM"

    def test_parse_json_with_fences(self) -> None:
        raw = "```json\n" + json.dumps({"mappings": [{"source_column": "X", "target_property": "Y", "confidence": 0.8, "reason": "test"}]}) + "\n```"
        result = _parse_llm_response(raw)
        assert len(result) == 1

    def test_parse_invalid_returns_empty(self) -> None:
        result = _parse_llm_response("not json at all")
        assert result == []


class TestValidateResponse:

    def test_valid_mapping_passes(self) -> None:
        mappings = [{"source_column": "X", "target_property": "FirstName", "target_shape": "PersonName", "confidence": 0.9, "transform": "int_clean", "reason": "test"}]
        valid_properties = {"FirstName"}
        valid_transforms = {"int_clean", "date_format"}
        result = _validate_response(mappings, valid_properties, valid_transforms)
        assert len(result) == 1

    def test_hallucinated_property_filtered(self) -> None:
        mappings = [{"source_column": "X", "target_property": "FakeProperty", "confidence": 0.9, "reason": "test"}]
        valid_properties = {"FirstName"}
        result = _validate_response(mappings, valid_properties, set())
        assert len(result) == 0

    def test_hallucinated_transform_stripped(self) -> None:
        mappings = [{"source_column": "X", "target_property": "FirstName", "confidence": 0.9, "transform": "fake_transform", "reason": "test"}]
        valid_properties = {"FirstName"}
        valid_transforms = {"int_clean"}
        result = _validate_response(mappings, valid_properties, valid_transforms)
        assert len(result) == 1
        assert result[0]["transform"] is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_llm_matcher.py -v --tb=short`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/ceds_jsonld/wizard/llm_matcher.py
"""LLM-assisted matcher — Phase 3 of the three-phase matching pipeline.

Sends unresolved columns + target property descriptions to a local LLM
and parses the structured JSON response. Reuses the Phase 1 SDG LLM
infrastructure (Ollama or transformers backend).

This is a true external-service mock scenario — the LLM may not be
available, and responses are non-deterministic.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ceds_jsonld.logging import get_logger
from ceds_jsonld.transforms import BUILTIN_TRANSFORMS
from ceds_jsonld.wizard.collector import TargetProperty
from ceds_jsonld.wizard.concept_matcher import MatchCandidate
from ceds_jsonld.wizard.profiler import ColumnProfile

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _build_mapping_prompt(
    columns: list[ColumnProfile],
    targets: list[TargetProperty],
) -> str:
    """Build the LLM prompt for column→property mapping.

    Args:
        columns: Unresolved source columns.
        targets: Unmapped target properties.

    Returns:
        Complete prompt string.
    """
    lines: list[str] = [
        "/no_think",
        "You are an expert at mapping education data to CEDS (Common Education Data Standards).",
        "",
        "## Source Columns (unmapped)",
        "",
    ]

    for col in columns:
        lines.append(f'Column: "{col.name}"')
        if col.sample_values:
            samples = col.sample_values[:5]
            lines.append(f"  Samples: {samples}")
        lines.append(f"  Type: {col.inferred_type}")
        if col.distinct_values:
            lines.append(f"  Distinct: {col.distinct_values[:10]}")
        lines.append("")

    lines.append("## Available Target Properties")
    lines.append("")

    for target in targets:
        lines.append(f'Property: "{target.name}" (in {target.parent_shape})')
        if target.label:
            lines.append(f"  Label: \"{target.label}\"")
        if target.description:
            lines.append(f"  Description: \"{target.description}\"")
        if target.datatype:
            xsd = target.datatype.rsplit("#", 1)[-1] if "#" in target.datatype else target.datatype
            lines.append(f"  Datatype: {xsd}")
        if target.concept_values:
            vals = target.concept_values[:10]
            lines.append(f"  Concept Values: {vals}")
        lines.append("")

    lines.append("## Available Transforms")
    for name in sorted(BUILTIN_TRANSFORMS.keys()):
        lines.append(f"- {name}")
    lines.append("")

    lines.append("## Instructions")
    lines.append("For each source column, suggest the best matching target property.")
    lines.append('Return JSON: {"mappings": [{"source_column": "...", "target_property": "...", "target_shape": "...", "confidence": 0.0-1.0, "transform": "..." or null, "reason": "..."}]}')
    lines.append("Only use property names and transforms from the lists above.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_llm_response(raw: str) -> list[dict[str, Any]]:
    """Parse LLM JSON response into a list of mapping dicts.

    Handles markdown code fences and extra text around JSON.

    Args:
        raw: Raw LLM output text.

    Returns:
        List of mapping dicts, or empty list if parsing fails.
    """
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # Find JSON object with "mappings" key
    match = re.search(r"\{[^{}]*\"mappings\"\s*:\s*\[.*\]\s*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            mappings = data.get("mappings", [])
            if isinstance(mappings, list):
                return mappings
        except json.JSONDecodeError:
            pass

    _log.warning("Failed to parse LLM mapping response")
    return []


def _validate_response(
    mappings: list[dict[str, Any]],
    valid_properties: set[str],
    valid_transforms: set[str],
) -> list[dict[str, Any]]:
    """Filter out hallucinated properties and transforms.

    Args:
        mappings: Parsed LLM mapping dicts.
        valid_properties: Set of real target property names.
        valid_transforms: Set of real transform function names.

    Returns:
        Filtered list with only valid entries.
    """
    validated: list[dict[str, Any]] = []
    for m in mappings:
        prop = m.get("target_property", "")
        if prop not in valid_properties:
            _log.debug("Filtering hallucinated property: %s", prop)
            continue
        # Validate transform
        transform = m.get("transform")
        if transform and transform not in valid_transforms:
            _log.debug("Stripping hallucinated transform: %s", transform)
            m["transform"] = None
        validated.append(m)
    return validated


# ---------------------------------------------------------------------------
# LLM matcher
# ---------------------------------------------------------------------------


class LLMMatcher:
    """LLM-assisted column→property matcher.

    Reuses the Phase 1 SDG LLM infrastructure. Requires ``[sdg]`` extras.

    Args:
        backend: "ollama" or "transformers", or None for auto-detect.
        model: Model name override, or None for default.
    """

    def __init__(
        self,
        backend: str | None = None,
        model: str | None = None,
    ) -> None:
        self._backend = backend
        self._model = model

    def match(
        self,
        columns: list[ColumnProfile],
        targets: list[TargetProperty],
    ) -> tuple[list[MatchCandidate], list[ColumnProfile], list[TargetProperty]]:
        """Send unresolved columns to LLM and parse the response.

        Args:
            columns: Unresolved source columns.
            targets: Unmapped target properties.

        Returns:
            Same tuple as MatchingEngine phases: (matches, remaining_cols, remaining_targets).
        """
        prompt = _build_mapping_prompt(columns, targets)
        raw_response = self._call_llm(prompt)

        if not raw_response:
            return [], columns, targets

        parsed = _parse_llm_response(raw_response)
        if not parsed:
            return [], columns, targets

        valid_props = {t.name for t in targets}
        valid_transforms = set(BUILTIN_TRANSFORMS.keys())
        validated = _validate_response(parsed, valid_props, valid_transforms)

        matches: list[MatchCandidate] = []
        resolved_cols: set[str] = set()
        resolved_targets: set[str] = set()

        col_names = {c.name for c in columns}
        for m in validated:
            src = m.get("source_column", "")
            if src not in col_names or src in resolved_cols:
                continue
            tgt = m.get("target_property", "")
            if tgt in resolved_targets:
                continue

            matches.append(
                MatchCandidate(
                    source_column=src,
                    target_property=tgt,
                    target_shape=m.get("target_shape", ""),
                    confidence=float(m.get("confidence", 0.8)),
                    reasons=[m.get("reason", "LLM suggestion")],
                    strategy="llm",
                    suggested_transform=m.get("transform"),
                )
            )
            resolved_cols.add(src)
            resolved_targets.add(tgt)

        remaining_cols = [c for c in columns if c.name not in resolved_cols]
        remaining_targets = [t for t in targets if t.name not in resolved_targets]
        return matches, remaining_cols, remaining_targets

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM to get a mapping response.

        Tries Ollama first (if auto-detect or specified), falls back to
        transformers.

        Returns:
            Raw LLM output text, or empty string on failure.
        """
        if self._backend in (None, "ollama"):
            result = self._try_ollama(prompt)
            if result:
                return result
            if self._backend == "ollama":
                _log.warning("Ollama specified but not available")
                return ""

        if self._backend in (None, "transformers"):
            return self._try_transformers(prompt)

        return ""

    def _try_ollama(self, prompt: str) -> str:
        """Try Ollama REST API."""
        try:
            import httpx

            from ceds_jsonld.sdg.llm_generator import _OLLAMA_BASE, DEFAULT_OLLAMA_MODEL

            model = self._model or DEFAULT_OLLAMA_MODEL
            resp = httpx.post(
                f"{_OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=120.0,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "")
        except Exception:
            _log.debug("Ollama not available", exc_info=True)
        return ""

    def _try_transformers(self, prompt: str) -> str:
        """Try transformers + torch in-process."""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            from ceds_jsonld.sdg.llm_generator import DEFAULT_MODEL

            model_name = self._model or DEFAULT_MODEL
            _log.info("Loading model %s for mapping wizard...", model_name)

            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype="auto",
                device_map="auto",
            )

            messages = [{"role": "user", "content": prompt}]
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            inputs = tokenizer([text], return_tensors="pt").to(model.device)

            outputs = model.generate(
                **inputs,
                max_new_tokens=2048,
                do_sample=False,
            )
            generated = outputs[0][inputs["input_ids"].shape[-1]:]
            return tokenizer.decode(generated, skip_special_tokens=True)

        except ImportError:
            _log.warning("transformers not available — install ceds-jsonld[sdg]")
        except Exception:
            _log.warning("Transformers generation failed", exc_info=True)
        return ""
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_llm_matcher.py -v --tb=short`
Expected: PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/wizard/llm_matcher.py tests/test_wizard_llm_matcher.py
git commit -m "feat(wizard): add LLMMatcher with prompt builder and response validator"
```

---

### Task 9: `MappingWizard` — top-level orchestrator

**Files:**
- Modify: `src/ceds_jsonld/wizard/__init__.py`
- Create: `tests/test_wizard_integration.py`

**Step 1: Write the failing test**

```python
# tests/test_wizard_integration.py
"""Integration tests for MappingWizard — end-to-end CSV→YAML."""

from __future__ import annotations

import csv
import yaml
import pytest

from ceds_jsonld.wizard import MappingWizard


class TestMappingWizardHeuristicOnly:
    """End-to-end tests using heuristic-only mode (no LLM)."""

    @pytest.fixture()
    def sample_csv(self, tmp_path):
        path = tmp_path / "students.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["FirstName", "LastName", "DOB", "Gender"])
            w.writeheader()
            w.writerow({"FirstName": "Jane", "LastName": "Doe", "DOB": "1990-01-15", "Gender": "Female"})
            w.writerow({"FirstName": "John", "LastName": "Smith", "DOB": "1985-03-22", "Gender": "Male"})
        return str(path)

    def test_suggest_returns_result(self, sample_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(sample_csv, shape="person")
        assert result is not None
        assert result.mapping_config is not None
        assert isinstance(result.yaml_text, str)
        assert len(result.yaml_text) > 0

    def test_suggest_maps_known_columns(self, sample_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(sample_csv, shape="person")

        # Should map at least FirstName
        mapped_sources = {m.source_column for m in result.confidence_report}
        assert "FirstName" in mapped_sources

    def test_suggest_yaml_is_valid(self, sample_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(sample_csv, shape="person")

        # YAML should be parseable
        parsed = yaml.safe_load(result.yaml_text)
        assert parsed is not None
        assert "shape" in parsed

    def test_suggest_with_output_file(self, sample_csv, tmp_path) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(sample_csv, shape="person")
        out = tmp_path / "mapping.yaml"
        result.save(str(out))
        assert out.exists()
        content = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert content["shape"] is not None


class TestMappingWizardAutoDetect:
    """Test shape auto-detection."""

    @pytest.fixture()
    def person_csv(self, tmp_path):
        path = tmp_path / "people.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["FirstName", "LastName", "Birthdate"])
            w.writeheader()
            w.writerow({"FirstName": "Jane", "LastName": "Doe", "Birthdate": "1990-01-15"})
        return str(path)

    def test_detect_shape_returns_person(self, person_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        detected = wizard.detect_shape(person_csv)
        assert len(detected) > 0
        # Person should be the top match
        assert detected[0][0] == "person"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_integration.py -v --tb=short`
Expected: FAIL

**Step 3: Write MappingWizard class in `__init__.py`**

Update `src/ceds_jsonld/wizard/__init__.py` to add the `MappingWizard` class. This is the main orchestrator that ties together ColumnProfiler, ShapeMetadataCollector, MatchingEngine, and MappingAssembler.

The implementation should:
- Accept a CSV/Excel path + shape name
- Profile columns via ColumnProfiler
- Collect target properties via ShapeMetadataCollector
- Run MatchingEngine (three-phase)
- Assemble results via MappingAssembler
- Return WizardResult
- Support `detect_shape()` for auto-detection

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_integration.py -v --tb=short`
Expected: PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/wizard/__init__.py tests/test_wizard_integration.py
git commit -m "feat(wizard): add MappingWizard top-level orchestrator"
```

---

### Task 10: Wire `MappingWizard` into public API

**Files:**
- Modify: `src/ceds_jsonld/__init__.py` — add `MappingWizard` to imports and `__all__`

**Step 1: Write the failing test**

```python
# Add to tests/test_wizard_integration.py
def test_import_from_top_level() -> None:
    from ceds_jsonld import MappingWizard
    assert MappingWizard is not None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_integration.py::test_import_from_top_level -v`
Expected: FAIL — `ImportError`

**Step 3: Add import to `__init__.py`**

Add to `src/ceds_jsonld/__init__.py`:
```python
from ceds_jsonld.wizard import MappingWizard
```

And add `"MappingWizard"` to `__all__`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_integration.py::test_import_from_top_level -v`
Expected: PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/__init__.py
git commit -m "feat(wizard): expose MappingWizard in top-level ceds_jsonld API"
```

---

### Task 11: `map-wizard` CLI command

**Files:**
- Modify: `src/ceds_jsonld/cli.py` — add `map-wizard` command
- Create: `tests/test_wizard_cli.py`

**Step 1: Write the failing test**

```python
# tests/test_wizard_cli.py
"""Tests for map-wizard CLI command."""

from __future__ import annotations

import csv

import pytest
from click.testing import CliRunner

from ceds_jsonld.cli import cli


@pytest.fixture()
def sample_csv(tmp_path):
    path = tmp_path / "students.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["FirstName", "LastName", "DOB"])
        w.writeheader()
        w.writerow({"FirstName": "Jane", "LastName": "Doe", "DOB": "1990-01-15"})
        w.writerow({"FirstName": "John", "LastName": "Smith", "DOB": "1985-03-22"})
    return str(path)


class TestMapWizardCLI:

    def test_map_wizard_basic(self, sample_csv, tmp_path) -> None:
        runner = CliRunner()
        output = tmp_path / "mapping.yaml"
        result = runner.invoke(cli, [
            "map-wizard", "--input", sample_csv, "--shape", "person",
            "--output", str(output), "--no-llm",
        ])
        assert result.exit_code == 0, result.output
        assert output.exists()

    def test_map_wizard_stdout(self, sample_csv) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "map-wizard", "--input", sample_csv, "--shape", "person", "--no-llm",
        ])
        assert result.exit_code == 0
        assert "shape" in result.output

    def test_map_wizard_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["map-wizard", "--help"])
        assert result.exit_code == 0
        assert "map-wizard" in result.output or "input" in result.output
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wizard_cli.py -v --tb=short`
Expected: FAIL — "No such command 'map-wizard'"

**Step 3: Add map-wizard command to cli.py**

Add the `map-wizard` command between the `benchmark` command and the entry point section in `src/ceds_jsonld/cli.py`:

```python
@cli.command("map-wizard")
@click.option("-i", "--input", "input_path", required=True, type=click.Path(exists=True), help="Path to input data file.")
@click.option("-s", "--shape", default=None, help="Shape name. Auto-detected if omitted.")
@click.option("-o", "--output", "output_path", default=None, type=click.Path(), help="Output YAML path. Prints to stdout if omitted.")
@click.option("--no-llm", is_flag=True, default=False, help="Heuristic-only mode (no LLM).")
@click.option("--threshold", type=float, default=0.4, help="Minimum confidence threshold (default: 0.4).")
@click.option("--preview", type=int, default=0, help="Preview N records through Pipeline after mapping.")
@click.option("--shapes-dir", type=click.Path(exists=True, file_okay=False), default=None, help="Additional shapes directory.")
def map_wizard(input_path, shape, output_path, no_llm, threshold, preview, shapes_dir):
    """AI-assisted mapping wizard — auto-map columns to CEDS shapes."""
    from ceds_jsonld.wizard import MappingWizard
    # ... implementation
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wizard_cli.py -v --tb=short`
Expected: PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/cli.py tests/test_wizard_cli.py
git commit -m "feat(wizard): add map-wizard CLI command"
```

---

### Task 12: Preview mode — validate generated YAML through Pipeline

**Files:**
- Modify: `src/ceds_jsonld/wizard/__init__.py` — add `preview()` method to MappingWizard
- Add: `tests/test_wizard_integration.py::TestPreview`

**Step 1: Write test**

```python
# Add to tests/test_wizard_integration.py
class TestPreview:

    @pytest.fixture()
    def person_csv(self, tmp_path):
        path = tmp_path / "people.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["FirstName", "LastName", "Birthdate"])
            w.writeheader()
            w.writerow({"FirstName": "Jane", "LastName": "Doe", "Birthdate": "1990-01-15"})
            w.writerow({"FirstName": "John", "LastName": "Smith", "Birthdate": "1985-03-22"})
        return str(path)

    def test_preview_returns_docs(self, person_csv) -> None:
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(person_csv, shape="person")
        docs = wizard.preview(person_csv, result, count=2)
        assert isinstance(docs, list)
        # May be empty if mapping is incomplete, but should not error
```

**Step 2–5:** Implement, test, commit.

```powershell
git commit -m "feat(wizard): add preview mode for generated mappings"
```

---

### Task 13: Shape auto-detection

**Files:**
- Modify: `src/ceds_jsonld/wizard/__init__.py` — flesh out `detect_shape()`
- Tests already in Task 9

**Step 1: Implementation**

The `detect_shape()` method in MappingWizard should:
1. Profile columns from the input file
2. For each registered shape, load its metadata collector and get leaf property names
3. Score overlap: `matched_properties / total_properties`
4. Return sorted list of `(shape_name, score)`

**Step 2: Verify existing test passes**

Run: `python -m pytest tests/test_wizard_integration.py::TestMappingWizardAutoDetect -v`
Expected: PASS

**Step 3: Commit**

```powershell
git commit -m "feat(wizard): add shape auto-detection via column overlap"
```

---

### Task 14: QW-2 — `introspect` Markdown table output

**Files:**
- Modify: `src/ceds_jsonld/cli.py` — add `--format markdown` to `introspect`
- Add: `tests/test_cli.py::TestIntrospectMarkdown` (or new test file)

**Step 1: Write the failing test**

```python
# In tests/test_cli.py or a new test file
def test_introspect_markdown(tmp_path) -> None:
    from click.testing import CliRunner
    from ceds_jsonld.cli import cli

    shacl = "src/ceds_jsonld/ontologies/person/Person_SHACL.ttl"
    runner = CliRunner()
    result = runner.invoke(cli, ["introspect", "--shacl", shacl, "--format", "markdown"])
    assert result.exit_code == 0
    assert "| Property" in result.output
    assert "FirstName" in result.output
```

**Step 2: Implement**

Add `--format` option to the existing `introspect` command (currently it has `--json` flag). Replace the flag with a `--format` choice of `text`, `json`, `markdown`. Format the output as a Markdown table with columns: Property, Sub-Shape, Type, Required, Concept Scheme.

**Step 3–5:** Test, commit.

```powershell
git commit -m "feat(cli): add markdown table output to introspect command (QW-2)"
```

---

### Task 15: QW-1 — HTML validation report

**Files:**
- Create: `src/ceds_jsonld/report.py` — HTML report generator
- Modify: `src/ceds_jsonld/cli.py` — add `--report` option to `validate`
- Create: `tests/test_report.py`

**Step 1: Write the failing test**

```python
# tests/test_report.py
"""Tests for HTML validation report generator."""

from __future__ import annotations

from ceds_jsonld.report import generate_html_report
from ceds_jsonld.validator import ValidationResult, FieldIssue


class TestHTMLReport:

    def test_generate_passing_report(self) -> None:
        result = ValidationResult(
            conforms=True,
            record_count=5,
            error_count=0,
            warning_count=0,
            issues={},
        )
        html = generate_html_report(result, shape="person")
        assert "<html" in html
        assert "PASSED" in html

    def test_generate_failing_report(self) -> None:
        result = ValidationResult(
            conforms=False,
            record_count=3,
            error_count=2,
            warning_count=1,
            issues={
                "record-1": [
                    FieldIssue(severity="error", property_path="FirstName", message="Required field missing"),
                ]
            },
        )
        html = generate_html_report(result, shape="person")
        assert "FAILED" in html
        assert "FirstName" in html

    def test_report_is_self_contained(self) -> None:
        result = ValidationResult(conforms=True, record_count=1, error_count=0, warning_count=0, issues={})
        html = generate_html_report(result, shape="person")
        # Should not reference external CSS/JS
        assert "http://" not in html
        assert "https://" not in html
```

**Step 2: Implement**

Build a self-contained HTML report using inline CSS. Shows:
- Summary header (shape, record count, pass/fail)
- Per-record table with pass/fail status
- Error details with property paths and messages
- Summary statistics

**Note:** Do NOT add jinja2 as a dependency. Use Python string formatting or `string.Template`.

**Step 3–5:** Test, commit.

```powershell
git commit -m "feat(validate): add HTML validation report generator (QW-1)"
```

---

### Task 16: Wire QW-1 `--report` option to validate CLI

**Files:**
- Modify: `src/ceds_jsonld/cli.py` — add `--report` to `validate` command

**Step 1: Test**

```python
# In tests/test_cli.py
def test_validate_html_report(tmp_path) -> None:
    # Create test CSV and run validate with --report
    ...
```

**Step 2–5:** Implement, test, commit.

```powershell
git commit -m "feat(cli): add --report option for HTML validation output (QW-1)"
```

---

### Task 17: Update `wizard/__init__.py` exports and `__all__`

**Files:**
- Modify: `src/ceds_jsonld/wizard/__init__.py` — export all public classes

**Step 1: Update exports**

```python
from ceds_jsonld.wizard.assembler import MappingAssembler, WizardResult
from ceds_jsonld.wizard.collector import ShapeMetadataCollector, TargetProperty
from ceds_jsonld.wizard.concept_matcher import ConceptValueMatcher, MatchCandidate
from ceds_jsonld.wizard.engine import MatchingEngine
from ceds_jsonld.wizard.heuristic import HeuristicMatcher
from ceds_jsonld.wizard.profiler import ColumnProfile, ColumnProfiler

__all__ = [
    "ColumnProfile", "ColumnProfiler",
    "ConceptValueMatcher", "HeuristicMatcher",
    "MappingAssembler", "MappingWizard",
    "MatchCandidate", "MatchingEngine",
    "ShapeMetadataCollector", "TargetProperty",
    "WizardResult",
]
```

**Step 2: Commit**

```powershell
git commit -m "feat(wizard): export all public classes from wizard package"
```

---

### Task 18: Full test suite run + end-to-end journey test

**Files:**
- Add: `tests/test_wizard_integration.py::TestEndToEndJourney`

**Step 1: Write journey test**

Test the complete user workflow: CSV → MappingWizard → YAML → FieldMapper → JSONLDBuilder → valid JSON-LD output. This is the most important test — it proves the wizard-generated YAML actually works with the existing pipeline.

```python
class TestEndToEndJourney:

    def test_wizard_yaml_through_pipeline(self, tmp_path) -> None:
        """CSV → Wizard (no LLM) → YAML → Pipeline → JSON-LD."""
        import yaml
        from ceds_jsonld.wizard import MappingWizard
        from ceds_jsonld.mapping import FieldMapper
        from ceds_jsonld.registry import ShapeRegistry

        # 1. Create test CSV with known person data
        csv_path = tmp_path / "input.csv"
        csv_path.write_text(
            "FirstName,LastName,Birthdate\n"
            "Jane,Doe,1990-01-15\n"
            "John,Smith,1985-03-22\n",
            encoding="utf-8",
        )

        # 2. Run wizard
        wizard = MappingWizard(use_llm=False)
        result = wizard.suggest(str(csv_path), shape="person")

        # 3. Verify YAML is valid
        config = yaml.safe_load(result.yaml_text)
        assert config is not None
        assert config["shape"] is not None

        # 4. Verify at least some columns mapped
        assert len(result.confidence_report) > 0
```

**Step 2: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL pass (808 existing + ~50 new wizard tests)

**Step 3: Commit**

```powershell
git commit -m "test(wizard): add end-to-end journey test"
```

---

### Task 19: Documentation updates

**Files:**
- Modify: `README.md` — add Mapping Wizard section
- Modify: `ROADMAP.md` — mark Phase 2 tasks complete, update status

**Step 1: Update README**

Add a "Mapping Wizard" section after the existing library description showing:
- Python API usage (`MappingWizard().suggest(...)`)
- CLI usage (`ceds-jsonld map-wizard ...`)
- What the wizard does (three-phase matching)

**Step 2: Update ROADMAP**

- Check all Phase 2 task boxes (`- [x]`)
- Update deliverable checkboxes
- Update summary timeline table
- Add completion note block

**Step 3: Commit**

```powershell
git commit -m "docs: add mapping wizard docs to README, mark Phase 2 complete in ROADMAP"
```

---

### Task 20: Merge to dev

**Step 1: Run full test suite one final time**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL pass

**Step 2: Merge**

```powershell
git checkout dev
git pull origin dev
$env:GIT_EDITOR = "true"
git merge --no-ff feature/mapping-wizard
git push origin dev
```

**Step 3: Delete branch**

```powershell
git branch -d feature/mapping-wizard
git push origin --delete feature/mapping-wizard
```

---

## Execution Notes

### Key Design Decisions Encoded

1. **Three-phase pipeline order:** concept-value → heuristic → LLM (per PoC findings)
2. **No new dependencies:** Heuristic mode uses stdlib + rdflib. LLM mode reuses `[sdg]` extras.
3. **Output format:** Annotated YAML matching `person_mapping.yaml` structure with confidence comments.
4. **LLM prompt:** `/no_think` prefix, `enable_thinking=False`, JSON schema in instructions.
5. **Transform suggestion:** Pattern-based in heuristic phase, LLM-suggested in Phase 3.
6. **Post-validation:** Filter hallucinated properties and transforms from LLM output.

### Risk Mitigations

- **PoC already validated 100% accuracy** on 34 columns across 3 CSVs.
- **Heuristic-only mode works without LLM** — graceful degradation.
- **All LLM processing is local** — FERPA compliant, no data leaves machine.
- **Concept-value matching resolves ~40% deterministically** — minimizes LLM calls.

### Dependencies on Existing Code

- `SHACLIntrospector` — shape tree parsing (no changes needed)
- `ConceptSchemeResolver` — concept value resolution (no changes needed)
- `OntologyMetadataExtractor` — labels and descriptions (no changes needed)
- `LLMValueGenerator` — model constants and Ollama base URL (imported)
- `BUILTIN_TRANSFORMS` — transform registry (imported)
- `ShapeRegistry` — shape loading (no changes needed)
