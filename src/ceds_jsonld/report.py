"""Self-contained validation report generators (HTML, JSON, CSV, Parquet)."""

from __future__ import annotations

from html import escape
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ceds_jsonld.validator import ValidationResult

_PAGE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Validation Report — $shape</title>
<style>
body{font-family:system-ui,sans-serif;margin:2rem;color:#1a1a1a;background:#fafafa}
h1{margin-bottom:.25rem}
.badge{display:inline-block;padding:.25rem .75rem;border-radius:4px;font-weight:700;color:#fff}
.pass{background:#2e7d32}
.fail{background:#c62828}
table{border-collapse:collapse;width:100%;margin-top:1rem}
th,td{border:1px solid #ccc;padding:.4rem .6rem;text-align:left}
th{background:#e0e0e0}
tr.error td{background:#ffebee}
tr.warning td{background:#fff8e1}
.summary{margin-top:1rem;font-size:.95rem}
</style>
</head>
<body>
<h1>CEDS Validation Report</h1>
<p>Shape: <strong>$shape</strong></p>
<p>Status: <span class="badge $badge_class">$status</span></p>
<div class="summary">
<p>Records: $record_count &nbsp;|&nbsp; Errors: $error_count &nbsp;|&nbsp; Warnings: $warning_count</p>
</div>
$issues_section
</body>
</html>""")

_ISSUES_TABLE_HEADER = (
    "<table><tr><th>Record</th><th>Severity</th><th>Property</th><th>Message</th><th>Expected</th><th>Actual</th></tr>"
)


def generate_html_report(result: ValidationResult, *, shape: str = "") -> str:
    """Build a self-contained HTML report from a :class:`ValidationResult`.

    Args:
        result: The validation result to render.
        shape: Shape name shown in the report header.

    Returns:
        Complete HTML string (no external dependencies).
    """
    if not shape and result.shape_name:
        shape = result.shape_name

    status = "PASSED" if result.conforms else "FAILED"
    badge_class = "pass" if result.conforms else "fail"

    issues_section = ""
    if result.issues:
        rows: list[str] = []
        for record_id, issues in result.issues.items():
            for issue in issues:
                sev = escape(issue.severity)
                rows.append(
                    f'<tr class="{sev}">'
                    f"<td>{escape(str(record_id))}</td>"
                    f"<td>{sev}</td>"
                    f"<td>{escape(issue.property_path)}</td>"
                    f"<td>{escape(issue.message)}</td>"
                    f"<td>{escape(issue.expected or '')}</td>"
                    f"<td>{escape(issue.actual or '')}</td>"
                    "</tr>"
                )
        issues_section = _ISSUES_TABLE_HEADER + "".join(rows) + "</table>"

    return _PAGE.substitute(
        shape=escape(shape),
        status=status,
        badge_class=badge_class,
        record_count=result.record_count,
        error_count=result.error_count,
        warning_count=result.warning_count,
        issues_section=issues_section,
    )


def generate_json_report(result: ValidationResult, *, shape: str = "") -> str:
    """Serialize a ValidationResult to a JSON string.

    Uses orjson if available, falls back to stdlib json.
    Includes run metadata and flattened issues list.

    Args:
        result: The validation result to render.
        shape: Shape name override (used if ``result.shape_name`` is empty).

    Returns:
        Pretty-printed JSON string.
    """
    data = result.to_dict()
    if shape and not data.get("shape_name"):
        data["shape_name"] = shape

    try:
        import orjson

        return orjson.dumps(data, option=orjson.OPT_INDENT_2).decode()
    except ImportError:
        import json

        return json.dumps(data, indent=2, default=str)


def generate_csv_report(result: ValidationResult, *, shape: str = "") -> str:
    """Serialize a ValidationResult to a CSV string.

    One row per issue.  Columns: run_id, timestamp, shape_name, source_name,
    record_id, property_path, severity, message, expected, actual.

    Args:
        result: The validation result to render.
        shape: Shape name override (used if ``result.shape_name`` is empty).

    Returns:
        CSV-formatted string (including header row).
    """
    if shape and not result.shape_name:
        result = _with_shape(result, shape)
    df = result.to_dataframe()
    df = _sanitize_csv_dataframe(df)
    return str(df.to_csv(index=False))


def generate_parquet_report(
    result: ValidationResult,
    path: str | Path,
    *,
    shape: str = "",
) -> None:
    """Write a ValidationResult to a Parquet file.

    Args:
        result: The validation result to render.
        path: File path for the Parquet output.
        shape: Shape name override (used if ``result.shape_name`` is empty).
    """
    if shape and not result.shape_name:
        result = _with_shape(result, shape)
    df = result.to_dataframe()
    df.to_parquet(path, index=False, engine="pyarrow")


def _with_shape(result: ValidationResult, shape: str) -> ValidationResult:
    """Return *result* with ``shape_name`` set without mutating the original."""
    from dataclasses import replace

    return replace(result, shape_name=shape)


_CSV_FORMULA_TRIGGERS = frozenset("=+-@")


def _sanitize_csv_value(value: str) -> str:
    """Prefix values that start with formula trigger characters (CWE-1236)."""
    if value and value[0] in _CSV_FORMULA_TRIGGERS:
        return "'" + value
    return value


def _sanitize_csv_dataframe(df: Any) -> Any:
    """Apply formula-injection escaping to all string columns in a DataFrame."""
    import pandas as pd

    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].map(
                lambda v: _sanitize_csv_value(v) if isinstance(v, str) else v  # noqa: B023
            )
    return df
