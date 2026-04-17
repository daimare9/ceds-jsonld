"""Output sinks for streaming JSON-LD documents to storage.

Provides a :class:`Sink` protocol and two concrete implementations:

- :class:`NDJSONSink` — writes chunked NDJSON part files to local disk.
- :class:`ADLSink` — writes chunked NDJSON part files to Azure Data Lake
  Storage via ``fsspec`` + ``adlfs``.

Write modes (modelled after Spark's ``DataFrameWriter.mode()``):

- ``"error"`` — raise if the output directory already contains part files (default).
- ``"overwrite"`` — delete the entire output directory and recreate it fresh.
- ``"append"`` — continue numbering from the highest existing part index.
"""

from __future__ import annotations

import os
import re
import shutil
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ceds_jsonld.logging import get_logger
from ceds_jsonld.serializer import dumps

_log = get_logger(__name__)

_VALID_MODES = frozenset({"error", "overwrite", "append"})
_PART_RE = re.compile(r"^part-(\d{5})\.ndjson$")


class WriteMode(StrEnum):
    """Write mode for output sinks, following Spark conventions.

    Attributes:
        ERROR: Raise ``FileExistsError`` if the output directory already
            contains part files. This is the safe default.
        OVERWRITE: Delete the entire output directory and recreate it,
            matching Spark's ``mode("overwrite")`` behaviour.
        APPEND: Continue numbering from the highest existing part index + 1.
    """

    ERROR = "error"
    OVERWRITE = "overwrite"
    APPEND = "append"


def _resolve_workers(workers: int | str) -> int:
    """Convert *workers* parameter to a concrete int."""
    if isinstance(workers, str):
        if workers != "auto":
            msg = f"workers must be a positive int or 'auto', got {workers!r}"
            raise ValueError(msg)
        return os.cpu_count() or 4
    if workers < 1:
        msg = f"workers must be >= 1, got {workers}"
        raise ValueError(msg)
    return workers


def _validate_mode(mode: str) -> str:
    if mode not in _VALID_MODES:
        msg = f"mode must be one of {sorted(_VALID_MODES)}, got {mode!r}"
        raise ValueError(msg)
    return mode


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
    mode: str

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
        mode: Write mode — ``"error"`` (default), ``"overwrite"``, or
            ``"append"``. See :class:`WriteMode`.
        workers: Number of threads for parallel file writes. ``1`` (default)
            runs single-threaded with no executor overhead.  ``"auto"``
            uses ``os.cpu_count()``.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        chunk_size: int = 10_000,
        mode: str = "error",
        workers: int | str = 1,
    ) -> None:
        if chunk_size < 1:
            msg = f"chunk_size must be >= 1, got {chunk_size}"
            raise ValueError(msg)
        self.path = Path(path)
        self.chunk_size = chunk_size
        self.mode = _validate_mode(mode)
        self.workers = _resolve_workers(workers)
        self._part_index = 0
        self._total_bytes = 0
        self._total_records = 0
        self._executor: ThreadPoolExecutor | None = None
        self._futures: list[Future[tuple[int, int]]] = []

    def open(self) -> None:
        """Create the output directory, applying the selected write mode."""
        self.path.mkdir(parents=True, exist_ok=True)
        existing = [f for f in self.path.iterdir() if _PART_RE.match(f.name)]

        if self.mode == "error" and existing:
            msg = (
                f"Directory {self.path} already contains {len(existing)} part file(s). "
                f"Use mode='overwrite' or mode='append'."
            )
            raise FileExistsError(msg)

        if self.mode == "overwrite":
            # Spark-style: nuke the entire directory and recreate it fresh
            shutil.rmtree(self.path)
            self.path.mkdir(parents=True, exist_ok=True)

        if self.mode == "append" and existing:
            max_idx = max(
                int(_PART_RE.match(f.name).group(1))  # type: ignore[union-attr]
                for f in existing
            )
            self._part_index = max_idx + 1

        if self.workers > 1:
            self._executor = ThreadPoolExecutor(max_workers=self.workers)

        _log.info("ndjson_sink.opened", path=str(self.path), mode=self.mode, workers=self.workers)

    def _write_part(self, part_file: Path, docs: list[dict[str, Any]]) -> tuple[int, int]:
        """Serialize and write docs to a single part file. Returns (records, bytes)."""
        chunk_bytes = 0
        with part_file.open("wb") as fh:
            for doc in docs:
                line = dumps(doc, pretty=False) + b"\n"
                fh.write(line)
                chunk_bytes += len(line)
        return len(docs), chunk_bytes

    def write_chunk(self, docs: list[dict[str, Any]]) -> None:
        """Write a batch of documents as one part file."""
        part_file = self.path / f"part-{self._part_index:05d}.ndjson"
        self._part_index += 1

        if self._executor is not None:
            future = self._executor.submit(self._write_part, part_file, docs)
            self._futures.append(future)
        else:
            records, chunk_bytes = self._write_part(part_file, docs)
            self._total_bytes += chunk_bytes
            self._total_records += records
            _log.debug(
                "ndjson_sink.chunk_written",
                part=part_file.name,
                records=records,
                bytes=chunk_bytes,
            )

    def close(self) -> SinkResult:
        """Wait for pending writes, write ``_SUCCESS`` marker, and return summary."""
        errors: list[str] = []
        if self._executor is not None:
            for future in self._futures:
                try:
                    records, chunk_bytes = future.result()
                    self._total_records += records
                    self._total_bytes += chunk_bytes
                except Exception as exc:
                    errors.append(str(exc))
            self._executor.shutdown(wait=True)
            self._executor = None
            self._futures.clear()

        # Write _SUCCESS marker
        (self.path / "_SUCCESS").write_bytes(b"")

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
            errors=errors,
        )


