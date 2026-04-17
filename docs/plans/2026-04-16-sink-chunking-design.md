# Streaming Output Sinks with Chunking

**Date:** 2026-04-16
**Status:** Approved
**Branch:** `feature/output-sinks`

## Problem

Pipeline output methods (`to_ndjson`, `to_json`, `to_cosmos`) are hardcoded on the
Pipeline class. Users working in Azure Spark notebooks need to write chunked NDJSON
to local directories or ADLS (via ABFSS paths) with configurable partitioning —
similar to how Spark writes partitioned output. There is no sink abstraction or
chunking support today.

## Design Decisions

- **Approach A selected:** Protocol-based Sink with `Pipeline.to_sink()` method.
- **Chunking:** Configurable per sink via `chunk_size` (default 10,000 records).
  Pipeline owns the batching loop; sinks receive pre-chunked lists.
- **Path structure:** Flat part files (`part-00000.ndjson`, `part-00001.ndjson`, …).
- **ADLS:** Uses `fsspec` + `adlfs` for native ABFSS support. Optional dependency.
- **Existing methods stay:** `to_ndjson()`, `to_json()`, `to_cosmos()` are untouched.

## Sink Protocol

```python
@runtime_checkable
class Sink(Protocol):
    chunk_size: int
    def open(self) -> None: ...
    def write_chunk(self, docs: list[dict[str, Any]]) -> None: ...
    def close(self) -> SinkResult: ...
```

### SinkResult

```python
@dataclass
class SinkResult:
    files_written: int = 0
    records_written: int = 0
    bytes_written: int = 0
    errors: list[str] = field(default_factory=list)
```

## Concrete Implementations

### NDJSONSink

- **Constructor:** `NDJSONSink(path: str | Path, *, chunk_size: int = 10_000)`
- **`open()`:** Creates output directory via `pathlib`.
- **`write_chunk(docs)`:** Writes `part-NNNNN.ndjson` using `serializer.dumps()`.
- **`close()`:** Returns `SinkResult` with file count and bytes written.
- **Dependencies:** None beyond existing serializer.

### ADLSink

- **Constructor:** `ADLSink(path: str, *, chunk_size: int = 10_000, storage_options: dict | None = None)`
- **`open()`:** Initializes `fsspec.filesystem("abfss", **storage_options)`, creates directory.
- **`write_chunk(docs)`:** Writes `part-NNNNN.ndjson` via fsspec file handle.
- **`close()`:** Returns `SinkResult`.
- **Dependencies:** `fsspec>=2023.1.0`, `adlfs>=2023.1.0` (optional extra `[adls]`).
- **Import guard:** Raises `ImportError` with install instructions if missing.
- **`storage_options`:** Standard fsspec pattern for auth (account key, SAS, credential).

## Pipeline Integration

```python
def to_sink(self, sink: Sink) -> PipelineResult:
```

- Calls `sink.open()`, iterates `self._source.read()`, maps/builds each row.
- Accumulates docs into batches of `sink.chunk_size`, calls `sink.write_chunk()`.
- Flushes remainder, calls `sink.close()`.
- DLQ works identically to existing `to_ndjson()`.
- Returns `PipelineResult` with `bytes_written` from `SinkResult`.

### User-Facing API

```python
from ceds_jsonld import Pipeline, NDJSONSink, ADLSink

# Local chunked NDJSON
result = pipeline.to_sink(NDJSONSink("./output/person", chunk_size=5_000))

# ADLS chunked NDJSON
sink = ADLSink(
    "abfss://data@myaccount.dfs.core.windows.net/jsonld/person",
    chunk_size=10_000,
    storage_options={"account_name": "myaccount"},
)
result = pipeline.to_sink(sink)
```

## Error Handling

- `sink.open()` failure → `PipelineError("Failed to open sink: {error}")`
- `sink.write_chunk()` failure → `PipelineError`. Part files are atomic.
- `ADLSink` missing deps → `ImportError` with install instructions.
- `chunk_size < 1` → `ValueError` at sink construction.
- Dead-letter queue works unchanged — failed rows never reach the sink.

## Testing Plan

| Test | Coverage |
|------|----------|
| `test_ndjson_sink_basic` | 25 records, chunk_size=10 → 3 part files (10, 10, 5) |
| `test_ndjson_sink_exact_boundary` | 20 records, chunk_size=10 → exactly 2 files |
| `test_ndjson_sink_single_chunk` | 5 records, chunk_size=10_000 → 1 part file |
| `test_ndjson_sink_result` | Verify SinkResult fields |
| `test_pipeline_to_sink` | Full Pipeline.to_sink(NDJSONSink) end-to-end |
| `test_pipeline_to_sink_dlq` | Poison row → DLQ file, good rows in sink |
| `test_pipeline_to_sink_result` | PipelineResult counts and bytes |
| `test_adl_sink_import_guard` | Missing fsspec → clear ImportError |
| `test_adl_sink_write_chunk` | Mock fsspec filesystem, verify part files |
| `test_sink_protocol` | isinstance checks for both sinks |
| `test_chunk_size_validation` | chunk_size=0 or -1 → ValueError |
| `test_sink_reusable_export` | Importable from `ceds_jsonld` top-level |

- NDJSONSink tests use real file I/O (`tmp_path`).
- ADLSink tests mock fsspec (external cloud service).

## Optional Dependency in pyproject.toml

```toml
[project.optional-dependencies]
adls = ["fsspec>=2023.1.0", "adlfs>=2023.1.0"]
```

## Exports (ceds_jsonld/__init__.py)

- `Sink`
- `SinkResult`
- `NDJSONSink`
- `ADLSink`

## File Changes

| File | Change |
|------|--------|
| `src/ceds_jsonld/sinks.py` | New — Sink protocol, SinkResult, NDJSONSink, ADLSink |
| `src/ceds_jsonld/pipeline.py` | Add `to_sink()` method |
| `src/ceds_jsonld/__init__.py` | Export Sink, SinkResult, NDJSONSink, ADLSink |
| `pyproject.toml` | Add `[adls]` optional dependency |
| `tests/test_sinks.py` | New — all 12 tests |
