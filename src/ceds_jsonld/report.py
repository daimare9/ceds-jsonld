"""Self-contained HTML validation report generator."""

from __future__ import annotations

from html import escape
from string import Template
from typing import TYPE_CHECKING

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

_ISSUES_TABLE_HEADER = "<table><tr><th>Record</th><th>Severity</th><th>Property</th><th>Message</th></tr>"


def generate_html_report(result: ValidationResult, *, shape: str = "") -> str:
    """Build a self-contained HTML report from a :class:`ValidationResult`.

    Args:
        result: The validation result to render.
        shape: Shape name shown in the report header.

    Returns:
        Complete HTML string (no external dependencies).
    """
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
