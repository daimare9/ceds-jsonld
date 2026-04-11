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
