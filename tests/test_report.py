"""Tests for HTML validation report generator."""

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
