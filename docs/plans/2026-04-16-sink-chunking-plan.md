# Output Sinks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `Sink` protocol with `NDJSONSink` and `ADLSink` implementations, and a `Pipeline.to_sink()` method that streams documents into chunked part files.

**Architecture:** Protocol-based sinks (`Sink`) with three methods: `open()`, `write_chunk()`, `close()`. Pipeline owns the chunking loop via `to_sink(sink)`, reading `sink.chunk_size` to batch documents from `stream()`. NDJSONSink writes to local disk via pathlib; ADLSink writes to ABFSS via fsspec+adlfs.

**Tech Stack:** Python 3.12+, `typing.Protocol`, `pathlib`, `fsspec`, `adlfs`, `orjson` (via existing `serializer.dumps`).

**Design Doc:** `docs/plans/2026-04-16-sink-chunking-design.md`

---

## Pre-Implementation

### Task 0: Create feature branch

**Step 1: Branch from dev**

```powershell
git checkout dev ; git pull origin dev ; git checkout -b feature/output-sinks
```

**Step 2: Verify branch**

```powershell
git branch --show-current
```

Expected: `feature/output-sinks`

---

## Task 1: Sink Protocol, SinkResult dataclass, and NDJSONSink

**Files:**
- Create: `src/ceds_jsonld/sinks.py`
- Test: `tests/test_sinks.py`

**Step 1: Write failing tests for NDJSONSink**

Create `tests/test_sinks.py`:

```python
"""Tests for output sinks — NDJSONSink, ADLSink, Sink protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ceds_jsonld.sinks import NDJSONSink, Sink, SinkResult


def _make_docs(n: int) -> list[dict[str, Any]]:
    """Generate *n* minimal JSON-LD-like documents."""
    return [{"@id": f"urn:test:{i}", "@type": "Person", "name": f"Person {i}"} for i in range(n)]


class TestSinkResult:
    def test_defaults(self) -> None:
        r = SinkResult()
        assert r.files_written == 0
        assert r.records_written == 0
        assert r.bytes_written == 0
        assert r.errors == []


class TestNDJSONSinkBasic:
    def test_chunked_output(self, tmp_path: Path) -> None:
        """25 records, chunk_size=10 → 3 part files (10, 10, 5)."""
        sink = NDJSONSink(tmp_path / "out", chunk_size=10)
        sink.open()
        docs = _make_docs(25)
        sink.write_chunk(docs[:10])
        sink.write_chunk(docs[10:20])
        sink.write_chunk(docs[20:])
        result = sink.close()

        assert result.files_written == 3
        assert result.bytes_written > 0
        files = sorted((tmp_path / "out").glob("part-*.ndjson"))
        assert len(files) == 3
        assert files[0].name == "part-00000.ndjson"
        assert files[2].name == "part-00002.ndjson"

        # Verify content
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 10
        assert json.loads(lines[0])["@id"] == "urn:test:0"

        lines_last = files[2].read_text().strip().split("\n")
        assert len(lines_last) == 5

    def test_exact_boundary(self, tmp_path: Path) -> None:
        """20 records, chunk_size=10 → exactly 2 files, no empty trailing."""
        sink = NDJSONSink(tmp_path / "out", chunk_size=10)
        sink.open()
        docs = _make_docs(20)
        sink.write_chunk(docs[:10])
        sink.write_chunk(docs[10:])
        result = sink.close()

        assert result.files_written == 2
        files = sorted((tmp_path / "out").glob("part-*.ndjson"))
        assert len(files) == 2

    def test_single_chunk(self, tmp_path: Path) -> None:
        """5 records, chunk_size=10_000 → 1 part file."""
        sink = NDJSONSink(tmp_path / "out", chunk_size=10_000)
        sink.open()
        sink.write_chunk(_make_docs(5))
        result = sink.close()

        assert result.files_written == 1
        files = list((tmp_path / "out").glob("part-*.ndjson"))
        assert len(files) == 1

    def test_sink_result_fields(self, tmp_path: Path) -> None:
        """SinkResult has correct files_written and bytes_written."""
        sink = NDJSONSink(tmp_path / "out", chunk_size=10)
        sink.open()
        sink.write_chunk(_make_docs(3))
        result = sink.close()

        assert result.files_written == 1
        assert result.bytes_written > 0
        # bytes_written should match actual file size
        actual_size = sum(f.stat().st_size for f in (tmp_path / "out").glob("part-*.ndjson"))
        assert result.bytes_written == actual_size


class TestNDJSONSinkValidation:
    def test_chunk_size_zero(self) -> None:
        with pytest.raises(ValueError, match="chunk_size must be >= 1"):
            NDJSONSink("some/path", chunk_size=0)

    def test_chunk_size_negative(self) -> None:
        with pytest.raises(ValueError, match="chunk_size must be >= 1"):
            NDJSONSink("some/path", chunk_size=-5)


class TestSinkProtocol:
    def test_ndjson_sink_satisfies_protocol(self, tmp_path: Path) -> None:
        sink = NDJSONSink(tmp_path / "out")
        assert isinstance(sink, Sink)
```

