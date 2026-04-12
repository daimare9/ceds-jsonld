# Validation Reporting & Power BI Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the validation subsystem with structured output formats (JSON, CSV, Parquet, DataFrame) and Cosmos DB persistence so validation results can be consumed by Power BI and other BI tools.

**Architecture:** Two-tiered approach. Tier 1 (v1.2.0) adds run metadata to `ValidationResult`, serialization methods (`to_dict`, `to_dataframe`), four report generators (HTML, JSON, CSV, Parquet), and CLI `--report-format` support. Tier 2 (v1.3.0) adds a `ValidationStore` class in `cosmos/` that persists results to a shared Cosmos DB container partitioned by shape, plus `Pipeline.validate(persist=True)` and CLI `--persist` integration. Both tiers are backward compatible — all new fields have defaults.

**Tech Stack:** Python 3.11+, pandas (DataFrame/CSV/Parquet export), orjson (JSON export, with stdlib json fallback), pyarrow (Parquet export via pandas), azure-cosmos (Tier 2 only), Power BI (documentation only — native Cosmos connector + CSV/Parquet import).

**Branches:** `feature/validation-reporting-tier1` (v1.2.0), `feature/validation-reporting-tier2` (v1.3.0)

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Run metadata | Auto-populated with optional overrides | Minimize user ceremony; Pipeline knows shape/source already |
| CLI report flag | `--report-format` + `--report-path` replaces `--report` | Cleaner than N separate flags; extensible |
| Tier 2 container | One shared `validation_results`, partitioned by `shape` | Simpler than per-shape containers; BI queries span shapes |
| Tier 2 activation | Pipeline flag + standalone `ValidationStore` | Convenience for common case + flexibility for advanced users |
| Versions | v1.2.0 (Tier 1), v1.3.0 (Tier 2) | Separate releases — Tier 1 has zero Azure deps |
| Backward compat | All new fields have defaults | `ValidationResult()` with no args still works |

---

## Existing Code Reference

- **`src/ceds_jsonld/validator.py`** — `ValidationResult` dataclass (fields: `conforms`, `record_count`, `error_count`, `warning_count`, `issues: dict[str, list[FieldIssue]]`, `raw_report: str`). `PreBuildValidator`, `SHACLValidator`. `FieldIssue` dataclass. `ValidationMode` enum.
- **`src/ceds_jsonld/report.py`** — `generate_html_report(result, *, shape="") -> str`. Single function, HTML-only.
- **`src/ceds_jsonld/pipeline.py`** — `Pipeline.validate(*, mode, sample_rate, shacl) -> ValidationResult`. Runs pre-build then optional SHACL.
- **`src/ceds_jsonld/cli.py`** — `validate` command with `--report <path>` (HTML only). Lines ~250-340.
- **`src/ceds_jsonld/cosmos/loader.py`** — `CosmosLoader` with `upsert_one()`, `upsert_many()`. Async context manager.
- **`src/ceds_jsonld/cosmos/prepare.py`** — `prepare_for_cosmos(doc)` injects `id`/`partitionKey`.
- **`src/ceds_jsonld/__init__.py`** — Public exports. `ValidationResult`, `FieldIssue`, `ValidationMode` already exported.
- **`tests/test_report.py`** — 3 tests for HTML report generation.
- **`tests/test_validator.py`** — ~20+ tests for PreBuildValidator and ValidationResult.

---

## Tier 1 — Structured Output Formats (v1.2.0)

### Task 1: Add run metadata fields to ValidationResult

**Files:**
- Modify: `src/ceds_jsonld/validator.py` (the `ValidationResult` dataclass, ~lines 70-100)
- Test: `tests/test_validator.py`

**What changes:**
Add five new fields to `ValidationResult`, all with defaults so existing code is unaffected:

```python
import uuid
import datetime

@dataclass
class ValidationResult:
    conforms: bool = True
    record_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    issues: dict[str, list[FieldIssue]] = field(default_factory=dict)
    raw_report: str = ""
    # --- New metadata fields (Tier 1) ---
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())
    shape_name: str = ""
    source_name: str = ""
    library_version: str = ""
```

**Step 1: Write failing tests**

In `tests/test_validator.py`, add to the `TestValidationResult` class:

```python
def test_metadata_defaults_populated(self):
    """New metadata fields auto-populate with sensible defaults."""
    result = ValidationResult()
    assert result.run_id  # non-empty UUID string
    assert result.timestamp  # non-empty ISO timestamp
    assert result.shape_name == ""
    assert result.source_name == ""
    assert result.library_version == ""

def test_metadata_overrides(self):
    """Metadata fields can be overridden at construction."""
    result = ValidationResult(
        run_id="custom-id",
        timestamp="2026-04-10T00:00:00+00:00",
        shape_name="person",
        source_name="students.csv",
        library_version="1.2.0",
    )
    assert result.run_id == "custom-id"
    assert result.shape_name == "person"
```

**Step 2: Run tests — expect FAIL** (fields don't exist yet)

```powershell
cls ; .\.venv\Scripts\python.exe -m pytest tests/test_validator.py::TestValidationResult::test_metadata_defaults_populated -v
```

**Step 3: Implement** — add the five fields to the dataclass in `validator.py`.

**Step 4: Run tests — expect PASS**

```powershell
cls ; .\.venv\Scripts\python.exe -m pytest tests/test_validator.py::TestValidationResult -v
```

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/validator.py tests/test_validator.py
git commit -m "feat(validator): add run metadata fields to ValidationResult"
```

---

### Task 2: Add to_dict() method to ValidationResult

**Files:**
- Modify: `src/ceds_jsonld/validator.py`
- Test: `tests/test_validator.py`

**What changes:**
Add `to_dict() -> dict[str, Any]` that returns the full result as a JSON-serializable dict.

```python
def to_dict(self) -> dict[str, Any]:
    """Serialize to a JSON-compatible dict.

    Returns a dict with all metadata, summary counts, and a flat
    list of issues (each issue includes its record_id).
    """
    flat_issues = []
    for record_id, issue_list in self.issues.items():
        for issue in issue_list:
            flat_issues.append({
                "record_id": record_id,
                "property_path": issue.property_path,
                "message": issue.message,
                "severity": issue.severity,
                "expected": issue.expected,
                "actual": issue.actual,
            })

    return {
        "run_id": self.run_id,
        "timestamp": self.timestamp,
        "shape_name": self.shape_name,
        "source_name": self.source_name,
        "library_version": self.library_version,
        "conforms": self.conforms,
        "record_count": self.record_count,
        "error_count": self.error_count,
        "warning_count": self.warning_count,
        "issues": flat_issues,
    }
```

**Step 1: Write failing tests**

```python
def test_to_dict_conforming(self):
    """to_dict on a conforming result includes metadata and empty issues."""
    result = ValidationResult(shape_name="person", source_name="test.csv")
    d = result.to_dict()
    assert d["conforms"] is True
    assert d["shape_name"] == "person"
    assert d["issues"] == []
    assert "run_id" in d
    assert "timestamp" in d

def test_to_dict_with_issues(self):
    """to_dict flattens issues with record_id."""
    result = ValidationResult()
    result.add_issue("rec-1", FieldIssue(property_path="firstName", message="missing"))
    d = result.to_dict()
    assert len(d["issues"]) == 1
    assert d["issues"][0]["record_id"] == "rec-1"
    assert d["issues"][0]["property_path"] == "firstName"
```

**Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.

**Step 5: Commit**

```powershell
git commit -am "feat(validator): add to_dict() serialization to ValidationResult"
```

---

### Task 3: Add to_dataframe() method to ValidationResult

**Files:**
- Modify: `src/ceds_jsonld/validator.py`
- Test: `tests/test_validator.py`

**What changes:**
Add `to_dataframe()` that returns a pandas DataFrame with one row per issue.

```python
def to_dataframe(self) -> Any:
    """Convert issues to a pandas DataFrame.

    Returns a DataFrame with columns: run_id, timestamp, shape_name,
    source_name, record_id, property_path, severity, message, expected, actual.

    If there are no issues, returns a DataFrame with metadata columns
    and zero rows.

    Raises:
        ImportError: If pandas is not installed.
    """
    import pandas as pd

    rows = []
    for record_id, issue_list in self.issues.items():
        for issue in issue_list:
            rows.append({
                "run_id": self.run_id,
                "timestamp": self.timestamp,
                "shape_name": self.shape_name,
                "source_name": self.source_name,
                "record_id": record_id,
                "property_path": issue.property_path,
                "severity": issue.severity,
                "message": issue.message,
                "expected": str(issue.expected) if issue.expected is not None else "",
                "actual": str(issue.actual) if issue.actual is not None else "",
            })

    return pd.DataFrame(rows, columns=[
        "run_id", "timestamp", "shape_name", "source_name",
        "record_id", "property_path", "severity", "message",
        "expected", "actual",
    ])
```

**Step 1: Write failing tests**

```python
def test_to_dataframe_empty(self):
    """to_dataframe on conforming result returns empty DataFrame with correct columns."""
    import pandas as pd
    result = ValidationResult(shape_name="person")
    df = result.to_dataframe()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
    assert "record_id" in df.columns
    assert "shape_name" in df.columns

def test_to_dataframe_with_issues(self):
    """to_dataframe returns one row per issue."""
    result = ValidationResult(shape_name="person")
    result.add_issue("rec-1", FieldIssue(property_path="a", message="msg1"))
    result.add_issue("rec-1", FieldIssue(property_path="b", message="msg2"))
    result.add_issue("rec-2", FieldIssue(property_path="c", message="msg3"))
    df = result.to_dataframe()
    assert len(df) == 3
    assert list(df["record_id"]) == ["rec-1", "rec-1", "rec-2"]
```

**Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.

**Step 5: Commit**

```powershell
git commit -am "feat(validator): add to_dataframe() to ValidationResult"
```

---

### Task 4: Add generate_json_report() to report.py

**Files:**
- Modify: `src/ceds_jsonld/report.py`
- Test: `tests/test_report.py`

**What changes:**
New function alongside existing `generate_html_report`:

```python
def generate_json_report(result: ValidationResult, *, shape: str = "") -> str:
    """Serialize a ValidationResult to a JSON string.

    Uses orjson if available, falls back to stdlib json.
    Includes run metadata and flattened issues list.
    """
    data = result.to_dict()
    if shape and not data.get("shape_name"):
        data["shape_name"] = shape

    try:
        import orjson
        return orjson.dumps(data, option=orjson.OPT_INDENT_2).decode()
    except ImportError:
        import json
        return json.dumps(data, indent=2, default=str)
```

**Step 1: Write failing tests** in `tests/test_report.py`:

```python
def test_generate_json_report_conforming(self) -> None:
    result = ValidationResult(shape_name="person")
    import json
    text = generate_json_report(result, shape="person")
    data = json.loads(text)
    assert data["conforms"] is True
    assert data["shape_name"] == "person"

def test_generate_json_report_with_issues(self) -> None:
    result = ValidationResult()
    result.add_issue("rec-1", FieldIssue(property_path="a", message="bad"))
    import json
    text = generate_json_report(result)
    data = json.loads(text)
    assert len(data["issues"]) == 1
```

**Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 5: Add generate_csv_report() and generate_parquet_report() to report.py

**Files:**
- Modify: `src/ceds_jsonld/report.py`
- Test: `tests/test_report.py`

**What changes:**

```python
def generate_csv_report(result: ValidationResult, *, shape: str = "") -> str:
    """Serialize a ValidationResult to CSV string.

    One row per issue. Columns: run_id, timestamp, shape_name, source_name,
    record_id, property_path, severity, message, expected, actual.
    """
    if shape and not result.shape_name:
        result.shape_name = shape
    df = result.to_dataframe()
    return df.to_csv(index=False)


def generate_parquet_report(result: ValidationResult, path: str, *, shape: str = "") -> None:
    """Write a ValidationResult to a Parquet file.

    Args:
        result: The validation result.
        path: File path for the Parquet output.
        shape: Shape name override.
    """
    if shape and not result.shape_name:
        result.shape_name = shape
    df = result.to_dataframe()
    df.to_parquet(path, index=False, engine="pyarrow")
```

**Tests:**

```python
def test_generate_csv_report(self) -> None:
    result = ValidationResult(shape_name="person")
    result.add_issue("rec-1", FieldIssue(property_path="a", message="bad"))
    csv_text = generate_csv_report(result, shape="person")
    assert "rec-1" in csv_text
    assert "property_path" in csv_text  # header row

def test_generate_parquet_report(self, tmp_path) -> None:
    import pandas as pd
    result = ValidationResult(shape_name="person")
    result.add_issue("rec-1", FieldIssue(property_path="a", message="bad"))
    path = str(tmp_path / "report.parquet")
    generate_parquet_report(result, path)
    df = pd.read_parquet(path)
    assert len(df) == 1
    assert df.iloc[0]["record_id"] == "rec-1"
```

**Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 6: Wire Pipeline.validate() to populate metadata

**Files:**
- Modify: `src/ceds_jsonld/pipeline.py` (`validate()` method, ~lines 250-340)
- Test: `tests/test_pipeline.py`

**What changes:**
At the start of `Pipeline.validate()`, populate the result metadata:

```python
from ceds_jsonld import __version__

result = ValidationResult(
    shape_name=self._shape_name,
    source_name=type(self._source).__name__,
    library_version=__version__,
)
```

The `_shape_name` field is already stored as `self._shape_name` in `Pipeline.__init__`. The source adapter class name provides a reasonable default for `source_name`.

**Tests:**

```python
def test_validate_populates_run_metadata(self, person_pipeline):
    """Pipeline.validate() fills in run_id, timestamp, shape_name."""
    result = person_pipeline.validate()
    assert result.run_id  # non-empty
    assert result.timestamp  # non-empty
    assert result.shape_name == "person"
    assert result.source_name  # adapter class name
    assert result.library_version  # library version string
```

**Step 5: Commit**

```powershell
git commit -am "feat(pipeline): populate validation run metadata automatically"
```

---

### Task 7: Update CLI validate command with --report-format and --report-path

**Files:**
- Modify: `src/ceds_jsonld/cli.py` (~lines 260-340)
- Test: `tests/test_cli.py`

**What changes:**
Replace the existing `--report` option with `--report-format` and `--report-path`:

```python
@click.option(
    "--report-format",
    type=click.Choice(["html", "json", "csv", "parquet"], case_sensitive=False),
    default=None,
    help="Generate a validation report in this format.",
)
@click.option(
    "--report-path",
    type=click.Path(),
    default=None,
    help="Output path for the validation report.",
)
```

In the command body, replace the existing HTML-only report block:

```python
if report_format:
    from ceds_jsonld.report import (
        generate_html_report,
        generate_json_report,
        generate_csv_report,
        generate_parquet_report,
    )

    # Default file name if --report-path not provided
    if not report_path:
        ext = {"html": ".html", "json": ".json", "csv": ".csv", "parquet": ".parquet"}
        report_path = f"validation_report{ext[report_format]}"

    fmt = report_format.lower()
    if fmt == "html":
        text = generate_html_report(result, shape=shape)
        Path(report_path).write_text(text, encoding="utf-8")
    elif fmt == "json":
        text = generate_json_report(result, shape=shape)
        Path(report_path).write_text(text, encoding="utf-8")
    elif fmt == "csv":
        text = generate_csv_report(result, shape=shape)
        Path(report_path).write_text(text, encoding="utf-8")
    elif fmt == "parquet":
        generate_parquet_report(result, report_path, shape=shape)

    click.echo(f"Report written to {report_path}")
```

**Backward compatibility note:** The old `--report` flag is removed. This is a breaking CLI change but the Python API is untouched. Document in CHANGELOG.

**Tests** — add to `tests/test_cli.py`:

```python
def test_validate_report_json(self, runner, tmp_path, person_csv):
    """--report-format json produces valid JSON file."""
    out = tmp_path / "report.json"
    result = runner.invoke(cli, [
        "validate", "-s", "person", "-i", str(person_csv),
        "--report-format", "json", "--report-path", str(out),
    ])
    assert result.exit_code == 0
    import json
    data = json.loads(out.read_text())
    assert "conforms" in data

def test_validate_report_csv(self, runner, tmp_path, person_csv):
    """--report-format csv produces CSV with header row."""
    out = tmp_path / "report.csv"
    result = runner.invoke(cli, [
        "validate", "-s", "person", "-i", str(person_csv),
        "--report-format", "csv", "--report-path", str(out),
    ])
    assert result.exit_code == 0
    text = out.read_text()
    assert "property_path" in text
```

**Step 5: Commit**

```powershell
git commit -am "feat(cli): replace --report with --report-format/--report-path"
```

---

### Task 8: Update exports, version bump, CHANGELOG

**Files:**
- Modify: `src/ceds_jsonld/__init__.py` — add `generate_json_report`, `generate_csv_report`, `generate_parquet_report` to imports and `__all__`
- Modify: `src/ceds_jsonld/report.py` — ensure all functions are importable
- Modify: `pyproject.toml` — bump to `1.2.0`
- Modify: `src/ceds_jsonld/__init__.py` — `__version__ = "1.2.0"`
- Modify: `CHANGELOG.md` — add v1.2.0 section

**Step 1:** Update all files. **Step 2:** Run full pre-commit checklist:

```powershell
cls ; .\.venv\Scripts\python.exe -m ruff check src/ tests/
.\.venv\Scripts\python.exe -m ruff format --check src/ tests/
.\.venv\Scripts\python.exe -m mypy src/ --no-incremental > mypy_out.txt 2>&1 ; Get-Content mypy_out.txt
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=short
```

**Step 3: Commit, merge, tag**

```powershell
git commit -am "chore: bump to v1.2.0, update exports and CHANGELOG"
# Merge to dev
$env:GIT_EDITOR = "true"
git checkout dev ; git merge --no-ff feature/validation-reporting-tier1
git push origin dev
# Merge to main
git checkout main ; git merge --no-ff dev
git tag -a v1.2.0 -m "v1.2.0 — Structured validation reporting"
git push origin main --tags
# Cleanup
git branch -d feature/validation-reporting-tier1
git push origin --delete feature/validation-reporting-tier1
git checkout dev
```

---

## Tier 2 — Cosmos DB Validation Store (v1.3.0)

### Task 9: Create ValidationStore class

**Files:**
- Create: `src/ceds_jsonld/cosmos/validation_store.py`
- Test: `tests/test_cosmos.py` (add to existing)

**What changes:**
A new class that wraps `CosmosLoader` specifically for validation results:

```python
class ValidationStore:
    """Persist ValidationResult documents to Azure Cosmos DB.

    Uses a single shared container ('validation_results') partitioned
    by shape_name. Each document is the output of ValidationResult.to_dict()
    with Cosmos-required id/partitionKey fields injected.

    Args:
        endpoint: Cosmos DB account URI.
        credential: Azure credential or master key string.
        database: Database name (default: "ceds").
        container: Container name (default: "validation_results").
    """

    def __init__(
        self,
        endpoint: str,
        credential: Any,
        database: str = "ceds",
        container: str = "validation_results",
    ) -> None: ...

    async def store(self, result: ValidationResult) -> UpsertResult:
        """Persist a single ValidationResult."""
        ...

    async def store_many(self, results: list[ValidationResult]) -> BulkResult:
        """Persist multiple ValidationResults."""
        ...

    async def query_by_shape(self, shape: str, *, limit: int = 100) -> list[dict]:
        """Query recent validation runs for a shape."""
        ...

    async def query_by_run(self, run_id: str) -> dict | None:
        """Retrieve a specific validation run by ID."""
        ...
```

**Cosmos document shape:**

```json
{
    "id": "<run_id>",
    "partitionKey": "<shape_name>",
    "run_id": "<uuid>",
    "timestamp": "<iso-datetime>",
    "shape_name": "person",
    "source_name": "students.csv",
    "library_version": "1.3.0",
    "conforms": false,
    "record_count": 1000,
    "error_count": 5,
    "warning_count": 12,
    "issues": [...]
}
```

**Tests** — mock Cosmos (true external service):

```python
class TestValidationStore:
    def test_store_prepares_document(self):
        """store() converts ValidationResult to dict with id/partitionKey."""
        ...

    def test_store_uses_run_id_as_cosmos_id(self):
        """The Cosmos 'id' field is the ValidationResult.run_id."""
        ...
```

---

### Task 10: Wire Pipeline.validate(persist=True)

**Files:**
- Modify: `src/ceds_jsonld/pipeline.py`
- Test: `tests/test_pipeline.py`

**What changes:**
Add optional `cosmos_config` parameter to Pipeline and `persist` flag to `validate()`:

```python
class Pipeline:
    def __init__(
        self,
        ...,
        cosmos_config: dict[str, Any] | None = None,  # NEW
    ) -> None: ...

    def validate(
        self,
        *,
        mode: str | ValidationMode = "report",
        sample_rate: float = 0.01,
        shacl: bool = False,
        persist: bool = False,  # NEW
    ) -> ValidationResult:
        ...
        # After validation completes:
        if persist:
            if not self._cosmos_config:
                raise PipelineError("persist=True requires cosmos_config")
            import asyncio
            from ceds_jsonld.cosmos.validation_store import ValidationStore
            store = ValidationStore(**self._cosmos_config)
            asyncio.run(store.store(result))

        return result
```

---

### Task 11: Add CLI --persist flag

**Files:**
- Modify: `src/ceds_jsonld/cli.py`
- Test: `tests/test_cli.py`

**What changes:**
Add `--persist` flag and cosmos connection options to the `validate` command:

```python
@click.option("--persist/--no-persist", default=False, help="Store results in Cosmos DB.")
@click.option("--cosmos-endpoint", envvar="CEDS_COSMOS_ENDPOINT", help="Cosmos DB endpoint.")
@click.option("--cosmos-database", envvar="CEDS_COSMOS_DATABASE", default="ceds")
@click.option("--cosmos-key", envvar="CEDS_COSMOS_KEY", help="Cosmos DB master key (dev only).")
```

Environment variable support means users can configure once and forget.

---

### Task 12: Update exports, docs, version bump

**Files:**
- Modify: `src/ceds_jsonld/cosmos/__init__.py` — add `ValidationStore` export
- Modify: `src/ceds_jsonld/__init__.py` — add `ValidationStore` to imports and `__all__`
- Modify: `pyproject.toml` — bump to `1.3.0`
- Modify: `CHANGELOG.md` — add v1.3.0 section

---

### Task 13: Write Power BI connection guide

**Files:**
- Create: `docs/powerbi-reporting.rst`
- Modify: `docs/index.rst` — add to toctree

**Contents:**
- Section 1: "Quick Start — CSV/Parquet Import" (Tier 1, no Azure needed)
- Section 2: "Live Dashboard — Cosmos DB Connector" (Tier 2)
- Section 3: "Sample Power BI template" (suggested measures: pass rate over time, top failing properties, error count by shape)
- Screenshots/examples of suggested Power BI visuals

---

## Files Changed Summary

### Tier 1 (v1.2.0)

| File | Action | What |
|------|--------|------|
| `src/ceds_jsonld/validator.py` | Modify | Add 5 metadata fields + `to_dict()` + `to_dataframe()` |
| `src/ceds_jsonld/report.py` | Modify | Add `generate_json_report()`, `generate_csv_report()`, `generate_parquet_report()` |
| `src/ceds_jsonld/pipeline.py` | Modify | Populate metadata in `validate()` |
| `src/ceds_jsonld/cli.py` | Modify | Replace `--report` with `--report-format`/`--report-path` |
| `src/ceds_jsonld/__init__.py` | Modify | Export new report functions, bump version |
| `pyproject.toml` | Modify | Bump to 1.2.0 |
| `CHANGELOG.md` | Modify | v1.2.0 entry |
| `tests/test_validator.py` | Modify | Tests for metadata, to_dict, to_dataframe |
| `tests/test_report.py` | Modify | Tests for JSON, CSV, Parquet reports |
| `tests/test_pipeline.py` | Modify | Test metadata population |
| `tests/test_cli.py` | Modify | Tests for new CLI flags |

### Tier 2 (v1.3.0)

| File | Action | What |
|------|--------|------|
| `src/ceds_jsonld/cosmos/validation_store.py` | Create | `ValidationStore` class |
| `src/ceds_jsonld/cosmos/__init__.py` | Modify | Export `ValidationStore` |
| `src/ceds_jsonld/pipeline.py` | Modify | Add `persist` flag + `cosmos_config` |
| `src/ceds_jsonld/cli.py` | Modify | Add `--persist` + cosmos options |
| `src/ceds_jsonld/__init__.py` | Modify | Export `ValidationStore`, bump version |
| `pyproject.toml` | Modify | Bump to 1.3.0 |
| `CHANGELOG.md` | Modify | v1.3.0 entry |
| `docs/powerbi-reporting.rst` | Create | Power BI connection guide |
| `docs/index.rst` | Modify | Add to toctree |
| `tests/test_cosmos.py` | Modify | ValidationStore tests |
| `tests/test_pipeline.py` | Modify | persist=True test |
| `tests/test_cli.py` | Modify | --persist test |

---

## Risk Considerations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `to_dataframe()` adds pandas as implicit dependency of validator | Low | pandas is already a core dep (used by all adapters) |
| CLI `--report` removal breaks existing scripts | Medium | Document in CHANGELOG as breaking CLI change; Python API unaffected |
| Large validation results (100K+ issues) → huge Cosmos docs | Medium | Consider truncating issues array or splitting into summary+detail docs |
| `generate_parquet_report` requires pyarrow | Low | pyarrow is already a core dep as of v1.1.0 |
