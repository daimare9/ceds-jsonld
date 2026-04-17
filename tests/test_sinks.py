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


# ------------------------------------------------------------------
# SinkResult
# ------------------------------------------------------------------


class TestSinkResult:
    def test_defaults(self) -> None:
        r = SinkResult()
        assert r.files_written == 0
        assert r.records_written == 0
        assert r.bytes_written == 0
        assert r.errors == []


# ------------------------------------------------------------------
# NDJSONSink
# ------------------------------------------------------------------


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

    def test_adl_sink_satisfies_protocol(self) -> None:
        from ceds_jsonld.sinks import ADLSink

        sink = ADLSink("abfss://c@a.dfs.core.windows.net/out")
        assert isinstance(sink, Sink)


# ------------------------------------------------------------------
# ADLSink
# ------------------------------------------------------------------


class TestADLSinkImportGuard:
    def test_missing_fsspec_raises(self) -> None:
        """If fsspec is not installed, opening raises ImportError."""
        import sys
        from unittest.mock import patch

        from ceds_jsonld.sinks import ADLSink

        sink = ADLSink("abfss://container@account.dfs.core.windows.net/out")
        with patch.dict(sys.modules, {"fsspec": None}), pytest.raises(ImportError, match="fsspec"):
            sink.open()


class TestADLSinkWriteChunk:
    def test_write_chunk_creates_part_files(self) -> None:
        """Mock fsspec filesystem, verify part files written correctly."""
        from unittest.mock import MagicMock

        from ceds_jsonld.sinks import ADLSink

        mock_fs = MagicMock()
        mock_fh = MagicMock()
        mock_fs.open.return_value.__enter__ = MagicMock(return_value=mock_fh)
        mock_fs.open.return_value.__exit__ = MagicMock(return_value=False)

        sink = ADLSink("abfss://c@a.dfs.core.windows.net/out", chunk_size=5)
        sink._fs = mock_fs  # inject mock

        docs = _make_docs(3)
        sink.write_chunk(docs)

        mock_fs.open.assert_called_once_with("abfss://c@a.dfs.core.windows.net/out/part-00000.ndjson", "wb")
        assert mock_fh.write.call_count == 3
        assert sink._part_index == 1

    def test_sink_result(self) -> None:
        """Verify SinkResult after writing."""
        from unittest.mock import MagicMock

        from ceds_jsonld.sinks import ADLSink

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
        from ceds_jsonld.sinks import ADLSink

        with pytest.raises(ValueError, match="chunk_size must be >= 1"):
            ADLSink("abfss://c@a.dfs.core.windows.net/out", chunk_size=0)


# ------------------------------------------------------------------
# Pipeline.to_sink() integration
# ------------------------------------------------------------------


def _person_registry():
    """Create a ShapeRegistry with the Person shape loaded."""
    from ceds_jsonld.registry import ShapeRegistry

    reg = ShapeRegistry()
    reg.load_shape("person")
    return reg


def _sample_rows(n: int) -> list[dict[str, Any]]:
    """Generate *n* minimal Person source rows."""
    return [
        {
            "FirstName": f"First{i}",
            "MiddleName": "",
            "LastName": f"Last{i}",
            "GenerationCodeOrSuffix": "",
            "Birthdate": "1990-01-15",
            "Sex": "Female",
            "RaceEthnicity": "White",
            "PersonIdentifiers": f"ID{i}",
            "IdentificationSystems": "PersonIdentificationSystem_SSN",
            "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
        }
        for i in range(n)
    ]


class TestPipelineToSink:
    def test_end_to_end(self, tmp_path: Path) -> None:
        """Full Pipeline.to_sink(NDJSONSink) with 15 records, chunk_size=10."""
        from ceds_jsonld import DictAdapter, Pipeline

        pipe = Pipeline(
            source=DictAdapter(_sample_rows(15)),
            shape="person",
            registry=_person_registry(),
        )
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
        from ceds_jsonld import DictAdapter, Pipeline

        good = _sample_rows(1)
        bad = [{"FirstName": "Bad"}]  # missing required fields
        data = good + bad + good  # 3 records, 1 bad

        dlq = tmp_path / "dlq.ndjson"
        pipe = Pipeline(
            source=DictAdapter(data),
            shape="person",
            registry=_person_registry(),
            dead_letter_path=dlq,
        )
        sink = NDJSONSink(tmp_path / "out", chunk_size=100)
        result = pipe.to_sink(sink)

        assert result.records_out == 2
        assert result.records_failed == 1
        assert result.dead_letter_path is not None

    def test_result_counts(self, tmp_path: Path) -> None:
        """PipelineResult reflects sink's bytes_written."""
        from ceds_jsonld import DictAdapter, Pipeline

        pipe = Pipeline(
            source=DictAdapter(_sample_rows(5)),
            shape="person",
            registry=_person_registry(),
        )
        sink = NDJSONSink(tmp_path / "out", chunk_size=100)
        result = pipe.to_sink(sink)

        assert result.records_in == 5
        assert result.records_out == 5
        assert result.bytes_written > 0
        assert result.elapsed_seconds > 0
        assert result.records_per_second > 0


