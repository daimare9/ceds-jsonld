"""Tests for all source adapters — using REAL dependencies, no mocks.

Each adapter is tested with real data on disk, real libraries, and real
network interactions via pytest-httpserver and real SQLite databases.
No mocks, no stubs, no fakes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from pytest_httpserver import HTTPServer
from sqlalchemy import create_engine, text

from ceds_jsonld.adapters import (
    APIAdapter,
    CSVAdapter,
    DatabaseAdapter,
    DictAdapter,
    ExcelAdapter,
    NDJSONAdapter,
    ParquetAdapter,
    SourceAdapter,
)
from ceds_jsonld.exceptions import AdapterError

# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

SAMPLE_ROWS = [
    {"FirstName": "Alice", "LastName": "Smith", "Age": "30"},
    {"FirstName": "Bob", "LastName": "Jones", "Age": "25"},
    {"FirstName": "Carol", "LastName": "Lee", "Age": "42"},
]

PERSON_CSV = (
    Path(__file__).resolve().parent.parent / "src" / "ceds_jsonld" / "ontologies" / "person" / "person_sample.csv"
)


# ---------------------------------------------------------------------------
# Fixtures — real temp files
# ---------------------------------------------------------------------------


@pytest.fixture()
def csv_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.csv"
    p.write_text(
        "FirstName,LastName,Age\nAlice,Smith,30\nBob,Jones,25\nCarol,Lee,42\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def csv_with_blanks(tmp_path: Path) -> Path:
    p = tmp_path / "blanks.csv"
    p.write_text("A,B\n1,\n,2\n", encoding="utf-8")
    return p


@pytest.fixture()
def ndjson_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.ndjson"
    lines = [json.dumps(row) for row in SAMPLE_ROWS]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


@pytest.fixture()
def excel_path(tmp_path: Path) -> Path:
    """Real Excel file created by openpyxl."""
    p = tmp_path / "test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Students"
    ws.append(["FirstName", "LastName", "Age"])
    for row in SAMPLE_ROWS:
        ws.append([row["FirstName"], row["LastName"], row["Age"]])
    wb.save(p)
    return p


@pytest.fixture()
def sqlite_url(tmp_path: Path) -> str:
    """Real SQLite database with a students table."""
    db_path = tmp_path / "test.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE students (FirstName TEXT, LastName TEXT, Age INTEGER)"))
        for row in SAMPLE_ROWS:
            conn.execute(
                text("INSERT INTO students VALUES (:f, :l, :a)"),
                {"f": row["FirstName"], "l": row["LastName"], "a": int(row["Age"])},
            )
        conn.commit()
    engine.dispose()
    return url


# =====================================================================
# SourceAdapter ABC
# =====================================================================


class TestSourceAdapterABC:
    """Verify the abstract base class contract."""

    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            SourceAdapter()  # type: ignore[abstract]

    def test_subclass_must_implement_read(self) -> None:
        class BadAdapter(SourceAdapter):
            pass

        with pytest.raises(TypeError):
            BadAdapter()  # type: ignore[abstract]

    def test_concrete_subclass_works(self) -> None:
        class OK(SourceAdapter):
            def read(self, **kwargs: Any) -> list:
                return [{"a": 1}]

        adapter = OK()
        assert list(adapter.read()) == [{"a": 1}]
        assert adapter.count() is None

    def test_read_batch_default_chunking(self) -> None:
        class Five(SourceAdapter):
            def read(self, **kwargs: Any):
                for i in range(5):
                    yield {"i": i}

        batches = list(Five().read_batch(batch_size=2))
        assert len(batches) == 3
        assert len(batches[0]) == 2
        assert len(batches[1]) == 2
        assert len(batches[2]) == 1


# =====================================================================
# CSVAdapter
# =====================================================================


class TestCSVAdapter:
    """CSV adapter with real files on disk."""

    def test_read_all_rows(self, csv_path: Path) -> None:
        adapter = CSVAdapter(csv_path)
        rows = list(adapter.read())
        assert len(rows) == 3
        assert rows[0]["FirstName"] == "Alice"
        assert rows[2]["LastName"] == "Lee"

    def test_values_are_strings_by_default(self, csv_path: Path) -> None:
        rows = list(CSVAdapter(csv_path).read())
        assert rows[0]["Age"] == "30"

    def test_count(self, csv_path: Path) -> None:
        assert CSVAdapter(csv_path).count() == 3

    def test_read_batch(self, csv_path: Path) -> None:
        batches = list(CSVAdapter(csv_path).read_batch(batch_size=2))
        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 1

    def test_nan_replaced_with_empty_string(self, csv_with_blanks: Path) -> None:
        rows = list(CSVAdapter(csv_with_blanks).read())
        assert rows[0]["B"] == ""
        assert rows[1]["A"] == ""

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(AdapterError, match="not found"):
            CSVAdapter(tmp_path / "nope.csv")

    def test_custom_delimiter(self, tmp_path: Path) -> None:
        p = tmp_path / "tabs.csv"
        p.write_text("A\tB\n1\t2\n3\t4\n", encoding="utf-8")
        rows = list(CSVAdapter(p, delimiter="\t").read())
        assert len(rows) == 2
        assert rows[0]["A"] == "1"

    def test_real_person_sample(self) -> None:
        if not PERSON_CSV.exists():
            pytest.skip("person_sample.csv not found")
        adapter = CSVAdapter(PERSON_CSV)
        rows = list(adapter.read())
        assert len(rows) == 90
        assert rows[0]["FirstName"] == "EDITH"
        assert adapter.count() == 90


# =====================================================================
# ExcelAdapter — real openpyxl
# =====================================================================


class TestExcelAdapter:
    """Excel adapter with real .xlsx files created by openpyxl."""

    def test_read_all_rows(self, excel_path: Path) -> None:
        rows = list(ExcelAdapter(excel_path).read())
        assert len(rows) == 3
        assert rows[0]["FirstName"] == "Alice"

    def test_values_are_strings(self, excel_path: Path) -> None:
        rows = list(ExcelAdapter(excel_path).read())
        assert rows[0]["Age"] == "30"

    def test_count(self, excel_path: Path) -> None:
        assert ExcelAdapter(excel_path).count() == 3

    def test_sheet_by_name(self, excel_path: Path) -> None:
        rows = list(ExcelAdapter(excel_path, sheet_name="Students").read())
        assert len(rows) == 3

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(AdapterError, match="not found"):
            ExcelAdapter(tmp_path / "nope.xlsx")

    def test_nan_cells_become_empty_strings(self, tmp_path: Path) -> None:
        p = tmp_path / "blanks.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Name", "Value"])
        ws.append(["Alice", None])
        ws.append([None, "42"])
        wb.save(p)

        rows = list(ExcelAdapter(p).read())
        assert rows[0]["Value"] == ""
        assert rows[1]["Name"] == ""


# =====================================================================
# DictAdapter
# =====================================================================


class TestDictAdapter:
    """In-memory dict adapter."""

    def test_read_list(self) -> None:
        assert list(DictAdapter(SAMPLE_ROWS).read()) == SAMPLE_ROWS

    def test_read_single_dict(self) -> None:
        assert list(DictAdapter({"x": "y"}).read()) == [{"x": "y"}]

    def test_count(self) -> None:
        assert DictAdapter(SAMPLE_ROWS).count() == 3

    def test_empty_list(self) -> None:
        adapter = DictAdapter([])
        assert list(adapter.read()) == []
        assert adapter.count() == 0

    def test_repeatable_reads(self) -> None:
        adapter = DictAdapter(SAMPLE_ROWS)
        assert list(adapter.read()) == list(adapter.read())

    def test_read_batch(self) -> None:
        batches = list(DictAdapter(SAMPLE_ROWS).read_batch(batch_size=2))
        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 1

    def test_generator_input_materialised(self) -> None:
        gen = ({"v": i} for i in range(3))
        adapter = DictAdapter(gen)
        assert adapter.count() == 3
        assert len(list(adapter.read())) == 3


# =====================================================================
# NDJSONAdapter
# =====================================================================


class TestNDJSONAdapter:
    """NDJSON adapter with real files."""

    def test_read_all(self, ndjson_path: Path) -> None:
        rows = list(NDJSONAdapter(ndjson_path).read())
        assert len(rows) == 3
        assert rows[0]["FirstName"] == "Alice"

    def test_count(self, ndjson_path: Path) -> None:
        assert NDJSONAdapter(ndjson_path).count() == 3

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "blanks.ndjson"
        p.write_text('{"a":1}\n\n{"a":2}\n\n', encoding="utf-8")
        assert len(list(NDJSONAdapter(p).read())) == 2

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.ndjson"
        p.write_text('{"ok":1}\nnot-json\n', encoding="utf-8")
        with pytest.raises(AdapterError, match="Invalid JSON on line 2"):
            list(NDJSONAdapter(p).read())

    def test_non_object_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "arr.ndjson"
        p.write_text("[1,2,3]\n", encoding="utf-8")
        with pytest.raises(AdapterError, match="not a JSON object"):
            list(NDJSONAdapter(p).read())

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(AdapterError, match="not found"):
            NDJSONAdapter(tmp_path / "nope.ndjson")


# =====================================================================
# ParquetAdapter — real Parquet files via pyarrow
# =====================================================================


@pytest.fixture()
def parquet_path(tmp_path: Path) -> Path:
    """Real Parquet file created by pyarrow."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "FirstName": ["Alice", "Bob", "Carol"],
            "LastName": ["Smith", "Jones", "Lee"],
            "Age": ["30", "25", "42"],
        }
    )
    p = tmp_path / "test.parquet"
    pq.write_table(table, p)
    return p


