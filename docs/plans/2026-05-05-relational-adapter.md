# RelationalAdapter — Multi-Table Star Schema Support

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable users with star-schema relational data (e.g., multiple Parquet files) to produce JSON-LD documents with embedded arrays without pre-joining outside the library.

**Architecture:** A new `RelationalAdapter` wraps a primary adapter + N satellite adapters. It loads satellites into an in-memory index at init time. For each primary row it injects `__related__: {table_name: [rows]}`. A new `source_table` key in YAML mapping configs tells `FieldMapper` to pull instances from the satellite rows instead of splitting a pipe-delimited string. Zero changes to `JSONLDBuilder`, `Pipeline`, `ShapeRegistry`, or serializer.

**Tech Stack:** Python 3.14, pandas (already a dependency), existing `SourceAdapter` ABC, `FieldMapper`, YAML mapping config schema.

---

## Task 1: Create `RelationalAdapter`

**Files:**
- Create: `src/ceds_jsonld/adapters/relational_adapter.py`

### Step 1: Write failing test

In `tests/test_relational_adapter.py` (new file), write:

```python
from ceds_jsonld.adapters.relational_adapter import RelationalAdapter
from ceds_jsonld.adapters.dict_adapter import DictAdapter

def test_relational_adapter_basic_join():
    primary = DictAdapter([
        {"student_id": "1", "first_name": "Alice"},
        {"student_id": "2", "first_name": "Bob"},
    ])
    ids_sat = DictAdapter([
        {"student_id": "1", "id_type": "SSN", "id_value": "111-11-1111"},
        {"student_id": "1", "id_type": "State", "id_value": "MI001"},
        {"student_id": "2", "id_type": "SSN", "id_value": "222-22-2222"},
    ])
    adapter = RelationalAdapter(
        primary=primary,
        join_key="student_id",
        satellites={"identifications": ids_sat},
    )
    rows = list(adapter.read())
    assert len(rows) == 2
    alice = rows[0]
    assert alice["first_name"] == "Alice"
    assert len(alice["__related__"]["identifications"]) == 2
    assert rows[1]["__related__"]["identifications"][0]["id_type"] == "SSN"
```

Run: `pytest tests/test_relational_adapter.py::test_relational_adapter_basic_join -v`
Expected: **FAIL** — `ModuleNotFoundError: relational_adapter`

### Step 2: Implement `RelationalAdapter`

Create `src/ceds_jsonld/adapters/relational_adapter.py`:

