"""Tests for validation report generators (HTML, JSON, CSV, Parquet)."""

from __future__ import annotations

from ceds_jsonld.report import generate_html_report
from ceds_jsonld.validator import FieldIssue, ValidationResult


class TestHTMLReport:
    def test_generate_passing_report(self) -> None:
        result = ValidationResult(
            conforms=True,
            record_count=5,
            error_count=0,
            warning_count=0,
        )
        html = generate_html_report(result, shape="person")
        assert "<html" in html
        assert "PASSED" in html

    def test_generate_failing_report(self) -> None:
        result = ValidationResult(
            conforms=False,
            record_count=3,
            error_count=2,
            warning_count=1,
        )
        result.add_issue(
            "record-1",
            FieldIssue(
                severity="error",
                property_path="FirstName",
                message="Required field missing",
            ),
        )
        html = generate_html_report(result, shape="person")
        assert "FAILED" in html
        assert "FirstName" in html

    def test_report_is_self_contained(self) -> None:
        result = ValidationResult(
            conforms=True,
            record_count=1,
            error_count=0,
            warning_count=0,
        )
        html = generate_html_report(result, shape="person")
        assert "http://" not in html
        assert "https://" not in html

    def test_html_report_shape_fallback(self) -> None:
        """When shape= is omitted, HTML should fall back to result.shape_name (#53)."""
        result = ValidationResult(
            conforms=True,
            record_count=1,
            error_count=0,
            warning_count=0,
            shape_name="person",
        )
        html = generate_html_report(result)
        assert "person" in html

    def test_html_report_expected_actual_columns(self) -> None:
        """HTML table must include Expected and Actual columns (#54)."""
        result = ValidationResult(
            conforms=False,
            record_count=1,
            error_count=1,
            warning_count=0,
        )
        result.add_issue(
            "rec-1",
            FieldIssue(
                severity="error",
                property_path="BirthDate",
                message="Invalid format",
                expected="YYYY-MM-DD",
                actual="not-a-date",
            ),
        )
        html = generate_html_report(result, shape="person")
        assert "<th>Expected</th>" in html
        assert "<th>Actual</th>" in html
        assert "YYYY-MM-DD" in html
        assert "not-a-date" in html


class TestJSONReport:
    def test_generate_json_report_conforming(self) -> None:
        """JSON report for conforming result has correct structure."""
        import json

        from ceds_jsonld.report import generate_json_report

        result = ValidationResult(shape_name="person")
        text = generate_json_report(result, shape="person")
        data = json.loads(text)
        assert data["conforms"] is True
        assert data["shape_name"] == "person"
        assert data["issues"] == []

    def test_generate_json_report_with_issues(self) -> None:
        """JSON report includes flattened issues."""
        import json

        from ceds_jsonld.report import generate_json_report

        result = ValidationResult()
        result.add_issue("rec-1", FieldIssue(property_path="a", message="bad"))
        text = generate_json_report(result)
        data = json.loads(text)
        assert len(data["issues"]) == 1
        assert data["issues"][0]["record_id"] == "rec-1"


class TestCSVReport:
    def test_generate_csv_report_with_issues(self) -> None:
        """CSV report contains header row and issue data."""
        from ceds_jsonld.report import generate_csv_report

        result = ValidationResult(shape_name="person")
        result.add_issue("rec-1", FieldIssue(property_path="a", message="bad"))
        csv_text = generate_csv_report(result)
        assert "rec-1" in csv_text
        assert "property_path" in csv_text  # header row

    def test_generate_csv_report_empty(self) -> None:
        """CSV report for conforming result has header but no data rows."""
        from ceds_jsonld.report import generate_csv_report

        result = ValidationResult(shape_name="person")
        csv_text = generate_csv_report(result)
        lines = csv_text.strip().split("\n")
        assert len(lines) == 1  # header only
        assert "record_id" in lines[0]


class TestParquetReport:
    def test_generate_parquet_report(self, tmp_path) -> None:
        """Parquet report creates a readable file with correct data."""
        import pandas as pd

        from ceds_jsonld.report import generate_parquet_report

        result = ValidationResult(shape_name="person")
        result.add_issue("rec-1", FieldIssue(property_path="a", message="bad"))
        path = str(tmp_path / "report.parquet")
        generate_parquet_report(result, path)
        df = pd.read_parquet(path)
        assert len(df) == 1
        assert df.iloc[0]["record_id"] == "rec-1"

    def test_generate_parquet_report_empty(self, tmp_path) -> None:
        """Parquet report for conforming result creates file with zero rows."""
        import pandas as pd

        from ceds_jsonld.report import generate_parquet_report

        result = ValidationResult(shape_name="person")
        path = str(tmp_path / "report.parquet")
        generate_parquet_report(result, path)
        df = pd.read_parquet(path)
        assert len(df) == 0
        assert "record_id" in df.columns