# ------------------------------------------------------------------
# Top-level exports
# ------------------------------------------------------------------


class TestSinkExports:
    def test_importable_from_top_level(self) -> None:
        from ceds_jsonld import ADLSink, NDJSONSink, Sink, SinkResult

        assert Sink is not None
        assert SinkResult is not None
        assert NDJSONSink is not None
        assert ADLSink is not None

    def test_write_mode_importable(self) -> None:
        from ceds_jsonld.sinks import WriteMode

        assert WriteMode is not None


# ------------------------------------------------------------------
# WriteMode enum / literal
# ------------------------------------------------------------------


class TestWriteMode:
    def test_valid_modes(self) -> None:
        from ceds_jsonld.sinks import WriteMode

        assert WriteMode.ERROR == "error"
        assert WriteMode.OVERWRITE == "overwrite"
        assert WriteMode.APPEND == "append"


# ------------------------------------------------------------------
# NDJSONSink — write mode: error (default)
# ------------------------------------------------------------------


class TestNDJSONSinkModeError:
    def test_default_mode_is_error(self, tmp_path: Path) -> None:
        sink = NDJSONSink(tmp_path / "out")
        assert sink.mode == "error"

    def test_error_mode_raises_on_existing_data(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "part-00000.ndjson").write_text('{"x":1}\n')

        sink = NDJSONSink(out, mode="error")
        with pytest.raises(FileExistsError, match="already contains"):
            sink.open()

    def test_error_mode_ok_on_empty_dir(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        sink = NDJSONSink(out, mode="error")
        sink.open()  # should not raise

    def test_error_mode_ok_on_new_dir(self, tmp_path: Path) -> None:
        sink = NDJSONSink(tmp_path / "new_out", mode="error")
        sink.open()  # should not raise


# ------------------------------------------------------------------
# NDJSONSink — write mode: overwrite
# ------------------------------------------------------------------


class TestNDJSONSinkModeOverwrite:
    def test_overwrite_clears_existing_parts(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "part-00000.ndjson").write_text('{"old":true}\n')
        (out / "part-00001.ndjson").write_text('{"old":true}\n')

        sink = NDJSONSink(out, mode="overwrite")
        sink.open()
        sink.write_chunk(_make_docs(3))
        sink.close()

        files = sorted(out.glob("part-*.ndjson"))
        assert len(files) == 1
        assert files[0].name == "part-00000.ndjson"
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[0])["@id"] == "urn:test:0"

    def test_overwrite_removes_entire_directory_contents(self, tmp_path: Path) -> None:
        """Spark-style overwrite nukes everything, not just part files."""
        out = tmp_path / "out"
        out.mkdir()
        (out / "part-00000.ndjson").write_text('{"old":true}\n')
        (out / "metadata.json").write_text('{"info":"keep"}\n')
        sub = out / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested\n")

        sink = NDJSONSink(out, mode="overwrite")
        sink.open()

        # Everything should be gone — directory recreated empty
        assert not (out / "part-00000.ndjson").exists()
        assert not (out / "metadata.json").exists()
        assert not sub.exists()


# ------------------------------------------------------------------
# NDJSONSink — write mode: append
# ------------------------------------------------------------------


class TestNDJSONSinkModeAppend:
    def test_append_continues_numbering(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "part-00000.ndjson").write_text('{"old":true}\n')
        (out / "part-00002.ndjson").write_text('{"old":true}\n')

        sink = NDJSONSink(out, mode="append")
        sink.open()
        sink.write_chunk(_make_docs(2))
        sink.close()

        files = sorted(out.glob("part-*.ndjson"))
        assert len(files) == 3  # 2 old + 1 new
        assert files[-1].name == "part-00003.ndjson"

    def test_append_on_empty_dir_starts_at_zero(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        sink = NDJSONSink(out, mode="append")
        sink.open()
        sink.write_chunk(_make_docs(1))
        sink.close()

        files = list(out.glob("part-*.ndjson"))
        assert len(files) == 1
        assert files[0].name == "part-00000.ndjson"


# ------------------------------------------------------------------
# NDJSONSink — invalid mode
# ------------------------------------------------------------------


class TestNDJSONSinkInvalidMode:
    def test_invalid_mode_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="mode must be"):
            NDJSONSink(tmp_path / "out", mode="ignore")