**Step 2: Run tests to verify they fail**

```powershell
cls ; python -m pytest tests/test_sinks.py -v --tb=short
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ceds_jsonld.sinks'`

**Step 3: Implement `src/ceds_jsonld/sinks.py`**

```python
"""Output sinks for streaming JSON-LD documents to storage.

Provides a :class:`Sink` protocol and two concrete implementations:

- :class:`NDJSONSink` — writes chunked NDJSON part files to local disk.
- :class:`ADLSink` — writes chunked NDJSON part files to Azure Data Lake
  Storage via ``fsspec`` + ``adlfs``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ceds_jsonld.logging import get_logger
from ceds_jsonld.serializer import dumps

_log = get_logger(__name__)


@dataclass
class SinkResult:
    """Summary returned when a sink is closed.

    Attributes:
        files_written: Number of part files created.
        records_written: Total records across all part files.
        bytes_written: Total bytes written across all part files.
        errors: Any non-fatal errors encountered during writes.
    """

    files_written: int = 0
    records_written: int = 0
    bytes_written: int = 0
    errors: list[str] = field(default_factory=list)


@runtime_checkable
class Sink(Protocol):
    """Protocol for output sinks that consume pipeline documents."""

    chunk_size: int

    def open(self) -> None: ...
    def write_chunk(self, docs: list[dict[str, Any]]) -> None: ...
    def close(self) -> SinkResult: ...


class NDJSONSink:
    """Write JSON-LD documents as chunked NDJSON part files to a local directory.

    Each call to :meth:`write_chunk` produces one ``part-NNNNN.ndjson`` file.
    Files use zero-padded 5-digit indices (``part-00000.ndjson``,
    ``part-00001.ndjson``, …) following Spark conventions.

    Args:
        path: Output directory path. Created on :meth:`open` if missing.
        chunk_size: Maximum records per part file. Used by
            :meth:`Pipeline.to_sink` to batch documents. Must be >= 1.
    """

    def __init__(self, path: str | Path, *, chunk_size: int = 10_000) -> None:
        if chunk_size < 1:
            msg = f"chunk_size must be >= 1, got {chunk_size}"
            raise ValueError(msg)
        self.path = Path(path)
        self.chunk_size = chunk_size
        self._part_index = 0
        self._total_bytes = 0
        self._total_records = 0

    def open(self) -> None:
        """Create the output directory."""
        self.path.mkdir(parents=True, exist_ok=True)
        _log.info("ndjson_sink.opened", path=str(self.path))

    def write_chunk(self, docs: list[dict[str, Any]]) -> None:
        """Write a batch of documents as one part file."""
        part_file = self.path / f"part-{self._part_index:05d}.ndjson"
        chunk_bytes = 0
        with part_file.open("wb") as fh:
            for doc in docs:
                line = dumps(doc, pretty=False) + b"\n"
                fh.write(line)
                chunk_bytes += len(line)
        self._total_bytes += chunk_bytes
        self._total_records += len(docs)
        self._part_index += 1
        _log.debug(
            "ndjson_sink.chunk_written",
            part=part_file.name,
            records=len(docs),
            bytes=chunk_bytes,
        )

    def close(self) -> SinkResult:
        """Return a summary of what was written."""
        _log.info(
            "ndjson_sink.closed",
            files=self._part_index,
            records=self._total_records,
            bytes=self._total_bytes,
        )
        return SinkResult(
            files_written=self._part_index,
            records_written=self._total_records,
            bytes_written=self._total_bytes,
        )
```

