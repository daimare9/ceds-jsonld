"""Tests for output sinks — NDJSONSink, ADLSink, Sink protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ceds_jsonld.sinks import NDJSONSink, Sink, SinkResult


def _make_docs(n: int) -> list[dict[str, Any]]:
    """Generate *n* minimal JSON-LD-like documents."""
    return [
        {"@id": f"urn:test:{i}", "@type": "Person", "name": f"Person {i}"}
        for i in range(n)
    ]


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
        actual_size = sum(
            f.stat().st_size for f in (tmp_path / "out").glob("part-*.ndjson")
        )
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
        with patch.dict(sys.modules, {"fsspec": None}):
            with pytest.raises(ImportError, match="fsspec"):
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

        mock_fs.open.assert_called_once_with(
            "abfss://c@a.dfs.core.windows.net/out/part-00000.ndjson", "wb"
        )
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
