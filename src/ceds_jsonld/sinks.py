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


class ADLSink:
    """Write JSON-LD documents as chunked NDJSON part files to ADLS via fsspec.

    Requires ``fsspec`` and ``adlfs`` packages. Install with::

        pip install ceds-jsonld[adls]

    Args:
        path: ABFSS URI
            (e.g. ``abfss://container@account.dfs.core.windows.net/output``).
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
            import fsspec  # type: ignore[import-untyped]
        except ImportError as exc:
            msg = "ADLSink requires fsspec and adlfs. Install with: pip install ceds-jsonld[adls]"
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