**Step 4: Run tests to verify they pass**

```powershell
cls ; python -m pytest tests/test_sinks.py -v --tb=short
```

Expected: all tests PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/sinks.py tests/test_sinks.py
git commit -m "feat(sinks): add Sink protocol, SinkResult, and NDJSONSink"
```

---

## Task 2: ADLSink

**Files:**
- Modify: `src/ceds_jsonld/sinks.py`
- Test: `tests/test_sinks.py` (append)

**Step 1: Write failing tests for ADLSink**

Append to `tests/test_sinks.py`:

```python
from unittest.mock import MagicMock, patch

from ceds_jsonld.sinks import ADLSink


class TestADLSinkImportGuard:
    def test_missing_fsspec_raises(self) -> None:
        """If fsspec is not installed, opening raises ImportError."""
        sink = ADLSink("abfss://container@account.dfs.core.windows.net/out")
        with patch.dict("sys.modules", {"fsspec": None}):
            with pytest.raises(ImportError, match="fsspec"):
                sink.open()


class TestADLSinkWriteChunk:
    def test_write_chunk_creates_part_files(self) -> None:
        """Mock fsspec filesystem, verify part files written correctly."""
        mock_fs = MagicMock()
        mock_fh = MagicMock()
        mock_fs.open.return_value.__enter__ = MagicMock(return_value=mock_fh)
        mock_fs.open.return_value.__exit__ = MagicMock(return_value=False)

        sink = ADLSink("abfss://c@a.dfs.core.windows.net/out", chunk_size=5)
        sink._fs = mock_fs  # inject mock

        docs = _make_docs(3)
        sink.write_chunk(docs)

        mock_fs.open.assert_called_once_with(
            "abfss://c@a.dfs.core.windows.net/out/part-00000.ndjson", "wb"
        )
        assert mock_fh.write.call_count == 3
        assert sink._part_index == 1

    def test_sink_result(self) -> None:
        """Verify SinkResult after writing."""
        mock_fs = MagicMock()
        mock_fh = MagicMock()
        mock_fs.open.return_value.__enter__ = MagicMock(return_value=mock_fh)
        mock_fs.open.return_value.__exit__ = MagicMock(return_value=False)

        sink = ADLSink("abfss://c@a.dfs.core.windows.net/out")
        sink._fs = mock_fs

        sink.write_chunk(_make_docs(2))
        result = sink.close()

        assert result.files_written == 1
        assert result.records_written == 2
        assert result.bytes_written > 0


class TestADLSinkValidation:
    def test_chunk_size_zero(self) -> None:
        with pytest.raises(ValueError, match="chunk_size must be >= 1"):
            ADLSink("abfss://c@a.dfs.core.windows.net/out", chunk_size=0)


class TestADLSinkProtocol:
    def test_satisfies_protocol(self) -> None:
        sink = ADLSink("abfss://c@a.dfs.core.windows.net/out")
        assert isinstance(sink, Sink)
