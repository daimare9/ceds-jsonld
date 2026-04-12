"""Tests for the ceds-jsonld CLI commands.

Uses Click's CliRunner for isolated invocation testing — no subprocess needed.
All tests use real shape data and real adapters.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from ceds_jsonld.cli import cli

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE = Path(__file__).resolve().parent.parent / "src" / "ceds_jsonld" / "ontologies" / "person"
PERSON_SAMPLE = _BASE / "person_sample.csv"
PERSON_SHACL = _BASE / "Person_SHACL.ttl"
PERSON_CONTEXT = _BASE / "person_context.json"


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    """Copy sample CSV to a temp directory so paths are predictable."""
    dest = tmp_path / "person_sample.csv"
    dest.write_bytes(PERSON_SAMPLE.read_bytes())
    return dest


# ---------------------------------------------------------------------------
# Top-level CLI
# ---------------------------------------------------------------------------


class TestCLIMain:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ceds-jsonld" in result.output
        assert "convert" in result.output

    def test_version(self, runner: CliRunner) -> None:
        from ceds_jsonld import __version__

        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


# ---------------------------------------------------------------------------
# list-shapes
# ---------------------------------------------------------------------------


class TestListShapes:
    def test_lists_person(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["list-shapes"])
        assert result.exit_code == 0
        assert "person" in result.output

    def test_shows_count(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["list-shapes"])
        assert "Available shapes" in result.output

    def test_custom_shapes_dir_nonexistent(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["list-shapes", "--shapes-dir", "/nonexistent"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------


class TestConvert:
    def test_csv_to_json(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.json"
        result = runner.invoke(
            cli,
            [
                "convert",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "-o",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert out.exists()
        docs = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(docs, list)
        assert len(docs) > 0
        assert docs[0]["@type"] == "Person"

    def test_csv_to_ndjson(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.ndjson"
        result = runner.invoke(
            cli,
            [
                "convert",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "-o",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert out.exists()
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) > 0
        doc = json.loads(lines[0])
        assert doc["@type"] == "Person"

    def test_explicit_format_ndjson(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.json"  # .json extension but forced ndjson
        result = runner.invoke(
            cli,
            [
                "convert",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "-o",
                str(out),
                "-f",
                "ndjson",
            ],
        )
        assert result.exit_code == 0, result.output
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) > 0
        # Each line should be valid JSON
        for line in lines:
            json.loads(line)

    def test_compact_output(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.json"
        result = runner.invoke(
            cli,
            [
                "convert",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "-o",
                str(out),
                "--compact",
            ],
        )
        assert result.exit_code == 0, result.output
        content = out.read_text(encoding="utf-8")
        # Compact output has no indentation
        assert "\n  " not in content or content.count("\n") < 10

    def test_missing_input(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "convert",
                "-s",
                "person",
                "-i",
                str(tmp_path / "nope.csv"),
                "-o",
                str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0

    def test_bad_shape(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "convert",
                "-s",
                "nonexistent",
                "-i",
                str(sample_csv),
                "-o",
                str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0
        assert "nonexistent" in result.output or "nonexistent" in (result.stderr or "")

    def test_writes_byte_count(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.json"
        result = runner.invoke(
            cli,
            [
                "convert",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "-o",
                str(out),
            ],
        )
        assert result.exit_code == 0
        assert "bytes" in result.output


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_data_passes(self, runner: CliRunner, sample_csv: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "validate",
                "-s",
                "person",
                "-i",
                str(sample_csv),
            ],
        )
        assert result.exit_code == 0
        assert "PASSED" in result.output

    def test_report_mode(self, runner: CliRunner, sample_csv: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "validate",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "--mode",
                "report",
            ],
        )
        assert result.exit_code == 0

    def test_bad_shape(self, runner: CliRunner, sample_csv: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "validate",
                "-s",
                "nonexistent",
                "-i",
                str(sample_csv),
            ],
        )
        assert result.exit_code != 0

    def test_html_report(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        report_path = tmp_path / "report.html"
        result = runner.invoke(
            cli,
            [
                "validate",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "--report-format",
                "html",
                "--report-path",
                str(report_path),
            ],
        )
        assert result.exit_code == 0
        assert report_path.exists()
        html = report_path.read_text(encoding="utf-8")
        assert "<html" in html
        assert "PASSED" in html

    def test_json_report(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        import json

        report_path = tmp_path / "report.json"
        result = runner.invoke(
            cli,
            [
                "validate",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "--report-format",
                "json",
                "--report-path",
                str(report_path),
            ],
        )
        assert result.exit_code == 0
        assert report_path.exists()
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert "conforms" in data

    def test_csv_report(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        report_path = tmp_path / "report.csv"
        result = runner.invoke(
            cli,
            [
                "validate",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "--report-format",
                "csv",
                "--report-path",
                str(report_path),
            ],
        )
        assert result.exit_code == 0
        assert report_path.exists()
        text = report_path.read_text(encoding="utf-8")
        assert "record_id" in text  # header row present

    def test_parquet_report(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        import pandas as pd

        report_path = tmp_path / "report.parquet"
        result = runner.invoke(
            cli,
            [
                "validate",
                "-s",
                "person",
                "-i",
                str(sample_csv),
                "--report-format",
                "parquet",
                "--report-path",
                str(report_path),
            ],
        )
        assert result.exit_code == 0
        assert report_path.exists()
        df = pd.read_parquet(report_path)
        assert "record_id" in df.columns

    def test_report_format_default_path(self, runner: CliRunner, sample_csv: Path, tmp_path: Path) -> None:
        """When --report-path is omitted, a default filename is used."""
        import os

        original_dir = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = runner.invoke(
                cli,
                [
                    "validate",
                    "-s",
                    "person",
                    "-i",
                    str(sample_csv),
                    "--report-format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            assert (tmp_path / "validation_report.json").exists()
        finally:
            os.chdir(original_dir)


# ---------------------------------------------------------------------------
# introspect
# ---------------------------------------------------------------------------


class TestIntrospect:
    def test_text_output(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "introspect",
                "--shacl",
                str(PERSON_SHACL),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "PersonShape" in result.output

    def test_json_output(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "introspect",
                "--shacl",
                str(PERSON_SHACL),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "local_name" in data

    def test_bad_file(self, runner: CliRunner, tmp_path: Path) -> None:
        bad = tmp_path / "bad.ttl"
        bad.write_text("not valid turtle", encoding="utf-8")
        result = runner.invoke(
            cli,
            [
                "introspect",
                "--shacl",
                str(bad),
            ],
        )
        assert result.exit_code != 0

    def test_markdown_output(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "introspect",
                "--shacl",
                str(PERSON_SHACL),
                "--format",
                "markdown",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "| Property" in result.output
        assert "FirstName" in result.output


# ---------------------------------------------------------------------------
# generate-mapping
# ---------------------------------------------------------------------------


class TestGenerateMapping:
    def test_stdout(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "generate-mapping",
                "--shacl",
                str(PERSON_SHACL),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = yaml.safe_load(result.output)
        assert "shape" in parsed
        assert "properties" in parsed

    def test_to_file(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "mapping.yaml"
        result = runner.invoke(
            cli,
            [
                "generate-mapping",
                "--shacl",
                str(PERSON_SHACL),
                "-o",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert out.exists()
        parsed = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert "shape" in parsed

    def test_with_context_file(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "generate-mapping",
                "--shacl",
                str(PERSON_SHACL),
                "--context-file",
                str(PERSON_CONTEXT),
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = yaml.safe_load(result.output)
        assert "properties" in parsed

    def test_with_context_url(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "generate-mapping",
                "--shacl",
                str(PERSON_SHACL),
                "--context-url",
                "https://example.org/context.json",
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = yaml.safe_load(result.output)
        assert parsed["context_url"] == "https://example.org/context.json"


# ---------------------------------------------------------------------------
# benchmark
# ---------------------------------------------------------------------------


class TestBenchmark:
    def test_runs_with_small_count(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "benchmark",
                "-s",
                "person",
                "-n",
                "100",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Results:" in result.output
        assert "rec/s" in result.output

    def test_shows_per_record_timing(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "benchmark",
                "-s",
                "person",
                "-n",
                "50",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Per record:" in result.output

    def test_bad_shape(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "benchmark",
                "-s",
                "nonexistent",
            ],
        )
        assert result.exit_code != 0