# ------------------------------------------------------------------
# NDJSONSink — parallel writes (workers)
# ------------------------------------------------------------------


class TestNDJSONSinkParallelWrites:
    def test_default_workers_is_one(self, tmp_path: Path) -> None:
        sink = NDJSONSink(tmp_path / "out")
        assert sink.workers == 1

    def test_workers_auto_detects_cores(self, tmp_path: Path) -> None:
        import os

        sink = NDJSONSink(tmp_path / "out", workers="auto")
        expected = os.cpu_count() or 4
        assert sink.workers == expected

    def test_parallel_writes_produce_correct_output(self, tmp_path: Path) -> None:
        """4 chunks with workers=2 should produce 4 part files with all records."""
        out = tmp_path / "out"
        sink = NDJSONSink(out, chunk_size=10, workers=2, mode="overwrite")
        sink.open()
        for _i in range(4):
            sink.write_chunk(_make_docs(10))
        result = sink.close()

        assert result.files_written == 4
        assert result.records_written == 40
        files = sorted(out.glob("part-*.ndjson"))
        assert len(files) == 4

        # All 40 records present across all files
        all_lines = []
        for f in files:
            all_lines.extend(f.read_text().strip().split("\n"))
        assert len(all_lines) == 40

    def test_workers_invalid_zero(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="workers must be"):
            NDJSONSink(tmp_path / "out", workers=0)

    def test_workers_invalid_negative(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="workers must be"):
            NDJSONSink(tmp_path / "out", workers=-1)

    def test_single_worker_no_executor(self, tmp_path: Path) -> None:
        """workers=1 should not create a ThreadPoolExecutor."""
        sink = NDJSONSink(tmp_path / "out", workers=1)
        sink.open()
        sink.write_chunk(_make_docs(5))
        result = sink.close()
        assert result.files_written == 1
        assert sink._executor is None


# ------------------------------------------------------------------
# NDJSONSink — _SUCCESS marker
# ------------------------------------------------------------------