```

**Step 2: Run tests to verify they fail**

```powershell
cls ; python -m pytest tests/test_sinks.py -v --tb=short
```

Expected: FAIL — `ImportError: cannot import name 'ADLSink' from 'ceds_jsonld.sinks'`

**Step 3: Implement ADLSink in `src/ceds_jsonld/sinks.py`**

Append to `sinks.py`:

```python
class ADLSink:
    """Write JSON-LD documents as chunked NDJSON part files to ADLS via fsspec.

    Requires ``fsspec`` and ``adlfs`` packages. Install with::

        pip install ceds-jsonld[adls]

    Args:
        path: ABFSS URI (e.g. ``abfss://container@account.dfs.core.windows.net/output``).
        chunk_size: Maximum records per part file. Must be >= 1.
        storage_options: Extra keyword arguments passed to
            ``fsspec.filesystem()``. Use for authentication (account key,
            SAS token, ``DefaultAzureCredential``, etc.).
    """

    def __init__(
        self,
        path: str,
        *,
        chunk_size: int = 10_000,
        storage_options: dict[str, Any] | None = None,
    ) -> None:
        if chunk_size < 1:
            msg = f"chunk_size must be >= 1, got {chunk_size}"
            raise ValueError(msg)
        self.path = path.rstrip("/")
        self.chunk_size = chunk_size
        self.storage_options = storage_options or {}
        self._fs: Any = None
        self._part_index = 0
        self._total_bytes = 0
        self._total_records = 0

    def open(self) -> None:
        """Initialize the fsspec filesystem and create the output directory."""
        try:
            import fsspec
        except ImportError as exc:
            msg = (
                "ADLSink requires fsspec and adlfs. "
                "Install with: pip install ceds-jsonld[adls]"
            )
            raise ImportError(msg) from exc
        self._fs = fsspec.filesystem("abfss", **self.storage_options)
        self._fs.mkdirs(self.path, exist_ok=True)
        _log.info("adl_sink.opened", path=self.path)

    def write_chunk(self, docs: list[dict[str, Any]]) -> None:
        """Write a batch of documents as one part file to ADLS."""
        part_path = f"{self.path}/part-{self._part_index:05d}.ndjson"
        chunk_bytes = 0
        with self._fs.open(part_path, "wb") as fh:
            for doc in docs:
                line = dumps(doc, pretty=False) + b"\n"
                fh.write(line)
                chunk_bytes += len(line)
        self._total_bytes += chunk_bytes
        self._total_records += len(docs)
        self._part_index += 1
        _log.debug(
            "adl_sink.chunk_written",
            part=f"part-{self._part_index - 1:05d}.ndjson",
            records=len(docs),
            bytes=chunk_bytes,
        )

    def close(self) -> SinkResult:
        """Return a summary of what was written."""
        _log.info(
            "adl_sink.closed",
            files=self._part_index,
            records=self._total_records,
            bytes=self._total_bytes,
        )
        return SinkResult(
            files_written=self._part_index,
            records_written=self._total_records,
            bytes_written=self._total_bytes,
        )
```

**Step 4: Run tests**

```powershell
cls ; python -m pytest tests/test_sinks.py -v --tb=short
```

Expected: all tests PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/sinks.py tests/test_sinks.py
git commit -m "feat(sinks): add ADLSink with fsspec/adlfs backend"
```

---

## Task 3: Pipeline.to_sink()

**Files:**
- Modify: `src/ceds_jsonld/pipeline.py` — add `to_sink()` method
- Test: `tests/test_sinks.py` (append)

**Step 1: Write failing tests for `Pipeline.to_sink()`**

Append to `tests/test_sinks.py`:

