"""Pipeline — end-to-end orchestration of ingest → map → build → serialize.

The Pipeline connects a :class:`SourceAdapter` to the existing FieldMapper →
JSONLDBuilder → serializer chain, providing both streaming and batch APIs.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ceds_jsonld.adapters.base import SourceAdapter
from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.cosmos.prepare import sanitize_cosmos_id
from ceds_jsonld.exceptions import PipelineError, ValidationError
from ceds_jsonld.logging import get_logger
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.registry import ShapeDefinition, ShapeRegistry
from ceds_jsonld.sanitize import validate_base_uri
from ceds_jsonld.serializer import dumps
from ceds_jsonld.validator import (
    PreBuildValidator,
    SHACLValidator,
    ValidationMode,
    ValidationResult,
)

_log = get_logger(__name__)


# ------------------------------------------------------------------
# Multiprocessing worker (module-level for pickle)
# ------------------------------------------------------------------


def _pipeline_worker(
    chunk: list[dict[str, Any]],
    part_index: int,
    output_path: str,
    mapping_config: dict[str, Any],
    shape_name: str,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Process one chunk: map → build → serialize → write part file.

    Runs in a child process. Reconstructs FieldMapper and JSONLDBuilder
    from pickle-safe config dicts (no filesystem or Path objects needed).

    Returns:
        (records_written, bytes_written, dead_letters) where dead_letters
        is a list of ``{"_error": ..., "_record": ...}`` dicts for rows
        that failed mapping or building.
    """
    mapper = FieldMapper(mapping_config)
    # Build a minimal ShapeDefinition for JSONLDBuilder — it only reads
    # mapping_config and name from the shape.
    shape_def = ShapeDefinition(
        name=shape_name,
        base_dir=Path("."),
        shacl_path=Path("."),
        context={},
        mapping_config=mapping_config,
    )
    builder = JSONLDBuilder(shape_def)

    part_file = Path(output_path) / f"part-{part_index:05d}.ndjson"
    total_bytes = 0
    records_written = 0
    dead_letters: list[dict[str, Any]] = []

    with part_file.open("wb") as fh:
        for raw_row in chunk:
            try:
                mapped = mapper.map(raw_row)
                doc = builder.build_one(mapped)
                line = dumps(doc, pretty=False) + b"\n"
                fh.write(line)
                total_bytes += len(line)
                records_written += 1
            except Exception as exc:
                dead_letters.append({"_error": str(exc), "_record": raw_row})

    return records_written, total_bytes, dead_letters


def _resolve_pipeline_workers(workers: int | str) -> int:
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


# ------------------------------------------------------------------
# Progress callback protocol
# ------------------------------------------------------------------

# Users may supply a progress callback matching this signature:
#   def on_progress(current: int, total: int | None) -> None: ...
ProgressCallback = Callable[[int, int | None], None]


def _try_tqdm(total: int | None = None, desc: str = "Processing") -> Any:
    """Return a tqdm progress bar if available, else ``None``."""
    try:
        from tqdm import tqdm

        return tqdm(total=total, desc=desc, unit="rec")
    except ImportError:
        return None


# ------------------------------------------------------------------
# Pipeline result / metrics
# ------------------------------------------------------------------


@dataclass
class PipelineResult:
    """Metrics collected during a pipeline run.

    Attributes:
        records_in: Number of raw records read from the adapter.
        records_out: Number of JSON-LD documents successfully produced.
        records_failed: Number of records that failed mapping/building.
        elapsed_seconds: Wall-clock time for the run.
        records_per_second: Throughput (``records_out / elapsed_seconds``).
        bytes_written: Bytes written to output (for file-output methods).
        dead_letter_path: Path to the dead-letter NDJSON file, if any
            records were sent there.
    """

    records_in: int = 0
    records_out: int = 0
    records_failed: int = 0
    elapsed_seconds: float = 0.0
    records_per_second: float = 0.0
    bytes_written: int = 0
    dead_letter_path: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)


# ------------------------------------------------------------------
# Dead-letter writer
# ------------------------------------------------------------------