@pytest.fixture()
def parquet_with_nulls(tmp_path: Path) -> Path:
    """Parquet file with null values."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "Name": ["Alice", None],
            "Value": [None, "42"],
        }
    )
    p = tmp_path / "nulls.parquet"
    pq.write_table(table, p)
    return p


@pytest.fixture()
def parquet_multi_row_group(tmp_path: Path) -> Path:
    """Parquet file with multiple row groups for batching tests."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    p = tmp_path / "multi_rg.parquet"
    writer = pq.ParquetWriter(p, pa.schema([("id", pa.int64()), ("val", pa.string())]))
    for i in range(3):
        table = pa.table({"id": [i * 2, i * 2 + 1], "val": [f"a{i * 2}", f"a{i * 2 + 1}"]})
        writer.write_table(table)
    writer.close()
    return p


class TestParquetAdapter:
    """Parquet adapter with real .parquet files created by pyarrow."""

    def test_read_all_rows(self, parquet_path: Path) -> None:
        rows = list(ParquetAdapter(parquet_path).read())
        assert len(rows) == 3
        assert rows[0]["FirstName"] == "Alice"
        assert rows[2]["LastName"] == "Lee"

    def test_values_are_strings(self, parquet_path: Path) -> None:
        rows = list(ParquetAdapter(parquet_path).read())
        assert rows[0]["Age"] == "30"

    def test_count(self, parquet_path: Path) -> None:
        assert ParquetAdapter(parquet_path).count() == 3

    def test_column_selection(self, parquet_path: Path) -> None:
        rows = list(ParquetAdapter(parquet_path, columns=["FirstName"]).read())
        assert len(rows) == 3
        assert set(rows[0].keys()) == {"FirstName"}

    def test_nan_replaced_with_empty_string(self, parquet_with_nulls: Path) -> None:
        rows = list(ParquetAdapter(parquet_with_nulls).read())
        assert rows[0]["Value"] == ""
        assert rows[1]["Name"] == ""

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(AdapterError, match="not found"):
            ParquetAdapter(tmp_path / "nope.parquet")

    def test_read_batch(self, parquet_path: Path) -> None:
        batches = list(ParquetAdapter(parquet_path).read_batch(batch_size=2))
        total = sum(len(b) for b in batches)
        assert total == 3

    def test_read_batch_multi_row_group(self, parquet_multi_row_group: Path) -> None:
        batches = list(ParquetAdapter(parquet_multi_row_group).read_batch(batch_size=4))
        total = sum(len(b) for b in batches)
        assert total == 6

    def test_count_multi_row_group(self, parquet_multi_row_group: Path) -> None:
        assert ParquetAdapter(parquet_multi_row_group).count() == 6