```python
"""Relational adapter — join a primary source with satellite sources.

Enables star-schema data (separate Parquet/CSV/database tables per relationship)
to be processed through the existing Pipeline without any pre-join ETL.
Satellite tables are loaded eagerly into memory at init time.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from ceds_jsonld.adapters.base import SourceAdapter
from ceds_jsonld.exceptions import AdapterError
from ceds_jsonld.logging import get_logger

_log = get_logger(__name__)

#: Key injected into each primary row to carry satellite data.
RELATED_KEY = "__related__"


class RelationalAdapter(SourceAdapter):
    """Join a primary source adapter with satellite adapters for one-to-many data.

    Loads all satellite data into memory at initialization, keyed by the join
    column. For each primary row yielded, injects a ``__related__`` dict
    containing the matching satellite rows for each logical table name.

    This allows YAML mapping configs to reference satellite rows via the
    ``source_table`` property key, enabling relational one-to-many data
    to become embedded typed arrays in JSON-LD output.

    Example:
        >>> adapter = RelationalAdapter(
        ...     primary=ParquetAdapter("students.parquet"),
        ...     join_key="student_id",
        ...     satellites={
        ...         "identifications": ParquetAdapter("student_ids.parquet"),
        ...         "races": ParquetAdapter("student_races.parquet"),
        ...     }
        ... )
        >>> for row in adapter.read():
        ...     print(row["student_id"], row["__related__"]["identifications"])
    """

    def __init__(
        self,
        primary: SourceAdapter,
        join_key: str,
        satellites: dict[str, SourceAdapter],
        *,
        satellite_join_key: str | None = None,
    ) -> None:
        """Initialize and eagerly load all satellite data into memory.

        Args:
            primary: The primary (one-side) adapter. Yields one row per entity.
            join_key: Column name in the primary table that identifies each
                entity (e.g. ``"student_id"``).
            satellites: Dict mapping a logical table name to its adapter.
                Each adapter yields many-side rows for that relationship.
            satellite_join_key: Column name in the satellite tables that
                matches back to the primary. Defaults to the same value as
                ``join_key``.

        Raises:
            AdapterError: If ``join_key`` is blank or ``satellites`` is empty.
        """
        if not join_key or not join_key.strip():
            msg = "join_key must be a non-empty string."
            raise AdapterError(msg)
        if not satellites:
            msg = (
                "RelationalAdapter requires at least one satellite adapter. "
                "If you have no satellites, use the primary adapter directly."
            )
            raise AdapterError(msg)

        self._primary = primary
        self._join_key = join_key
        self._sat_join_key = satellite_join_key or join_key
        self._satellite_index: dict[str, dict[str, list[dict[str, Any]]]] = {}

        # Eagerly load all satellites into an in-memory index
        for table_name, sat_adapter in satellites.items():
            index: dict[str, list[dict[str, Any]]] = defaultdict(list)
            rows_loaded = 0
            for row in sat_adapter.read():
                fk_value = row.get(self._sat_join_key)
                if fk_value is None or str(fk_value).strip() == "":
                    _log.warning(
                        "relational_adapter.missing_fk",
                        table=table_name,
                        fk_column=self._sat_join_key,
                    )
                    continue
                index[str(fk_value)].append(row)
                rows_loaded += 1
            self._satellite_index[table_name] = dict(index)
            _log.info(
                "relational_adapter.satellite_loaded",
                table=table_name,
                rows=rows_loaded,
                unique_keys=len(self._satellite_index[table_name]),
            )

    def read(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Yield enriched primary rows with satellite data injected.

        Each primary row is yielded with an additional ``__related__`` key
        whose value is ``{table_name: [matching_satellite_rows]}``. If a
        primary entity has no satellite rows for a table, an empty list is
        used — the property is simply omitted from the JSON-LD output.

        Returns:
            Iterator of dicts. Each dict is the primary row merged with
            ``{"__related__": {table_name: [satellite_row, ...]}}``.
        """
        for primary_row in self._primary.read(**kwargs):
            pk_value = primary_row.get(self._join_key)
            pk_str = "" if pk_value is None else str(pk_value)

            related: dict[str, list[dict[str, Any]]] = {
                table_name: index.get(pk_str, [])
                for table_name, index in self._satellite_index.items()
            }

            enriched = dict(primary_row)
            enriched[RELATED_KEY] = related
            yield enriched

    def count(self) -> int | None:
        """Return primary row count if the primary adapter supports it."""
        return self._primary.count()
```

Run: `pytest tests/test_relational_adapter.py::test_relational_adapter_basic_join -v`
Expected: **PASS**

### Step 3: Add remaining unit tests to `tests/test_relational_adapter.py`