class TestNDJSONSinkSuccessMarker:
    def test_success_file_written_on_close(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        sink = NDJSONSink(out, mode="overwrite")
        sink.open()
        sink.write_chunk(_make_docs(3))
        sink.close()

        success_file = out / "_SUCCESS"
        assert success_file.exists()

    def test_success_file_not_written_if_no_records(self, tmp_path: Path) -> None:
        """If no records were written, _SUCCESS should still be written (job succeeded)."""
        out = tmp_path / "out"
        sink = NDJSONSink(out, mode="overwrite")
        sink.open()
        sink.close()

        assert (out / "_SUCCESS").exists()

    def test_overwrite_clears_old_success(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "_SUCCESS").write_text("")
        (out / "part-00000.ndjson").write_text('{"old":true}\n')

        sink = NDJSONSink(out, mode="overwrite")
        sink.open()
        # Old _SUCCESS should be removed on open
        assert not (out / "_SUCCESS").exists()
        sink.write_chunk(_make_docs(1))
        sink.close()
        # New _SUCCESS written on close
        assert (out / "_SUCCESS").exists()


# ------------------------------------------------------------------
# ADLSink — write mode support
# ------------------------------------------------------------------


class TestADLSinkModes:
    def test_default_mode_is_error(self) -> None:
        from ceds_jsonld.sinks import ADLSink

        sink = ADLSink("abfss://c@a.dfs.core.windows.net/out")
        assert sink.mode == "error"

    def test_invalid_mode_raises(self) -> None:
        from ceds_jsonld.sinks import ADLSink

        with pytest.raises(ValueError, match="mode must be"):
            ADLSink("abfss://c@a.dfs.core.windows.net/out", mode="ignore")

    def test_default_workers_is_one(self) -> None:
        from ceds_jsonld.sinks import ADLSink

        sink = ADLSink("abfss://c@a.dfs.core.windows.net/out")
        assert sink.workers == 1


# ------------------------------------------------------------------
# Pipeline.to_sink() — parallel workers (multiprocessing)
# ------------------------------------------------------------------


class TestPipelineToSinkParallel:
    """Test Pipeline.to_sink(sink, workers=N) with multiprocessing."""

    def test_parallel_produces_same_output_as_serial(self, tmp_path: Path) -> None:
        """workers=2 should produce identical docs as workers=1."""
        from ceds_jsonld import DictAdapter, Pipeline

        rows = _sample_rows(20)
        reg = _person_registry()

        # Serial run
        serial_dir = tmp_path / "serial"
        pipe1 = Pipeline(source=DictAdapter(rows), shape="person", registry=reg)
        sink1 = NDJSONSink(serial_dir, chunk_size=10)
        r1 = pipe1.to_sink(sink1)

        # Parallel run
        parallel_dir = tmp_path / "parallel"
        pipe2 = Pipeline(source=DictAdapter(rows), shape="person", registry=reg)
        sink2 = NDJSONSink(parallel_dir, chunk_size=10)
        r2 = pipe2.to_sink(sink2, workers=2)

        assert r1.records_out == r2.records_out == 20
        assert r1.records_in == r2.records_in == 20
        assert r1.records_failed == r2.records_failed == 0

        # Parse all docs from both runs and compare as sets of @ids
        def _read_all_docs(out_dir: Path) -> list[dict]:
            docs = []
            for f in sorted(out_dir.glob("part-*.ndjson")):
                for line in f.read_text().strip().split("\n"):
                    if line:
                        docs.append(json.loads(line))
            return docs

        serial_docs = _read_all_docs(serial_dir)
        parallel_docs = _read_all_docs(parallel_dir)
        assert len(serial_docs) == len(parallel_docs) == 20
        assert {d["@id"] for d in serial_docs} == {d["@id"] for d in parallel_docs}

    def test_parallel_result_bytes_written(self, tmp_path: Path) -> None:
        """bytes_written in the result should reflect actual file sizes."""
        from ceds_jsonld import DictAdapter, Pipeline

        pipe = Pipeline(
            source=DictAdapter(_sample_rows(15)),
            shape="person",
            registry=_person_registry(),
        )
        sink = NDJSONSink(tmp_path / "out", chunk_size=10)
        result = pipe.to_sink(sink, workers=2)

        assert result.records_out == 15
        assert result.bytes_written > 0
        actual = sum(f.stat().st_size for f in (tmp_path / "out").glob("part-*.ndjson"))
        assert result.bytes_written == actual

    def test_parallel_creates_success_marker(self, tmp_path: Path) -> None:
        """_SUCCESS file should still be written in parallel mode."""
        from ceds_jsonld import DictAdapter, Pipeline

        pipe = Pipeline(
            source=DictAdapter(_sample_rows(5)),
            shape="person",
            registry=_person_registry(),
        )
        out = tmp_path / "out"
        sink = NDJSONSink(out, chunk_size=10)
        pipe.to_sink(sink, workers=2)

        assert (out / "_SUCCESS").exists()

    def test_parallel_workers_auto(self, tmp_path: Path) -> None:
        """workers='auto' should work without error."""
        from ceds_jsonld import DictAdapter, Pipeline

        pipe = Pipeline(
            source=DictAdapter(_sample_rows(5)),
            shape="person",
            registry=_person_registry(),
        )
        sink = NDJSONSink(tmp_path / "out", chunk_size=10)
        result = pipe.to_sink(sink, workers="auto")
        assert result.records_out == 5

    def test_parallel_dlq_collects_errors(self, tmp_path: Path) -> None:
        """Poison rows should still go to DLQ in parallel mode."""
        from ceds_jsonld import DictAdapter, Pipeline

        good = _sample_rows(3)
        bad = [{"FirstName": "Bad"}]  # missing required fields
        data = good + bad + good

        dlq = tmp_path / "dlq.ndjson"
        pipe = Pipeline(
            source=DictAdapter(data),
            shape="person",
            registry=_person_registry(),
            dead_letter_path=dlq,
        )
        sink = NDJSONSink(tmp_path / "out", chunk_size=100)
        result = pipe.to_sink(sink, workers=2)

        assert result.records_out == 6
        assert result.records_failed == 1
        assert result.dead_letter_path is not None

    def test_parallel_with_custom_transforms_raises(self, tmp_path: Path) -> None:
        """custom_transforms + workers > 1 should raise a clear error."""
        from ceds_jsonld import DictAdapter, Pipeline
        from ceds_jsonld.exceptions import PipelineError

        pipe = Pipeline(
            source=DictAdapter(_sample_rows(3)),
            shape="person",
            registry=_person_registry(),
            custom_transforms={"my_fn": lambda x: x},
        )
        sink = NDJSONSink(tmp_path / "out", chunk_size=10)
        with pytest.raises(PipelineError, match="custom_transforms"):
            pipe.to_sink(sink, workers=2)

    def test_workers_one_uses_serial_path(self, tmp_path: Path) -> None:
        """workers=1 (default) should use the existing serial path."""
        from ceds_jsonld import DictAdapter, Pipeline

        pipe = Pipeline(
            source=DictAdapter(_sample_rows(5)),
            shape="person",
            registry=_person_registry(),
        )
        sink = NDJSONSink(tmp_path / "out", chunk_size=10)
        result = pipe.to_sink(sink, workers=1)
        assert result.records_out == 5