# =====================================================================
# APIAdapter — real HTTP via pytest-httpserver (NO mocks)
# =====================================================================


class TestAPIAdapter:
    """API adapter tested against a real local HTTP server."""

    def test_single_request_json_array(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/students").respond_with_json(SAMPLE_ROWS)
        rows = list(APIAdapter(httpserver.url_for("/students")).read())
        assert len(rows) == 3
        assert rows[0]["FirstName"] == "Alice"

    def test_results_key_extraction(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/api").respond_with_json({"data": SAMPLE_ROWS, "total": 3})
        adapter = APIAdapter(httpserver.url_for("/api"), results_key="data")
        assert len(list(adapter.read())) == 3

    def test_offset_pagination(self, httpserver: HTTPServer) -> None:
        httpserver.expect_ordered_request("/items", query_string="offset=0&limit=2").respond_with_json(SAMPLE_ROWS[:2])
        httpserver.expect_ordered_request("/items", query_string="offset=2&limit=2").respond_with_json(SAMPLE_ROWS[2:])

        adapter = APIAdapter(httpserver.url_for("/items"), pagination="offset", page_size=2)
        rows = list(adapter.read())
        assert len(rows) == 3
        assert rows[2]["FirstName"] == "Carol"

    def test_cursor_pagination(self, httpserver: HTTPServer) -> None:
        httpserver.expect_ordered_request("/items", query_string="limit=2").respond_with_json(
            {"data": SAMPLE_ROWS[:2], "next_cursor": "abc123"}
        )
        httpserver.expect_ordered_request("/items", query_string="limit=2&cursor=abc123").respond_with_json(
            {"data": SAMPLE_ROWS[2:], "next_cursor": None}
        )

        adapter = APIAdapter(
            httpserver.url_for("/items"),
            pagination="cursor",
            page_size=2,
            results_key="data",
        )
        assert len(list(adapter.read())) == 3

    def test_custom_headers_sent(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/secure", headers={"Authorization": "Bearer TOKEN"}).respond_with_json(
            [{"ok": True}]
        )

        adapter = APIAdapter(
            httpserver.url_for("/secure"),
            headers={"Authorization": "Bearer TOKEN"},
        )
        assert list(adapter.read()) == [{"ok": True}]

    def test_http_error_raises(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/fail").respond_with_data("Not Found", status=404)
        adapter = APIAdapter(httpserver.url_for("/fail"))
        with pytest.raises(AdapterError, match="HTTP 404"):
            list(adapter.read())

    def test_invalid_pagination_strategy(self) -> None:
        with pytest.raises(AdapterError, match="Unknown pagination"):
            APIAdapter("http://example.com", pagination="magic")

    def test_missing_results_key_raises(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/api").respond_with_json({"other": []})
        adapter = APIAdapter(httpserver.url_for("/api"), results_key="data")
        with pytest.raises(AdapterError, match="missing expected key"):
            list(adapter.read())


# =====================================================================
# DatabaseAdapter — real SQLAlchemy + SQLite (NO mocks)
# =====================================================================


class TestDatabaseAdapter:
    """Database adapter tested against a real SQLite database."""

    def test_read_all_rows(self, sqlite_url: str) -> None:
        rows = list(DatabaseAdapter(sqlite_url, query="SELECT * FROM students").read())
        assert len(rows) == 3
        assert rows[0]["FirstName"] == "Alice"

    def test_parameterized_query(self, sqlite_url: str) -> None:
        adapter = DatabaseAdapter(
            sqlite_url,
            query="SELECT * FROM students WHERE Age > :min_age",
            params={"min_age": 28},
        )
        rows = list(adapter.read())
        assert len(rows) == 2
        assert {r["FirstName"] for r in rows} == {"Alice", "Carol"}

    def test_count_returns_none(self, sqlite_url: str) -> None:
        assert DatabaseAdapter(sqlite_url, query="SELECT 1").count() is None

    def test_empty_connection_string_raises(self) -> None:
        with pytest.raises(AdapterError, match="must not be empty"):
            DatabaseAdapter("", query="SELECT 1")

    def test_empty_query_raises(self) -> None:
        with pytest.raises(AdapterError, match="must not be empty"):
            DatabaseAdapter("sqlite:///x.db", query="")

    def test_bad_sql_raises(self, sqlite_url: str) -> None:
        adapter = DatabaseAdapter(sqlite_url, query="SELECT * FROM no_such_table")
        with pytest.raises(AdapterError, match="query failed"):
            list(adapter.read())

    def test_read_batch(self, sqlite_url: str) -> None:
        adapter = DatabaseAdapter(sqlite_url, query="SELECT * FROM students")
        batches = list(adapter.read_batch(batch_size=2))
        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 1


# =====================================================================
# read_batch default implementation
# =====================================================================


class TestReadBatch:
    """Default read_batch() from SourceAdapter works across all adapters."""

    def test_exact_multiple(self) -> None:
        data = [{"i": i} for i in range(6)]
        batches = list(DictAdapter(data).read_batch(batch_size=3))
        assert len(batches) == 2
        assert all(len(b) == 3 for b in batches)

    def test_single_item_batches(self) -> None:
        batches = list(DictAdapter([{"x": 1}, {"x": 2}]).read_batch(batch_size=1))
        assert len(batches) == 2

    def test_batch_larger_than_data(self) -> None:
        batches = list(DictAdapter([{"x": 1}]).read_batch(batch_size=100))
        assert len(batches) == 1
        assert batches[0] == [{"x": 1}]