```python
import pytest
from ceds_jsonld.adapters.relational_adapter import RelationalAdapter, RELATED_KEY
from ceds_jsonld.adapters.dict_adapter import DictAdapter
from ceds_jsonld.exceptions import AdapterError


def test_relational_adapter_empty_satellites_raises():
    with pytest.raises(AdapterError, match="at least one satellite"):
        RelationalAdapter(
            primary=DictAdapter([{"id": "1"}]),
            join_key="id",
            satellites={},
        )


def test_relational_adapter_blank_join_key_raises():
    with pytest.raises(AdapterError, match="non-empty string"):
        RelationalAdapter(
            primary=DictAdapter([{"id": "1"}]),
            join_key="  ",
            satellites={"x": DictAdapter([])},
        )


def test_relational_adapter_no_satellite_match_yields_empty_list():
    primary = DictAdapter([{"student_id": "99", "name": "Ghost"}])
    sat = DictAdapter([{"student_id": "1", "code": "SSN"}])
    adapter = RelationalAdapter(primary=primary, join_key="student_id", satellites={"ids": sat})
    rows = list(adapter.read())
    assert rows[0][RELATED_KEY]["ids"] == []


def test_relational_adapter_multiple_satellites():
    primary = DictAdapter([{"id": "1", "name": "Alice"}])
    races = DictAdapter([{"id": "1", "race": "Asian"}])
    ids = DictAdapter([{"id": "1", "id_val": "MI001"}])
    adapter = RelationalAdapter(
        primary=primary,
        join_key="id",
        satellites={"races": races, "ids": ids},
    )
    rows = list(adapter.read())
    assert "races" in rows[0][RELATED_KEY]
    assert "ids" in rows[0][RELATED_KEY]
    assert rows[0][RELATED_KEY]["races"][0]["race"] == "Asian"


def test_relational_adapter_custom_satellite_join_key():
    """Support different FK column names in primary vs satellite."""
    primary = DictAdapter([{"person_id": "1", "name": "Bob"}])
    sat = DictAdapter([{"student_fk": "1", "val": "X"}])
    adapter = RelationalAdapter(
        primary=primary,
        join_key="person_id",
        satellites={"data": sat},
        satellite_join_key="student_fk",
    )
    rows = list(adapter.read())
    assert rows[0][RELATED_KEY]["data"][0]["val"] == "X"


def test_relational_adapter_satellite_missing_fk_skipped():
    """Satellite rows with no FK value are skipped (not joined to anyone)."""
    primary = DictAdapter([{"id": "1", "name": "Alice"}])
    sat = DictAdapter([
        {"id": "1", "code": "SSN"},
        {"id": "", "code": "BAD"},      # empty FK — skip
        {"id": None, "code": "ALSO_BAD"},  # None FK — skip
    ])
    adapter = RelationalAdapter(primary=primary, join_key="id", satellites={"ids": sat})
    rows = list(adapter.read())
    assert len(rows[0][RELATED_KEY]["ids"]) == 1  # only the valid row


def test_relational_adapter_count_delegates_to_primary():
    from ceds_jsonld.adapters.csv_adapter import CSVAdapter
    primary = DictAdapter([{"id": "1"}, {"id": "2"}])
    sat = DictAdapter([])
    adapter = RelationalAdapter(primary=primary, join_key="id", satellites={"x": sat})
    # DictAdapter.count() returns None (no count support)
    assert adapter.count() is None
```

Run: `pytest tests/test_relational_adapter.py -v`
Expected: **ALL PASS**

---

## Task 2: Extend `FieldMapper` for `source_table`

**Files:**
- Modify: `src/ceds_jsonld/mapping.py`

The change is localized to `_map_property()` — if the property definition contains `source_table`, delegate to a new `_map_from_table()` method instead of `_map_multiple()` or `_map_single()`. The `_map_from_table()` method iterates over the satellite rows in `raw_row["__related__"][source_table]` and maps each row to one instance.

### Step 1: Write the failing integration test

Add to `tests/test_relational_adapter.py`:

```python
from ceds_jsonld.mapping import FieldMapper


RELATIONAL_MAPPING = {
    "shape": "TestShape",
    "context_url": "https://example.org/ctx.json",
    "base_uri": "cepi:test/",
    "id_source": "student_id",
    "type": "Student",
    "properties": {
        "hasIdentification": {
            "type": "Identification",
            "cardinality": "multiple",
            "source_table": "identifications",  # ← NEW KEY
            "fields": {
                "IdentifierValue": {
                    "source": "id_value",
                    "target": "IdentifierValue",
                },
                "IdentifierType": {
                    "source": "id_type",
                    "target": "IdentifierType",
                    "optional": True,
                },
            },
        }
    },
}


def test_field_mapper_source_table():
    primary = DictAdapter([{"student_id": "1", "name": "Alice"}])
    sat = DictAdapter([
        {"student_id": "1", "id_value": "MI001", "id_type": "State"},
        {"student_id": "1", "id_value": "SSN123", "id_type": "SSN"},
    ])
    adapter = RelationalAdapter(
        primary=primary,
        join_key="student_id",
        satellites={"identifications": sat},
    )
    mapper = FieldMapper(RELATIONAL_MAPPING)
    rows = list(adapter.read())
    mapped = mapper.map(rows[0])
    assert mapped["__id__"] == "1"
    ids = mapped["hasIdentification"]
    assert len(ids) == 2
    assert ids[0]["IdentifierValue"] == "MI001"
    assert ids[1]["IdentifierValue"] == "SSN123"


def test_field_mapper_source_table_no_satellite_rows():
    """Property is absent from output when there are no satellite rows."""
    primary = DictAdapter([{"student_id": "99", "name": "Ghost"}])
    sat = DictAdapter([{"student_id": "1", "id_value": "X", "id_type": "Y"}])
    adapter = RelationalAdapter(
        primary=primary, join_key="student_id", satellites={"identifications": sat}
    )
    mapper = FieldMapper(RELATIONAL_MAPPING)
    rows = list(adapter.read())
    mapped = mapper.map(rows[0])
    assert "hasIdentification" not in mapped
```

Run: `pytest tests/test_relational_adapter.py::test_field_mapper_source_table -v`
Expected: **FAIL** — `FieldMapper` doesn't know about `source_table`

### Step 2: Implement `_map_from_table()` in `FieldMapper`

In `src/ceds_jsonld/mapping.py`, change `_map_property()` to check for `source_table`:

```python
def _map_property(
    self,
    raw_row: dict[str, Any],
    prop_name: str,
    prop_def: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map a single property, respecting cardinality and source_table."""
    # NEW: satellite table mode takes precedence over split_on
    if "source_table" in prop_def:
        return self._map_from_table(raw_row, prop_name, prop_def)
    cardinality = prop_def.get("cardinality", "single")
    if cardinality == "multiple":
        return self._map_multiple(raw_row, prop_name, prop_def)
    return self._map_single(raw_row, prop_name, prop_def)
```

Then add the `_map_from_table()` method (after `_map_multiple`, before `_is_empty`):