class _DeadLetterWriter:
    """Write failed records to an NDJSON file for later reprocessing.

    Opens the file lazily on the first failure so no file is created
    if there are zero errors.
    """

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._fh: Any = None
        self._count = 0

    def write(self, raw_row: dict[str, Any], error: str) -> None:
        """Write a failed record with its error to the dead-letter file.

        Uses a fallback serialization strategy: if the raw_row contains
        non-JSON-serializable types (set, datetime, custom objects), the
        values are coerced to strings via ``repr()`` so the DLQ writer
        never itself becomes a crash source.
        """
        if self._path is None:
            return
        if self._fh is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("wb")
            _log.info("dead_letter.opened", path=str(self._path))
        entry = {"_error": error, "_record": raw_row}
        try:
            data = dumps(entry, pretty=False)
        except Exception:
            # Fallback: coerce non-serializable values to repr strings
            import json as _json

            safe_row = {
                k: repr(v) if not isinstance(v, (str, int, float, bool, type(None))) else v for k, v in raw_row.items()
            }
            safe_entry = {"_error": error, "_record": safe_row, "_serialization_fallback": True}
            data = _json.dumps(safe_entry, ensure_ascii=False, default=str).encode("utf-8")
        self._fh.write(data + b"\n")
        self._count += 1

    @property
    def count(self) -> int:
        return self._count

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
            _log.info("dead_letter.closed", path=str(self._path), records=self._count)


