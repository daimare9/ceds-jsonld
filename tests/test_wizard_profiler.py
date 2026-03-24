"""Tests for ColumnProfiler — source column analysis."""

from __future__ import annotations

import pytest

from ceds_jsonld.wizard.profiler import ColumnProfile, ColumnProfiler


class TestColumnProfile:
    """ColumnProfile dataclass basic tests."""

    def test_column_profile_fields(self) -> None:
        p = ColumnProfile(
            name="DOB",
            normalized="dob",
            sample_values=["1990-01-15", "1985-03-22"],
            inferred_type="date",
            null_rate=0.0,
            unique_rate=1.0,
            contains_delimiter=None,
            value_pattern="YYYY-MM-DD",
            distinct_values=["1990-01-15", "1985-03-22"],
        )
        assert p.name == "DOB"
        assert p.inferred_type == "date"


class TestColumnProfiler:
    """ColumnProfiler analysis tests."""

    def test_profile_from_dicts_basic(self) -> None:
        rows = [
            {"FirstName": "Jane", "Age": "25", "DOB": "1990-01-15"},
            {"FirstName": "John", "Age": "30", "DOB": "1985-03-22"},
            {"FirstName": "Alice", "Age": "28", "DOB": "1992-07-10"},
        ]
        profiler = ColumnProfiler(sample_size=10)
        profiles = profiler.profile_from_dicts(rows)

        assert len(profiles) == 3
        by_name = {p.name: p for p in profiles}
        assert "FirstName" in by_name
        assert "DOB" in by_name

    def test_type_inference_date(self) -> None:
        rows = [
            {"DOB": "1990-01-15"},
            {"DOB": "1985-03-22"},
            {"DOB": "1992-07-10"},
            {"DOB": "2000-12-01"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        dob = profiles[0]
        assert dob.inferred_type == "date"

    def test_type_inference_integer(self) -> None:
        rows = [{"Age": "25"}, {"Age": "30"}, {"Age": "28"}]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].inferred_type == "integer"

    def test_type_inference_float(self) -> None:
        rows = [{"GPA": "3.5"}, {"GPA": "2.8"}, {"GPA": "3.9"}]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].inferred_type == "float"

    def test_type_inference_boolean(self) -> None:
        rows = [{"Active": "true"}, {"Active": "false"}, {"Active": "true"}]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].inferred_type == "boolean"

    def test_null_rate(self) -> None:
        rows = [
            {"Name": "Jane"},
            {"Name": ""},
            {"Name": None},
            {"Name": "John"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].null_rate == pytest.approx(0.5)

    def test_delimiter_detection_pipe(self) -> None:
        rows = [
            {"IDs": "SSN|12345"},
            {"IDs": "DL|67890"},
            {"IDs": "SSN|11111"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].contains_delimiter == "|"

    def test_low_cardinality_distinct_values(self) -> None:
        rows = [
            {"Gender": "Male"},
            {"Gender": "Female"},
            {"Gender": "Male"},
            {"Gender": "Female"},
            {"Gender": "Male"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert set(profiles[0].distinct_values) == {"Male", "Female"}

    def test_high_cardinality_no_distinct(self) -> None:
        rows = [{"Name": f"Person_{i}"} for i in range(50)]
        profiler = ColumnProfiler(distinct_threshold=15)
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].distinct_values == []

    def test_unique_rate(self) -> None:
        rows = [
            {"ID": "A"},
            {"ID": "B"},
            {"ID": "C"},
            {"ID": "A"},
        ]
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_dicts(rows)
        assert profiles[0].unique_rate == pytest.approx(0.75)

    def test_profile_from_csv(self, tmp_path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("Name,Age\nJane,25\nJohn,30\n", encoding="utf-8")
        profiler = ColumnProfiler()
        profiles = profiler.profile_from_csv(str(csv_file))
        assert len(profiles) == 2