class ADLSink:
    """Write JSON-LD documents as chunked NDJSON part files to ADLS via fsspec.

    Requires ``fsspec`` and ``adlfs`` packages. Install with::

        pip install ceds-jsonld[adls]

    Args:
        path: ABFSS URI
            (e.g. ``abfss://container@account.dfs.core.windows.net/output``).
        chunk_size: Maximum records per part file. Must be >= 1.
        mode: Write mode — ``"error"`` (default), ``"overwrite"``, or
            ``"append"``. See :class:`WriteMode`.
        workers: Number of threads for parallel file writes. ``1`` (default)
            runs single-threaded. ``"auto"`` uses ``os.cpu_count()``.
        storage_options: Extra keyword arguments passed to
            ``fsspec.filesystem()``. Use for authentication (account key,
            SAS token, ``DefaultAzureCredential``, etc.).
    """

    def __init__(
        self,
        path: str,
        *,
        chunk_size: int = 10_000,
        mode: str = "error",
        workers: int | str = 1,
        storage_options: dict[str, Any] | None = None,
    ) -> None:
        if chunk_size < 1:
            msg = f"chunk_size must be >= 1, got {chunk_size}"
            raise ValueError(msg)
        self.path = path.rstrip("/")
        self.chunk_size = chunk_size
        self.mode = _validate_mode(mode)
        self.workers = _resolve_workers(workers)
        self.storage_options = storage_options or {}
        self._fs: Any = None
        self._part_index = 0
        self._total_bytes = 0
        self._total_records = 0
        self._executor: ThreadPoolExecutor | None = None
        self._futures: list[Future[tuple[int, int]]] = []

    def open(self) -> None:
        """Initialize the fsspec filesystem and apply write mode."""
        try:
            import fsspec  # type: ignore[import-untyped]
        except ImportError as exc:
            msg = "ADLSink requires fsspec and adlfs. Install with: pip install ceds-jsonld[adls]"
            raise ImportError(msg) from exc
        self._fs = fsspec.filesystem("abfss", **self.storage_options)
        self._fs.mkdirs(self.path, exist_ok=True)

        # List existing part files
        try:
            all_files = self._fs.ls(self.path, detail=False)
        except FileNotFoundError:
            all_files = []
        existing = [f for f in all_files if _PART_RE.match(f.rsplit("/", 1)[-1])]

        if self.mode == "error" and existing:
            msg = (
                f"Directory {self.path} already contains {len(existing)} part file(s). "
                f"Use mode='overwrite' or mode='append'."
            )
            raise FileExistsError(msg)

        if self.mode == "overwrite":
            # Spark-style: nuke the entire remote directory and recreate
            try:
                self._fs.rm(self.path, recursive=True)
            except FileNotFoundError:
                pass
            self._fs.mkdirs(self.path, exist_ok=True)

        if self.mode == "append" and existing:
            max_idx = max(
                int(_PART_RE.match(f.rsplit("/", 1)[-1]).group(1))  # type: ignore[union-attr]
                for f in existing
            )
            self._part_index = max_idx + 1

        if self.workers > 1:
            self._executor = ThreadPoolExecutor(max_workers=self.workers)

        _log.info("adl_sink.opened", path=self.path, mode=self.mode, workers=self.workers)

    def _write_part(self, part_path: str, docs: list[dict[str, Any]]) -> tuple[int, int]:
        """Serialize and write docs to a single part file. Returns (records, bytes)."""
        chunk_bytes = 0
        with self._fs.open(part_path, "wb") as fh:
            for doc in docs:
                line = dumps(doc, pretty=False) + b"\n"
                fh.write(line)
                chunk_bytes += len(line)
        return len(docs), chunk_bytes

    def write_chunk(self, docs: list[dict[str, Any]]) -> None:
        """Write a batch of documents as one part file to ADLS."""
        part_path = f"{self.path}/part-{self._part_index:05d}.ndjson"
        self._part_index += 1

        if self._executor is not None:
            future = self._executor.submit(self._write_part, part_path, docs)
            self._futures.append(future)
        else:
            records, chunk_bytes = self._write_part(part_path, docs)
            self._total_bytes += chunk_bytes
            self._total_records += records
            _log.debug(
                "adl_sink.chunk_written",
                part=part_path.rsplit("/", 1)[-1],
                records=records,
                bytes=chunk_bytes,
            )

    def close(self) -> SinkResult:
        """Wait for pending writes, write ``_SUCCESS`` marker, and return summary."""
        errors: list[str] = []
        if self._executor is not None:
            for future in self._futures:
                try:
                    records, chunk_bytes = future.result()
                    self._total_records += records
                    self._total_bytes += chunk_bytes
                except Exception as exc:
                    errors.append(str(exc))
            self._executor.shutdown(wait=True)
            self._executor = None
            self._futures.clear()

        # Write _SUCCESS marker
        with self._fs.open(f"{self.path}/_SUCCESS", "wb") as fh:
            fh.write(b"")

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
            errors=errors,
        )