```python
from ceds_jsonld import Pipeline, DictAdapter


def _person_pipeline(
    data: list[dict[str, Any]],
    *,
    dead_letter_path: str | Path | None = None,
) -> Pipeline:
    """Create a minimal Person pipeline from dict data."""
    return Pipeline(
        source=DictAdapter(data),
        shape="person",
        base_uri="https://example.org/",
        dead_letter_path=dead_letter_path,
    )


class TestPipelineToSink:
    def test_end_to_end(self, tmp_path: Path) -> None:
        """Full Pipeline.to_sink(NDJSONSink) with 15 records, chunk_size=10."""
        data = [
            {"PersonId": str(i), "FirstName": f"First{i}", "LastName": f"Last{i}"}
            for i in range(15)
        ]
        pipe = _person_pipeline(data)
        sink = NDJSONSink(tmp_path / "out", chunk_size=10)
        result = pipe.to_sink(sink)

        assert result.records_out == 15
        assert result.records_in == 15
        assert result.records_failed == 0
        assert result.bytes_written > 0
        files = sorted((tmp_path / "out").glob("part-*.ndjson"))
        assert len(files) == 2  # 10 + 5

    def test_dlq_integration(self, tmp_path: Path) -> None:
        """Poison row goes to DLQ; good rows land in sink."""
        good = [{"PersonId": "1", "FirstName": "A", "LastName": "B"}]
        # A row missing PersonId will fail build (missing @id source)
        bad = [{"FirstName": "Bad", "LastName": "Row"}]
        data = good + bad + good  # 3 records, 1 bad

        dlq = tmp_path / "dlq.ndjson"
        pipe = _person_pipeline(data, dead_letter_path=dlq)
        sink = NDJSONSink(tmp_path / "out", chunk_size=100)
        result = pipe.to_sink(sink)

        assert result.records_out == 2
        assert result.records_failed == 1
        assert result.dead_letter_path is not None

    def test_result_counts(self, tmp_path: Path) -> None:
        """PipelineResult reflects sink's bytes_written."""
        data = [
            {"PersonId": str(i), "FirstName": f"First{i}", "LastName": f"Last{i}"}
            for i in range(5)
        ]
        pipe = _person_pipeline(data)
        sink = NDJSONSink(tmp_path / "out", chunk_size=100)
        result = pipe.to_sink(sink)

        assert result.records_in == 5
        assert result.records_out == 5
        assert result.bytes_written > 0
        assert result.elapsed_seconds > 0
        assert result.records_per_second > 0
```

**Step 2: Run tests to verify they fail**

```powershell
cls ; python -m pytest tests/test_sinks.py::TestPipelineToSink -v --tb=short
```

Expected: FAIL — `AttributeError: 'Pipeline' object has no attribute 'to_sink'`

**Step 3: Implement `to_sink()` on Pipeline**

Add to `src/ceds_jsonld/pipeline.py` after the `to_ndjson` method (around line 700):

```python
def to_sink(self, sink: Any) -> PipelineResult:
    """Stream documents to an output sink with automatic chunking.

    Iterates the source adapter, maps and builds each row, accumulates
    documents into batches of ``sink.chunk_size``, and writes each
    batch via ``sink.write_chunk()``.

    Args:
        sink: Any object satisfying the :class:`~ceds_jsonld.sinks.Sink`
            protocol (e.g. :class:`~ceds_jsonld.sinks.NDJSONSink`,
            :class:`~ceds_jsonld.sinks.ADLSink`).

    Returns:
        A :class:`PipelineResult` with timing, counts, and the sink's
        byte total.

    Raises:
        PipelineError: On adapter, mapping, build, or sink failures.
    """
    t0 = time.perf_counter()
    try:
        sink.open()
    except Exception as exc:
        msg = f"Failed to open sink: {exc}"
        raise PipelineError(msg) from exc

    chunk: list[dict[str, Any]] = []
    records_in = 0
    records_out = 0
    dead = _DeadLetterWriter(self._dead_letter_path)

    try:
        for raw_row in self._source.read():
            records_in += 1
            try:
                mapped = self._mapper.map(raw_row)
                doc = self._builder.build_one(mapped)
            except Exception as exc:
                if self._dead_letter_path is not None:
                    _log.warning("pipeline.row_failed", row=records_in, error=str(exc))
                    dead.write(raw_row, str(exc))
                    continue
                raise PipelineError(
                    f"Pipeline to_sink failed at row {records_in}: {exc}"
                ) from exc

            chunk.append(doc)
            records_out += 1
            if len(chunk) >= sink.chunk_size:
                sink.write_chunk(chunk)
                chunk = []

        if chunk:
            sink.write_chunk(chunk)

    except PipelineError:
        raise
    except Exception as exc:
        msg = f"Pipeline to_sink failed: {exc}"
        raise PipelineError(msg) from exc
    finally:
        dead.close()

    try:
        sink_result = sink.close()
    except Exception as exc:
        msg = f"Failed to close sink: {exc}"
        raise PipelineError(msg) from exc

    elapsed = time.perf_counter() - t0
    rps = records_out / elapsed if elapsed > 0 else 0.0
    result = PipelineResult(
        records_in=records_in,
        records_out=records_out,
        records_failed=dead.count,
        elapsed_seconds=round(elapsed, 3),
        records_per_second=round(rps, 1),
        bytes_written=sink_result.bytes_written,
        dead_letter_path=str(self._dead_letter_path) if dead.count > 0 else None,
    )
    _log.info(
        "pipeline.to_sink",
        sink=type(sink).__name__,
        records=records_out,
        files=sink_result.files_written,
        bytes=sink_result.bytes_written,
        elapsed=result.elapsed_seconds,
    )
    return result
```

