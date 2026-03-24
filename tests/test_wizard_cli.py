"""Tests for map-wizard CLI command."""

from __future__ import annotations

import csv

import pytest
from click.testing import CliRunner

from ceds_jsonld.cli import cli


@pytest.fixture()
def sample_csv(tmp_path):
    path = tmp_path / "students.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["FirstName", "LastName", "DOB"])
        w.writeheader()
        w.writerow({"FirstName": "Jane", "LastName": "Doe", "DOB": "1990-01-15"})
        w.writerow({"FirstName": "John", "LastName": "Smith", "DOB": "1985-03-22"})
    return str(path)


class TestMapWizardCLI:
    def test_map_wizard_basic(self, sample_csv, tmp_path) -> None:
        runner = CliRunner()
        output = tmp_path / "mapping.yaml"
        result = runner.invoke(
            cli,
            [
                "map-wizard",
                "--input",
                sample_csv,
                "--shape",
                "person",
                "--output",
                str(output),
                "--no-llm",
            ],
        )
        assert result.exit_code == 0, result.output
        assert output.exists()

    def test_map_wizard_stdout(self, sample_csv) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "map-wizard",
                "--input",
                sample_csv,
                "--shape",
                "person",
                "--no-llm",
            ],
        )
        assert result.exit_code == 0
        assert "shape" in result.output

    def test_map_wizard_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["map-wizard", "--help"])
        assert result.exit_code == 0
        assert "input" in result.output.lower()