```python
def _map_from_table(
    self,
    raw_row: dict[str, Any],
    prop_name: str,
    prop_def: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map a property from satellite table rows injected by RelationalAdapter.

    Each satellite row (in ``raw_row["__related__"][source_table]``) becomes
    one instance of the sub-shape, using the same field-mapping logic as
    ``_map_single`` but applied per satellite row.

    Args:
        raw_row: The enriched primary row from RelationalAdapter (contains
            ``__related__`` key).
        prop_name: YAML property name (for error messages).
        prop_def: The property definition dict from the mapping config.

    Returns:
        List of mapped instance dicts, one per satellite row. Empty list if
        no satellite rows exist for this entity.
    """
    from ceds_jsonld.adapters.relational_adapter import RELATED_KEY

    source_table = prop_def["source_table"]
    related = raw_row.get(RELATED_KEY)
    if not related or source_table not in related:
        # No __related__ key at all — raw_row came from a non-relational
        # adapter; treat as empty (graceful degradation).
        return []

    satellite_rows = related[source_table]
    if not satellite_rows:
        return []

    fields = prop_def.get("fields", {})
    instances: list[dict[str, Any]] = []

    for sat_row in satellite_rows:
        instance: dict[str, Any] = {}
        for _field_key, field_def in fields.items():
            target = field_def.get("target", _field_key)
            source = field_def["source"]
            value = sat_row.get(source)

            if self._is_empty(value):
                if not field_def.get("optional", False):
                    # Required field missing in satellite row — skip instance
                    _log.warning(
                        "mapper.satellite_missing_required",
                        property=prop_name,
                        field=source,
                        table=source_table,
                    )
                    instance = {}
                    break
                continue

            self._ensure_scalar(value, source, prop_name)
            value = sanitize_string_value(str(value))

            transform_name = field_def.get("transform")
            if transform_name:
                transform_fn = get_transform(transform_name, self._custom_transforms)
                try:
                    raw_result = transform_fn(value)
                except Exception as exc:
                    msg = (
                        f"Transform '{transform_name}' raised {type(exc).__name__} on field "
                        f"'{source}' in satellite table '{source_table}' "
                        f"for property '{prop_name}': {exc}"
                    )
                    raise MappingError(msg) from exc
                value = self._validate_transform_result(
                    raw_result, value, transform_name, source, prop_name
                )

            if value is None:
                if not field_def.get("optional", False):
                    msg = (
                        f"Transform on required field '{source}' in satellite table "
                        f"'{source_table}' for property '{prop_name}' produced None."
                    )
                    raise MappingError(msg)
                continue

            # Handle multi_value_split within a satellite field
            multi_split = field_def.get("multi_value_split")
            if multi_split:
                sub_values = [v.strip() for v in value.split(multi_split) if v.strip()]
                if sub_values:
                    instance[target] = sub_values
            else:
                instance[target] = value

        if instance:
            instances.append(instance)

    return instances
```

Run: `pytest tests/test_relational_adapter.py -v`
Expected: **ALL PASS**

---

## Task 3: Export `RelationalAdapter` from the package

**Files:**
- Modify: `src/ceds_jsonld/adapters/__init__.py`
- Modify: `src/ceds_jsonld/__init__.py`

### Step 1: Add to `adapters/__init__.py`

Add the import and export:
```python
from ceds_jsonld.adapters.relational_adapter import RelationalAdapter
```
Add `"RelationalAdapter"` to `__all__`.

### Step 2: Add to `src/ceds_jsonld/__init__.py`

Add `RelationalAdapter` to the top-level import block (alongside other adapters) and to `__all__`.

Run: `python -c "from ceds_jsonld import RelationalAdapter; print(RelationalAdapter)"`
Expected: `<class 'ceds_jsonld.adapters.relational_adapter.RelationalAdapter'>`

---

## Task 4: End-to-end integration test

**Files:**
- Modify: `tests/test_relational_adapter.py`

Add a full pipeline integration test that goes CSV/Dict → RelationalAdapter → FieldMapper → JSONLDBuilder → complete JSON-LD document:

```python
from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.registry import ShapeDefinition
from pathlib import Path


FULL_MAPPING = {
    "shape": "StudentShape",
    "context_url": "https://example.org/ctx.json",
    "base_uri": "cepi:student/",
    "id_source": "student_id",
    "type": "Student",
    "properties": {
        "hasPersonName": {
            "type": "PersonName",
            "cardinality": "single",
            "fields": {
                "FirstName": {"source": "first_name", "target": "FirstName"},
                "LastName": {"source": "last_name", "target": "LastOrSurname"},
            },
        },
        "hasIdentification": {
            "type": "Identification",
            "cardinality": "multiple",
            "source_table": "identifications",
            "fields": {
                "IdentifierValue": {"source": "id_value", "target": "IdentifierValue"},
                "IdentifierType": {"source": "id_type", "target": "IdentifierType", "optional": True},
            },
        },
    },
}


def test_full_pipeline_relational():
    """End-to-end: primary + satellite → JSON-LD with embedded array."""
    primary = DictAdapter([
        {"student_id": "1", "first_name": "Alice", "last_name": "Smith"},
    ])
    sat = DictAdapter([
        {"student_id": "1", "id_value": "MI001", "id_type": "State"},
        {"student_id": "1", "id_value": "SSN123", "id_type": "SSN"},
    ])
    adapter = RelationalAdapter(
        primary=primary, join_key="student_id", satellites={"identifications": sat}
    )
    shape_def = ShapeDefinition(
        name="StudentShape",
        base_dir=Path("."),
        shacl_path=Path("."),
        context={},
        mapping_config=FULL_MAPPING,
    )
    mapper = FieldMapper(FULL_MAPPING)
    builder = JSONLDBuilder(shape_def)

    rows = list(adapter.read())
    mapped = mapper.map(rows[0])
    doc = builder.build_one(mapped)

    assert doc["@type"] == "Student"
    assert doc["@id"] == "cepi:student/1"
    name = doc["hasPersonName"]
    assert name["FirstName"] == "Alice"
    ids = doc["hasIdentification"]
    assert isinstance(ids, list)
    assert len(ids) == 2
    assert ids[0]["IdentifierValue"] == "MI001"
    assert ids[1]["IdentifierType"] == "SSN"
```