class Pipeline:
    """Orchestrate data ingestion, mapping, building, and serialization.

    Example:
        >>> from ceds_jsonld.adapters import CSVAdapter
        >>> adapter = CSVAdapter("students.csv")
        >>> pipeline = Pipeline(source=adapter, shape="person", registry=registry)
        >>> for doc in pipeline.stream():
        ...     print(doc["@id"])
        >>> pipeline.to_json("output/students.json")
    """

    def __init__(
        self,
        source: SourceAdapter,
        shape: str,
        registry: ShapeRegistry,
        *,
        custom_transforms: dict[str, Callable[..., Any]] | None = None,
        source_overrides: dict[str, dict[str, str]] | None = None,
        transform_overrides: dict[str, dict[str, str]] | None = None,
        id_source: str | None = None,
        id_transform: str | None = None,
        progress: bool | ProgressCallback = False,
        dead_letter_path: str | Path | None = None,
        inject_cosmos_id: bool = False,
    ) -> None:
        """Initialize the pipeline.

        Args:
            source: A configured :class:`SourceAdapter` that yields raw dicts.
            shape: Shape name registered in the registry (e.g. ``"person"``).
            registry: A :class:`ShapeRegistry` with the requested shape loaded.
            custom_transforms: Optional user-defined transforms forwarded to
                :class:`FieldMapper`.
            source_overrides: Override source column names per property. Example::

                {"hasPersonName": {"FirstName": "FIRST_NM", "LastOrSurname": "LAST_NM"}}

            transform_overrides: Override transform functions per property. Example::

                {"hasPersonSexGender": {"hasSex": "my_custom_fn"}}

            id_source: Override the source column used for document ``@id``.
            id_transform: Override the transform applied to the ``@id`` value.
            progress: Enable progress tracking.  ``True`` uses tqdm (if
                installed) or silent operation.  A callable receives
                ``(current_count, total_or_none)`` on each record.
            dead_letter_path: If set, records that fail mapping or building
                are written to this NDJSON file instead of raising.  The
                pipeline continues processing remaining records.
            inject_cosmos_id: If ``True``, each document produced by this
                pipeline will have a Cosmos DB-safe ``id`` field injected,
                derived from the document's ``@id`` with ``/`` replaced by
                ``|``.  Useful when consuming the JSON-LD output outside of
                :class:`CosmosLoader` (e.g. a custom upload script or another
                sink).
        """
        self._source = source
        self._shape_name = shape
        self._registry = registry
        self._custom_transforms = custom_transforms
        self._progress = progress
        self._dead_letter_path = Path(dead_letter_path) if dead_letter_path else None
        self._inject_cosmos_id = inject_cosmos_id

        # Resolve shape artifacts eagerly so config errors surface early.
        try:
            self._shape_def = registry.get_shape(shape)
        except Exception as exc:
            msg = f"Shape '{shape}' not found in registry"
            raise PipelineError(msg) from exc

        # Validate base_uri at the Pipeline level for an early, clear error
        # message before the FieldMapper or Builder see the config.
        # Skip validation when id_is_uri — the source supplies complete URIs.
        id_is_uri = self._shape_def.mapping_config.get("id_is_uri", False)
        base_uri = self._shape_def.mapping_config.get("base_uri", "")
        if base_uri and not id_is_uri:
            try:
                validate_base_uri(base_uri)
            except ValueError as exc:
                msg = (
                    f"Shape '{shape}' has an invalid base_uri: {exc}. "
                    f"The base_uri must end with '/' or '#' to separate the "
                    f"namespace from the identifier (e.g. 'cepi:person/')."
                )
                raise PipelineError(msg) from exc

        self._mapper = FieldMapper(
            self._shape_def.mapping_config,
            custom_transforms=custom_transforms,
        )

        # Apply source/transform overrides if provided.
        has_overrides = any(
            [
                source_overrides,
                transform_overrides,
                id_source is not None,
                id_transform is not None,
            ]
        )
        if has_overrides:
            self._mapper = self._mapper.with_overrides(
                source_overrides=source_overrides,
                transform_overrides=transform_overrides,
                id_source=id_source,
                id_transform=id_transform,
            )

        self._builder = JSONLDBuilder(self._shape_def)
        self._pre_validator = PreBuildValidator(self._mapper._config)

        _log.info("pipeline.initialized", shape=shape, adapter=type(source).__name__)

    # ------------------------------------------------------------------
    # Validation API
    # ------------------------------------------------------------------

    def validate(
        self,
        *,
        mode: str | ValidationMode = "report",
        sample_rate: float = 0.01,
        shacl: bool = False,
    ) -> ValidationResult:
        """Validate all source records and optionally the built JSON-LD.

        Runs pre-build validation on every raw row.  When ``shacl=True``,
        also performs full SHACL round-trip validation on the built documents
        (expensive — uses sample-based checking by default).

        Args:
            mode: ``"strict"``, ``"report"``, or ``"sample"``.  Controls
                failure behaviour.  Can be a string or ``ValidationMode`` enum.
            sample_rate: Fraction of records to SHACL-validate in sample mode
                (default 1 %).  Pre-build validation always checks 100 %.
            shacl: If ``True``, also run full pySHACL validation on the
                built documents.

        Returns:
            A :class:`~ceds_jsonld.validator.ValidationResult` with any issues.

        Raises:
            PipelineError: On adapter or build failures.
            ValidationError: In strict mode, on the first validation error.
        """
        if isinstance(mode, str):
            mode = ValidationMode(mode)

        from ceds_jsonld import __version__

        result = ValidationResult(
            shape_name=self._shape_name,
            source_name=type(self._source).__name__,
            library_version=__version__,
        )

        # Phase 1: pre-build validation on raw rows
        raw_rows: list[dict[str, Any]] = []
        try:
            for raw_row in self._source.read():
                raw_rows.append(raw_row)
                row_result = self._pre_validator.validate_row(
                    raw_row,
                    mode=ValidationMode.STRICT if mode is ValidationMode.STRICT else ValidationMode.REPORT,
                )
                result.record_count += 1
                if not row_result.conforms:
                    result.conforms = False
                for rec_id, issues in row_result.issues.items():
                    for issue in issues:
                        result.add_issue(rec_id, issue)
        except ValidationError:
            raise
        except PipelineError:
            raise
        except Exception as exc:
            msg = f"Validation failed during data reading: {exc}"
            raise PipelineError(msg) from exc

        # Phase 2: optional SHACL validation on built docs
        if shacl and result.conforms:
            try:
                shacl_validator = SHACLValidator(
                    self._shape_def.shacl_path,
                    context=self._shape_def.context,
                )
            except Exception as exc:
                msg = f"Failed to initialise SHACL validator: {exc}"
                raise PipelineError(msg) from exc

            docs: list[dict[str, Any]] = []
            for raw_row in raw_rows:
                mapped = self._mapper.map(raw_row)
                doc = self._builder.build_one(mapped)
                docs.append(doc)

            shacl_result = shacl_validator.validate_batch(
                docs,
                mode=mode,
                sample_rate=sample_rate,
            )
            result.error_count += shacl_result.error_count
            result.warning_count += shacl_result.warning_count
            if not shacl_result.conforms:
                result.conforms = False
            for rec_id, issues in shacl_result.issues.items():
                for issue in issues:
                    result.add_issue(rec_id, issue)
            if shacl_result.raw_report:
                result.raw_report = shacl_result.raw_report

        return result

    # ------------------------------------------------------------------
    # Streaming API
    # ------------------------------------------------------------------

    def stream(
        self,
        *,
        validate: bool = False,
        validation_mode: str | ValidationMode = "report",
    ) -> Iterator[dict[str, Any]]:
        """Yield fully-built JSON-LD documents one at a time.

        Each raw row from the adapter is mapped, then built into a JSON-LD
        document.  Memory usage stays constant regardless of dataset size.

        When a ``dead_letter_path`` was configured on the Pipeline, rows that
        fail mapping or building are written there instead of raising.

        Args:
            validate: If ``True``, run pre-build validation on each row
                before mapping.  Invalid rows raise ``ValidationError`` in
                strict mode or are skipped (with a warning logged) in report
                mode.
            validation_mode: ``"strict"`` or ``"report"``.  Only used when
                ``validate=True``.

        Yields:
            JSON-LD documents as plain Python dicts.

        Raises:
            PipelineError: On adapter, mapping, or build failures.
            ValidationError: In strict mode when a row fails validation.
        """
        if isinstance(validation_mode, str):
            validation_mode = ValidationMode(validation_mode)

        # Try to get a record count for progress tracking
        total = self._source.count() if hasattr(self._source, "count") else None
        pbar = None
        user_cb: ProgressCallback | None = None

        if self._progress is True:
            pbar = _try_tqdm(total=total, desc=f"Building {self._shape_name}")
        elif callable(self._progress):
            user_cb = self._progress

        dead = _DeadLetterWriter(self._dead_letter_path)
        count = 0

        try:
            for raw_row in self._source.read():
                count += 1

                if validate:
                    row_result = self._pre_validator.validate_row(
                        raw_row,
                        mode=validation_mode,
                    )
                    if not row_result.conforms and validation_mode is not ValidationMode.STRICT:
                        _log.warning("pipeline.row_skipped", row=count, reason="validation")
                        dead.write(raw_row, "pre-build validation failed")
                        if pbar is not None:
                            pbar.update(1)
                        if user_cb is not None:
                            user_cb(count, total)
                        continue

                try:
                    mapped = self._mapper.map(raw_row)
                    doc = self._builder.build_one(mapped)
                except Exception as exc:
                    if self._dead_letter_path is not None:
                        _log.warning("pipeline.row_failed", row=count, error=str(exc))
                        dead.write(raw_row, str(exc))
                        if pbar is not None:
                            pbar.update(1)
                        if user_cb is not None:
                            user_cb(count, total)
                        continue
                    raise PipelineError(f"Pipeline stream failed at row {count}: {exc}") from exc

                if self._inject_cosmos_id and "@id" in doc:
                    doc["id"] = sanitize_cosmos_id(doc["@id"])

                if pbar is not None:
                    pbar.update(1)
                if user_cb is not None:
                    user_cb(count, total)
                yield doc

        except (PipelineError, ValidationError):
            raise
        except Exception as exc:
            msg = f"Pipeline stream failed: {exc}"
            raise PipelineError(msg) from exc
        finally:
            dead.close()
            if pbar is not None:
                pbar.close()

    # ------------------------------------------------------------------
    # Batch API
    # ------------------------------------------------------------------

    def build_all(
        self,
        *,
        validate: bool = False,
        validation_mode: str | ValidationMode = "report",
    ) -> list[dict[str, Any]]:
        """Build all JSON-LD documents in memory.

        Suitable for datasets that fit in memory.  For larger datasets,
        use :meth:`stream`, :meth:`to_json`, or :meth:`to_ndjson` instead.

        Args:
            validate: If ``True``, run pre-build validation on each row
                before mapping.  See :meth:`stream` for behaviour details.
            validation_mode: ``"strict"`` or ``"report"``.

        Returns:
            List of JSON-LD documents.
        """
        docs = list(self.stream(validate=validate, validation_mode=validation_mode))

        # Warn when duplicate @id values are detected — these cause overwrites
        # in downstream systems like Cosmos DB.
        seen: dict[str, int] = {}
        for doc in docs:
            doc_id = doc.get("@id", "")
            seen[doc_id] = seen.get(doc_id, 0) + 1

        dupes = {k: v for k, v in seen.items() if v > 1}
        if dupes:
            total_dupes = sum(v - 1 for v in dupes.values())
            _log.warning(
                "pipeline.duplicate_ids",
                unique_duplicated=len(dupes),
                total_extra=total_dupes,
                sample=list(dupes.keys())[:5],
            )

        return docs

    def run(
        self,
        *,
        validate: bool = False,
        validation_mode: str | ValidationMode = "report",
    ) -> PipelineResult:
        """Build all documents and return metrics about the run.

        Like :meth:`build_all` but returns a :class:`PipelineResult` instead
        of the raw documents.  The built documents are discarded — use this
        when you only care about throughput metrics or validation, or combine
        with ``to_json()``/``to_ndjson()`` for file output with metrics.

        Args:
            validate: If ``True``, run pre-build validation.
            validation_mode: ``"strict"`` or ``"report"``.

        Returns:
            A :class:`PipelineResult` with timing, counts, and throughput.
        """
        t0 = time.perf_counter()
        records_in = 0
        records_out = 0
        dead = _DeadLetterWriter(self._dead_letter_path)
        result_errors: list[dict[str, Any]] = []

        try:
            for raw_row in self._source.read():
                records_in += 1
                try:
                    if validate:
                        vmode = (
                            validation_mode
                            if isinstance(validation_mode, ValidationMode)
                            else ValidationMode(validation_mode)
                        )
                        row_result = self._pre_validator.validate_row(raw_row, mode=vmode)
                        if not row_result.conforms and vmode is not ValidationMode.STRICT:
                            dead.write(raw_row, "pre-build validation failed")
                            result_errors.append({"row": records_in, "error": "validation failed"})
                            continue
                    mapped = self._mapper.map(raw_row)
                    self._builder.build_one(mapped)
                    records_out += 1
                except Exception as exc:
                    if self._dead_letter_path is not None:
                        dead.write(raw_row, str(exc))
                        result_errors.append({"row": records_in, "error": str(exc)})
                    else:
                        raise PipelineError(f"Pipeline run failed at row {records_in}: {exc}") from exc
        finally:
            dead.close()

        elapsed = time.perf_counter() - t0
        rps = records_out / elapsed if elapsed > 0 else 0.0

        pr = PipelineResult(
            records_in=records_in,
            records_out=records_out,
            records_failed=dead.count,
            elapsed_seconds=round(elapsed, 6),
            records_per_second=round(rps, 1),
            dead_letter_path=str(self._dead_letter_path) if dead.count > 0 else None,
            errors=result_errors,
        )

        _log.info(
            "pipeline.run_complete",
            records_in=pr.records_in,
            records_out=pr.records_out,
            records_failed=pr.records_failed,
            elapsed=pr.elapsed_seconds,
            rps=pr.records_per_second,
        )
        return pr

    # ------------------------------------------------------------------
    # File output
    # ------------------------------------------------------------------

    def to_json(
        self,
        path: str | Path,
        *,
        pretty: bool = True,
    ) -> PipelineResult:
        """Build all documents and write them as a JSON array to a file.

        Args:
            path: Output file path.
            pretty: If ``True``, indent with 2 spaces.

        Returns:
            A :class:`PipelineResult` with timing and byte count.

        Raises:
            PipelineError: If serialization or writing fails.
        """
        t0 = time.perf_counter()
        try:
            records_in = 0
            records_failed = 0
            dead = _DeadLetterWriter(self._dead_letter_path)
            docs: list[dict[str, Any]] = []
            for raw_row in self._source.read():
                records_in += 1
                try:
                    mapped = self._mapper.map(raw_row)
                    doc = self._builder.build_one(mapped)
                    docs.append(doc)
                except Exception as exc:
                    if self._dead_letter_path is not None:
                        dead.write(raw_row, str(exc))
                        records_failed += 1
                    else:
                        raise
            dead.close()
            data = dumps(docs, pretty=pretty)
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            elapsed = time.perf_counter() - t0
            rps = len(docs) / elapsed if elapsed > 0 else 0.0
            result = PipelineResult(
                records_in=records_in,
                records_out=len(docs),
                records_failed=dead.count,
                elapsed_seconds=round(elapsed, 3),
                records_per_second=round(rps, 1),
                bytes_written=len(data),
                dead_letter_path=str(self._dead_letter_path) if dead.count > 0 else None,
            )
            _log.info(
                "pipeline.to_json",
                path=str(path),
                records=len(docs),
                bytes=len(data),
                elapsed=result.elapsed_seconds,
            )
            return result
        except PipelineError:
            raise
        except Exception as exc:
            msg = f"Failed to write JSON to {path}: {exc}"
            raise PipelineError(msg) from exc

    def to_ndjson(self, path: str | Path) -> PipelineResult:
        """Stream documents to a newline-delimited JSON file.

        Each document is serialized as a single compact JSON line.
        Memory-efficient — only one document is in memory at a time.

        Args:
            path: Output file path.

        Returns:
            A :class:`PipelineResult` with timing and byte count.

        Raises:
            PipelineError: If serialization or writing fails.
        """
        t0 = time.perf_counter()
        try:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            total_bytes = 0
            records_in = 0
            records_out = 0
            dead = _DeadLetterWriter(self._dead_letter_path)
            with out.open("wb") as fh:
                for raw_row in self._source.read():
                    records_in += 1
                    try:
                        mapped = self._mapper.map(raw_row)
                        doc = self._builder.build_one(mapped)
                    except Exception as exc:
                        if self._dead_letter_path is not None:
                            dead.write(raw_row, str(exc))
                            continue
                        raise
                    line = dumps(doc, pretty=False) + b"\n"
                    fh.write(line)
                    total_bytes += len(line)
                    records_out += 1
            dead.close()
            elapsed = time.perf_counter() - t0
            rps = records_out / elapsed if elapsed > 0 else 0.0
            result = PipelineResult(
                records_in=records_in,
                records_out=records_out,
                records_failed=dead.count,
                elapsed_seconds=round(elapsed, 3),
                records_per_second=round(rps, 1),
                bytes_written=total_bytes,
                dead_letter_path=str(self._dead_letter_path) if dead.count > 0 else None,
            )
            _log.info(
                "pipeline.to_ndjson",
                path=str(path),
                records=records_out,
                bytes=total_bytes,
                elapsed=result.elapsed_seconds,
            )
            return result
        except PipelineError:
            raise
        except Exception as exc:
            msg = f"Failed to write NDJSON to {path}: {exc}"
            raise PipelineError(msg) from exc

    def to_sink(self, sink: Any, *, workers: int | str = 1) -> PipelineResult:
        """Stream documents to an output sink with automatic chunking.

        Iterates the source adapter, maps and builds each row, accumulates
        documents into batches of ``sink.chunk_size``, and writes each
        batch via ``sink.write_chunk()``.

        When *workers* > 1, the CPU-bound map → build → serialize loop
        is distributed across child processes using
        ``concurrent.futures.ProcessPoolExecutor``.  Each worker writes
        its own part file directly, bypassing the sink's ``write_chunk``.
        The sink still handles ``open()`` / ``close()`` / ``_SUCCESS``
        semantics.

        Args:
            sink: Any object satisfying the :class:`~ceds_jsonld.sinks.Sink`
                protocol (e.g. :class:`~ceds_jsonld.sinks.NDJSONSink`,
                :class:`~ceds_jsonld.sinks.ADLSink`).
            workers: Number of child processes for parallel map/build.
                ``1`` (default) uses the serial path.  ``"auto"`` uses
                ``os.cpu_count()``.  Custom transforms are not supported
                with ``workers > 1``.

        Returns:
            A :class:`PipelineResult` with timing, counts, and the sink's
            byte total.

        Raises:
            PipelineError: On adapter, mapping, build, or sink failures.
        """
        n_workers = _resolve_pipeline_workers(workers)
        if n_workers > 1:
            return self._to_sink_parallel(sink, n_workers)
        return self._to_sink_serial(sink)

    # ------------------------------------------------------------------
    # Serial to_sink (workers=1, identical to previous behaviour)
    # ------------------------------------------------------------------

    def _to_sink_serial(self, sink: Any) -> PipelineResult:
        """Serial path — single-process map → build → write."""
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
                    raise PipelineError(f"Pipeline to_sink failed at row {records_in}: {exc}") from exc

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

    # ------------------------------------------------------------------
    # Parallel to_sink (workers > 1, multiprocessing)
    # ------------------------------------------------------------------

    def _to_sink_parallel(self, sink: Any, n_workers: int) -> PipelineResult:
        """Parallel path — distribute map/build/write across processes."""
        if self._custom_transforms:
            msg = (
                "custom_transforms cannot be used with workers > 1 because "
                "lambda/closure objects are not pickle-safe for multiprocessing. "
                "Use workers=1 or register transforms by name."
            )
            raise PipelineError(msg)

        t0 = time.perf_counter()

        # Open sink for directory creation / mode handling only.
        # Workers write part files directly; we just need the directory.
        try:
            sink.open()
        except Exception as exc:
            msg = f"Failed to open sink: {exc}"
            raise PipelineError(msg) from exc

        output_path = str(sink.path)
        mapping_config = self._shape_def.mapping_config
        shape_name = self._shape_def.name

        # Read all rows from source and batch into chunks.
        chunks: list[list[dict[str, Any]]] = []
        current_chunk: list[dict[str, Any]] = []
        records_in = 0
        for raw_row in self._source.read():
            records_in += 1
            current_chunk.append(raw_row)
            if len(current_chunk) >= sink.chunk_size:
                chunks.append(current_chunk)
                current_chunk = []
        if current_chunk:
            chunks.append(current_chunk)

        # Submit chunks to worker pool
        records_out = 0
        total_bytes = 0
        dead = _DeadLetterWriter(self._dead_letter_path)

        try:
            with ProcessPoolExecutor(max_workers=n_workers) as pool:
                futures = []
                for i, chunk in enumerate(chunks):
                    # Use sink's starting part_index offset for correct numbering
                    part_idx = sink._part_index + i
                    future = pool.submit(
                        _pipeline_worker,
                        chunk,
                        part_idx,
                        output_path,
                        mapping_config,
                        shape_name,
                    )
                    futures.append(future)

                for future in futures:
                    written, chunk_bytes, dead_letters = future.result()
                    records_out += written
                    total_bytes += chunk_bytes
                    for dl in dead_letters:
                        dead.write(dl["_record"], dl["_error"])

            # Update sink's internal counters so close() produces correct totals
            sink._part_index += len(chunks)
            sink._total_records += records_out
            sink._total_bytes += total_bytes

        except PipelineError:
            raise
        except Exception as exc:
            msg = f"Pipeline parallel to_sink failed: {exc}"
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
            "pipeline.to_sink_parallel",
            sink=type(sink).__name__,
            workers=n_workers,
            records=records_out,
            files=sink_result.files_written,
            bytes=sink_result.bytes_written,
            elapsed=result.elapsed_seconds,
        )
        return result

    def to_cosmos(
        self,
        endpoint: str,
        credential: Any,
        database: str,
        *,
        container: str | None = None,
        partition_value: str | None = None,
        concurrency: int = 25,
        create_if_missing: bool = True,
    ) -> Any:
        """Upload all documents to Azure Cosmos DB.

        Builds every document via :meth:`stream`, prepares each for Cosmos
        (injects ``id`` and ``partitionKey``), then bulk-upserts with
        bounded concurrency.

        Args:
            endpoint: Cosmos DB account URI
                (e.g. ``https://myaccount.documents.azure.com:443/``).
            credential: An ``azure.identity`` *TokenCredential*
                (``DefaultAzureCredential()``, ``ManagedIdentityCredential()``,
                etc.) or a plain master-key string for the local emulator.
            database: Target database name.
            container: Target container name.  Defaults to the shape name
                (e.g. ``"person"``).
            partition_value: Explicit partition key value injected into every
                document.  Defaults to each document's ``@type``.
            concurrency: Max parallel upserts (default 25).
            create_if_missing: Create the database/container if they don't
                exist (default ``True``).

        Returns:
            A :class:`~ceds_jsonld.cosmos.loader.BulkResult` with counts
            and RU cost.

        Raises:
            PipelineError: On build or upload failure.
            CosmosError: If ``azure-cosmos`` is not installed.
        """
        import asyncio

        try:
            from ceds_jsonld.cosmos.loader import CosmosLoader as _CosmosLoader
        except Exception as exc:
            msg = (
                "Cosmos DB support requires the 'azure-cosmos' package. "
                "Install it with: pip install ceds-jsonld[cosmos]"
            )
            raise PipelineError(msg) from exc

        target_container = container or self._shape_name
        docs = self.build_all()

        async def _upload() -> Any:
            loader = _CosmosLoader(
                endpoint=endpoint,
                credential=credential,
                database=database,
                container=target_container,
                partition_value=partition_value,
                concurrency=concurrency,
                create_if_missing=create_if_missing,
            )
            async with loader:
                return await loader.upsert_many(docs)

        try:
            return asyncio.run(_upload())
        except PipelineError:
            raise
        except Exception as exc:
            msg = f"Cosmos DB upload failed: {exc}"
            raise PipelineError(msg) from exc
