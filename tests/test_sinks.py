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