**Step 4: Run tests**

```powershell
cls ; python -m pytest tests/test_sinks.py -v --tb=short
```

Expected: all tests PASS

**Step 5: Commit**

```powershell
git add src/ceds_jsonld/pipeline.py tests/test_sinks.py
git commit -m "feat(pipeline): add to_sink() method for chunked streaming output"
```

---

## Task 4: Exports and optional dependency

**Files:**
- Modify: `src/ceds_jsonld/__init__.py` — add exports
- Modify: `pyproject.toml` — add `[adls]` optional dependency
- Test: `tests/test_sinks.py` (append)

**Step 1: Write failing test for top-level imports**

Append to `tests/test_sinks.py`:

```python
class TestSinkExports:
    def test_importable_from_top_level(self) -> None:
        from ceds_jsonld import ADLSink, NDJSONSink, Sink, SinkResult

        assert Sink is not None
        assert SinkResult is not None
        assert NDJSONSink is not None
        assert ADLSink is not None
```

**Step 2: Run to verify it fails**

```powershell
cls ; python -m pytest tests/test_sinks.py::TestSinkExports -v --tb=short
```

Expected: FAIL — `ImportError: cannot import name 'Sink' from 'ceds_jsonld'`

**Step 3: Add exports to `__init__.py`**

Add to imports section:

```python
from ceds_jsonld.sinks import ADLSink, NDJSONSink, Sink, SinkResult
```

Add to `__all__`:

```python
"ADLSink",
"NDJSONSink",
"Sink",
"SinkResult",
```

**Step 4: Add `[adls]` to `pyproject.toml`**

After the `database` line in `[project.optional-dependencies]`:

```toml
adls = ["fsspec>=2023.1.0", "adlfs>=2023.1.0"]
```

Also add to the `all` extra and `dev` extra:

```toml
"fsspec>=2023.1.0",
"adlfs>=2023.1.0",
```

**Step 5: Run all sink tests**

```powershell
cls ; python -m pytest tests/test_sinks.py -v --tb=short
```

Expected: all tests PASS

**Step 6: Commit**

```powershell
git add src/ceds_jsonld/__init__.py pyproject.toml tests/test_sinks.py
git commit -m "feat(sinks): export Sink/SinkResult/NDJSONSink/ADLSink, add [adls] dependency"
```

---

## Task 5: Full test suite + mypy

**Step 1: Run mypy**

```powershell
cls ; python -m mypy src/
```

Expected: no new errors

**Step 2: Run full test suite**

```powershell
cls ; python -m pytest tests/ -v --tb=short
```

Expected: all tests PASS (1015 + ~12 new ≈ 1027)

**Step 3: Commit any fixes if needed**

---

## Task 6: Merge to dev and clean up

**Step 1: Merge to dev**

```powershell
$env:GIT_EDITOR = "true"
git checkout dev ; git merge --no-ff feature/output-sinks
```

**Step 2: Push dev**

```powershell
git push origin dev
```

**Step 3: Delete topic branch**

```powershell
git branch -d feature/output-sinks ; git push origin --delete feature/output-sinks
```