Run: `pytest tests/test_relational_adapter.py -v`
Expected: **ALL PASS**

---

## Task 5: Update YAML mapping instructions

**Files:**
- Modify: `.github/instructions/yaml-mapping.instructions.md`

Add a new section documenting `source_table`:

```markdown
### Multi-Table / Relational Sources (Star Schema)

When source data lives in separate relational tables (e.g., multiple Parquet files),
use `source_table` in a property definition instead of `split_on`. The `source_table`
value must match a key in the `satellites` dict passed to `RelationalAdapter`.

```yaml
properties:
  hasIdentification:
    type: Identification
    cardinality: multiple
    source_table: identifications   # ← matches satellites={"identifications": ...}
    fields:
      IdentifierValue:
        source: id_value            # ← column in the satellite table
        target: IdentifierValue
      IdentifierType:
        source: id_type
        target: IdentifierType
        optional: true
```

**Rules:**
- `source_table` and `split_on` are mutually exclusive. `source_table` takes precedence.
- When `source_table` is set, `cardinality` is effectively always `multiple` — each satellite row becomes one instance.
- Fields under `source_table` properties reference **satellite table columns**, not primary table columns.
- If no satellite rows exist for a primary entity, the property is omitted from the JSON-LD output (not an error).
- `source_table` requires the adapter to be a `RelationalAdapter`. Using it with a flat adapter returns an empty list and omits the property.
```

---

## Task 6: Commit

```bash
git add src/ceds_jsonld/adapters/relational_adapter.py \
        src/ceds_jsonld/adapters/__init__.py \
        src/ceds_jsonld/__init__.py \
        src/ceds_jsonld/mapping.py \
        tests/test_relational_adapter.py \
        .github/instructions/yaml-mapping.instructions.md \
        docs/plans/2026-05-05-relational-adapter.md

git commit -m "feat(adapters): add RelationalAdapter for star-schema multi-table sources

Adds RelationalAdapter that wraps a primary SourceAdapter with N satellite
adapters. Satellites are eagerly loaded into a memory index at init; each
primary row is enriched with matching satellite rows under __related__.

Extends FieldMapper with _map_from_table() to map satellite rows into typed
sub-shape arrays when a property definition contains source_table.

YAML mapping: source_table replaces split_on for relational sources.

New tests cover: join logic, empty satellites, missing FK rows, custom
satellite FK column, end-to-end pipeline integration.

Closes #<issue>"
```

---

## Checklist

- [ ] `RelationalAdapter` class created and tested
- [ ] `FieldMapper._map_from_table()` implemented and tested
- [ ] `RelationalAdapter` exported from `ceds_jsonld` top-level
- [ ] End-to-end integration test passes
- [ ] YAML instructions updated with `source_table` docs
- [ ] Full test suite passes with no regressions
- [ ] Committed on `feature/relational-adapter` branch
