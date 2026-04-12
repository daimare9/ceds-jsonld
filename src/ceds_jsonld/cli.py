"""Command-line interface for ceds-jsonld.

Provides the ``ceds-jsonld`` CLI with commands for converting data to JSON-LD,
validating documents, introspecting SHACL shapes, generating mapping templates,
listing available shapes, and running performance benchmarks.

Requires the ``[cli]`` extra: ``pip install ceds-jsonld[cli]``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

try:
    import click
except ImportError:
    _msg = "The ceds-jsonld CLI requires the 'click' package. Install it with: pip install ceds-jsonld[cli]"
    print(_msg, file=sys.stderr)  # noqa: T201
    sys.exit(1)

from ceds_jsonld import __version__
from ceds_jsonld.exceptions import (
    PipelineError,
    ShapeLoadError,
    ValidationError,
)
from ceds_jsonld.registry import ShapeRegistry
from ceds_jsonld.serializer import dumps

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_registry(
    shape: str,
    *,
    shapes_dir: str | None = None,
) -> tuple[ShapeRegistry, Any]:
    """Load a registry and shape definition.

    Args:
        shape: Shape name.
        shapes_dir: Optional extra directory to search for shapes.

    Returns:
        Tuple of (registry, shape_definition).
    """
    registry = ShapeRegistry()
    if shapes_dir is not None:
        registry.add_search_dir(shapes_dir)
    try:
        shape_def = registry.load_shape(shape)
    except ShapeLoadError as exc:
        available = registry.list_available()
        raise click.ClickException(f"Shape '{shape}' not found. Available shapes: {available}\n{exc}") from exc
    return registry, shape_def


def _make_adapter(input_path: str, *, sheet: str | None = None) -> Any:
    """Create the appropriate adapter for the given file extension.

    Args:
        input_path: Path to the input data file.
        sheet: Optional sheet name for Excel files.

    Returns:
        A SourceAdapter instance.

    Raises:
        click.ClickException: If the file type is unsupported or the adapter
            dependency is missing.
    """
    from ceds_jsonld.adapters.csv_adapter import CSVAdapter
    from ceds_jsonld.adapters.ndjson_adapter import NDJSONAdapter

    p = Path(input_path)
    if not p.exists():
        raise click.ClickException(f"Input file not found: {p}")

    suffix = p.suffix.lower()

    if suffix == ".csv":
        return CSVAdapter(input_path)
    elif suffix == ".ndjson" or suffix == ".jsonl":
        return NDJSONAdapter(input_path)
    elif suffix in (".xlsx", ".xls"):
        try:
            from ceds_jsonld.adapters.excel_adapter import ExcelAdapter

            kwargs: dict[str, Any] = {}
            if sheet is not None:
                kwargs["sheet_name"] = sheet
            return ExcelAdapter(input_path, **kwargs)
        except ImportError as exc:
            raise click.ClickException(
                "Excel support requires openpyxl. Install with: pip install ceds-jsonld[excel]"
            ) from exc
    else:
        raise click.ClickException(
            f"Unsupported file extension '{suffix}'. Supported: .csv, .ndjson, .jsonl, .xlsx, .xls"
        )


# ---------------------------------------------------------------------------
# Main CLI group
# ---------------------------------------------------------------------------


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__)
def cli() -> None:
    """ceds-jsonld — Convert education data to CEDS-compliant JSON-LD."""


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "-s",
    "--shape",
    required=True,
    help="Shape name (e.g. 'person').",
)
@click.option(
    "-i",
    "--input",
    "input_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to input data file (CSV, Excel, or NDJSON).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(),
    help="Path to output file (.json or .ndjson).",
)
@click.option(
    "-f",
    "--format",
    "output_format",
    type=click.Choice(["json", "ndjson"], case_sensitive=False),
    default=None,
    help="Output format. Inferred from extension if omitted.",
)
@click.option(
    "--shapes-dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Additional directory to search for shape definitions.",
)
@click.option(
    "--sheet",
    default=None,
    help="Sheet name for Excel files.",
)
@click.option(
    "--validate/--no-validate",
    default=False,
    help="Run pre-build validation before building.",
)
@click.option(
    "--pretty/--compact",
    default=True,
    help="Pretty-print JSON output (default: pretty).",
)
def convert(
    shape: str,
    input_path: str,
    output_path: str,
    output_format: str | None,
    shapes_dir: str | None,
    sheet: str | None,
    validate: bool,
    pretty: bool,
) -> None:
    """Convert a data file to JSON-LD.

    Reads data from a CSV, Excel, or NDJSON file, maps it to the specified
    SHACL shape, and writes JSON-LD output to a file.

    Examples:

        ceds-jsonld convert -s person -i students.csv -o students.json

        ceds-jsonld convert -s person -i data.xlsx --sheet Sheet1 -o out.ndjson

        ceds-jsonld convert -s person -i data.csv -o out.json --validate --compact
    """
    from ceds_jsonld.pipeline import Pipeline

    # Resolve output format
    if output_format is None:
        ext = Path(output_path).suffix.lower()
        if ext == ".ndjson" or ext == ".jsonl":
            output_format = "ndjson"
        else:
            output_format = "json"

    registry, _ = _load_registry(shape, shapes_dir=shapes_dir)
    adapter = _make_adapter(input_path, sheet=sheet)

    pipeline = Pipeline(source=adapter, shape=shape, registry=registry)

    try:
        if output_format == "ndjson":
            result = pipeline.to_ndjson(output_path)
        else:
            result = pipeline.to_json(output_path, pretty=pretty)
    except PipelineError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f"Wrote {result.bytes_written:,} bytes ({result.records_out} records) "
        f"to {output_path} ({result.elapsed_seconds:.2f}s, "
        f"{result.records_per_second:.0f} rec/s)"
    )


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "-s",
    "--shape",
    required=True,
    help="Shape name (e.g. 'person').",
)
@click.option(
    "-i",
    "--input",
    "input_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to input data file.",
)
@click.option(
    "--shapes-dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Additional directory to search for shape definitions.",
)
@click.option(
    "--sheet",
    default=None,
    help="Sheet name for Excel files.",
)
@click.option(
    "--mode",
    type=click.Choice(["strict", "report", "sample"], case_sensitive=False),
    default="report",
    help="Validation mode (default: report).",
)
@click.option(
    "--shacl/--no-shacl",
    default=False,
    help="Also run full SHACL validation (slow).",
)
@click.option(
    "--sample-rate",
    type=float,
    default=0.01,
    help="SHACL sample rate in sample mode (default: 0.01 = 1%%).",
)
@click.option(
    "--report-format",
    "report_format",
    type=click.Choice(["html", "json", "csv", "parquet"], case_sensitive=False),
    default=None,
    help="Generate a validation report in this format.",
)
@click.option(
    "--report-path",
    "report_path",
    type=click.Path(),
    default=None,
    help="Output path for the validation report (default: auto-named in cwd).",
)
def validate(
    shape: str,
    input_path: str,
    shapes_dir: str | None,
    sheet: str | None,
    mode: str,
    shacl: bool,
    sample_rate: float,
    report_format: str | None,
    report_path: str | None,
) -> None:
    """Validate data against a SHACL shape.

    Runs pre-build validation on every record. Optionally also runs full
    SHACL round-trip validation (expensive).

    Examples:

        ceds-jsonld validate -s person -i students.csv

        ceds-jsonld validate -s person -i students.csv --shacl --mode sample
    """
    from ceds_jsonld.pipeline import Pipeline

    registry, _ = _load_registry(shape, shapes_dir=shapes_dir)
    adapter = _make_adapter(input_path, sheet=sheet)

    pipeline = Pipeline(source=adapter, shape=shape, registry=registry)

    t0 = time.perf_counter()
    try:
        result = pipeline.validate(mode=mode, shacl=shacl, sample_rate=sample_rate)
    except (PipelineError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc

    elapsed = time.perf_counter() - t0

    if report_format:
        from ceds_jsonld.report import (
            generate_csv_report,
            generate_html_report,
            generate_json_report,
            generate_parquet_report,
        )

        ext = report_format.lower()
        if not report_path:
            report_path = f"validation_report.{ext}"

        if ext == "html":
            html = generate_html_report(result, shape=shape)
            Path(report_path).write_text(html, encoding="utf-8")
        elif ext == "json":
            json_str = generate_json_report(result, shape=shape)
            Path(report_path).write_text(json_str, encoding="utf-8")
        elif ext == "csv":
            csv_str = generate_csv_report(result, shape=shape)
            Path(report_path).write_text(csv_str, encoding="utf-8")
        elif ext == "parquet":
            generate_parquet_report(result, Path(report_path), shape=shape)

        click.echo(f"{ext.upper()} report written to {report_path}")

    if result.conforms:
        click.secho(
            f"PASSED — {result.record_count} records validated ({elapsed:.2f}s)",
            fg="green",
        )
    else:
        click.secho(
            f"FAILED — {result.error_count} errors, {result.warning_count} warnings "
            f"across {result.record_count} records ({elapsed:.2f}s)",
            fg="red",
        )
        for rec_id, issues in result.issues.items():
            click.echo(f"\n  Record: {rec_id}")
            for issue in issues:
                color = "red" if issue.severity == "error" else "yellow"
                click.secho(f"    [{issue.severity}] {issue.property_path}: {issue.message}", fg=color)

        sys.exit(1)


# ---------------------------------------------------------------------------
# introspect
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--shacl",
    "shacl_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to a SHACL Turtle (.ttl) file.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON (shorthand for --format json).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json", "markdown"], case_sensitive=False),
    default=None,
    help="Output format: text (default), json, or markdown.",
)
def introspect(shacl_path: str, as_json: bool, fmt: str | None) -> None:
    """Inspect a SHACL shape file and display its structure.

    Shows the shape tree including property names, datatypes, cardinalities,
    and nested sub-shapes.

    Examples:

        ceds-jsonld introspect --shacl ontologies/person/Person_SHACL.ttl

        ceds-jsonld introspect --shacl Person_SHACL.ttl --json

        ceds-jsonld introspect --shacl Person_SHACL.ttl --format markdown
    """
    from ceds_jsonld.introspector import SHACLIntrospector

    # --json flag is shorthand for --format json
    if as_json and fmt is None:
        fmt = "json"
    elif fmt is None:
        fmt = "text"

    try:
        intro = SHACLIntrospector(shacl_path)
    except ShapeLoadError as exc:
        raise click.ClickException(str(exc)) from exc

    if fmt == "json":
        data = intro.to_dict()
        click.echo(dumps(data, pretty=True).decode())
    elif fmt == "markdown":
        tree = intro.shape_tree()
        # Try to auto-discover context for friendly name resolution
        context = _find_sibling_context(shacl_path)
        _print_markdown_table(tree, context)
    else:
        tree = intro.shape_tree()
        _print_shape_tree(tree, indent=0)


def _print_shape_tree(shape: Any, indent: int = 0) -> None:
    """Print a human-readable representation of a shape tree."""
    prefix = "  " * indent
    target = f" → {shape.target_class_local}" if shape.target_class_local else ""
    closed = " (closed)" if shape.is_closed else ""
    click.echo(f"{prefix}{shape.local_name}{target}{closed}")

    for prop in shape.properties:
        req = " [required]" if prop.min_count and prop.min_count > 0 else ""
        dtype = f" : {prop.datatype.split('#')[-1] if prop.datatype else 'object'}"

        if prop.allowed_values:
            values = ", ".join(v.split("/")[-1].split("#")[-1] for v in prop.allowed_values[:5])
            extra = ", ..." if len(prop.allowed_values) > 5 else ""
            dtype += f" [{values}{extra}]"

        name = prop.name or prop.path_local
        click.echo(f"{prefix}  ├─ {name}{dtype}{req}")

    for _name, child in shape.children.items():
        _print_shape_tree(child, indent=indent + 1)


def _find_sibling_context(shacl_path: str) -> dict[str, str] | None:
    """Auto-discover a *_context.json file in the same directory as the SHACL file."""
    import glob
    import json as _json

    parent = Path(shacl_path).parent
    candidates = glob.glob(str(parent / "*_context.json"))
    if not candidates:
        return None
    with open(candidates[0]) as f:
        data = _json.load(f)
    ctx = data.get("@context", data)
    return ctx if isinstance(ctx, dict) else None


def _collect_properties_flat(
    shape: Any,
    parent: str = "",
    iri_to_name: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Recursively collect properties into a flat list for markdown output."""
    rows: list[dict[str, str]] = []
    shape_label = parent or shape.local_name
    lookup = iri_to_name or {}

    for prop in shape.properties:
        name = lookup.get(prop.path, prop.name or prop.path_local)
        dtype = prop.datatype.split("#")[-1] if prop.datatype else "object"
        required = "Yes" if prop.min_count and prop.min_count > 0 else ""
        concept = ""
        if prop.allowed_values:
            vals = [v.split("/")[-1].split("#")[-1] for v in prop.allowed_values[:5]]
            extra = ", ..." if len(prop.allowed_values) > 5 else ""
            concept = ", ".join(vals) + extra

        rows.append(
            {
                "Property": name,
                "Sub-Shape": shape_label,
                "Type": dtype,
                "Required": required,
                "Concept Scheme": concept,
            }
        )

    for _name, child in shape.children.items():
        rows.extend(_collect_properties_flat(child, parent=child.local_name, iri_to_name=lookup))

    return rows


def _print_markdown_table(
    shape: Any,
    context: dict[str, str] | None = None,
) -> None:
    """Print shape properties as a Markdown table."""
    from ceds_jsonld.introspector import SHACLIntrospector

    iri_to_name = SHACLIntrospector._build_iri_to_name(context) if context else None
    rows = _collect_properties_flat(shape, iri_to_name=iri_to_name)
    headers = ["Property", "Sub-Shape", "Type", "Required", "Concept Scheme"]

    # Calculate column widths
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            widths[h] = max(widths[h], len(row.get(h, "")))

    # Header
    header_line = "| " + " | ".join(h.ljust(widths[h]) for h in headers) + " |"
    sep_line = "| " + " | ".join("-" * widths[h] for h in headers) + " |"
    click.echo(header_line)
    click.echo(sep_line)

    # Rows
    for row in rows:
        line = "| " + " | ".join(row.get(h, "").ljust(widths[h]) for h in headers) + " |"
        click.echo(line)


# ---------------------------------------------------------------------------
# generate-mapping
# ---------------------------------------------------------------------------


@cli.command("generate-mapping")
@click.option(
    "--shacl",
    "shacl_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to a SHACL Turtle (.ttl) file.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="Output YAML file path. Prints to stdout if omitted.",
)
@click.option(
    "--context-url",
    default="",
    help="JSON-LD @context URL for the generated mapping.",
)
@click.option(
    "--base-uri",
    default="",
    help="Base URI prefix for document @id values.",
)
@click.option(
    "--context-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON-LD context file for human-readable property names.",
)
def generate_mapping(
    shacl_path: str,
    output_path: str | None,
    context_url: str,
    base_uri: str,
    context_file: str | None,
) -> None:
    """Generate a mapping YAML template from a SHACL shape.

    Creates a skeleton mapping configuration with all properties from the
    SHACL shape. Fill in the ``source`` fields for your data.

    Examples:

        ceds-jsonld generate-mapping --shacl Person_SHACL.ttl -o person_mapping.yaml

        ceds-jsonld generate-mapping --shacl Person_SHACL.ttl --context-file person_context.json
    """
    import json as json_mod

    import yaml

    from ceds_jsonld.introspector import SHACLIntrospector

    try:
        intro = SHACLIntrospector(shacl_path)
    except ShapeLoadError as exc:
        raise click.ClickException(str(exc)) from exc

    # Load context lookup if provided
    context_lookup: dict[str, str] | None = None
    if context_file is not None:
        try:
            ctx_data = json_mod.loads(Path(context_file).read_text(encoding="utf-8"))
            if isinstance(ctx_data, dict) and "@context" in ctx_data:
                ctx_inner = ctx_data["@context"]
                if isinstance(ctx_inner, dict):
                    context_lookup = ctx_inner
        except Exception as exc:
            raise click.ClickException(f"Failed to parse context file: {exc}") from exc

    template = intro.generate_mapping_template(
        context_url=context_url,
        base_uri=base_uri,
        context_lookup=context_lookup,
    )

    yaml_str = yaml.dump(template, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml_str, encoding="utf-8")
        click.echo(f"Mapping template written to {output_path}")
    else:
        click.echo(yaml_str)


# ---------------------------------------------------------------------------
# list-shapes
# ---------------------------------------------------------------------------


@cli.command("list-shapes")
@click.option(
    "--shapes-dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Additional directory to search for shapes.",
)
def list_shapes(shapes_dir: str | None) -> None:
    """List all available shapes.

    Shows shapes that can be loaded from the built-in ontologies directory
    and any additional directories specified.

    Examples:

        ceds-jsonld list-shapes

        ceds-jsonld list-shapes --shapes-dir ./my-shapes
    """
    registry = ShapeRegistry()
    if shapes_dir is not None:
        registry.add_search_dir(shapes_dir)

    available = registry.list_available()

    if not available:
        click.echo("No shapes found.")
        return

    click.echo(f"Available shapes ({len(available)}):")
    for name in available:
        click.echo(f"  - {name}")


# ---------------------------------------------------------------------------
# benchmark
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "-s",
    "--shape",
    required=True,
    help="Shape name (e.g. 'person').",
)
@click.option(
    "-n",
    "--records",
    type=int,
    default=100_000,
    help="Number of records to benchmark (default: 100,000).",
)
@click.option(
    "--shapes-dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Additional directory to search for shapes.",
)
def benchmark(shape: str, records: int, shapes_dir: str | None) -> None:
    """Run a performance benchmark for a shape.

    Builds N records using sample data repeated, measuring throughput
    for mapping, building, and serialization.

    Examples:

        ceds-jsonld benchmark -s person

        ceds-jsonld benchmark -s person -n 1000000
    """
    from ceds_jsonld.builder import JSONLDBuilder
    from ceds_jsonld.mapping import FieldMapper

    registry, shape_def = _load_registry(shape, shapes_dir=shapes_dir)

    # Load sample data for the shape
    if shape_def.sample_path is None:
        raise click.ClickException(
            f"Shape '{shape}' has no sample data file. Cannot run benchmark without sample data."
        )

    import pandas as pd

    sample_df = pd.read_csv(shape_def.sample_path)
    sample_rows = sample_df.to_dict(orient="records")

    if not sample_rows:
        raise click.ClickException("Sample data file is empty.")

    click.echo(f"Benchmarking shape '{shape}' with {records:,} records...")
    click.echo(f"Sample file: {shape_def.sample_path} ({len(sample_rows)} rows)")
    click.echo()

    mapper = FieldMapper(shape_def.mapping_config)
    builder = JSONLDBuilder(shape_def)

    # Generate rows by cycling through sample data
    rows = [sample_rows[i % len(sample_rows)] for i in range(records)]

    # --- Mapping benchmark ---
    click.echo("Phase 1: Field mapping...")
    t0 = time.perf_counter()
    mapped = [mapper.map(row) for row in rows]
    t_map = time.perf_counter() - t0

    # --- Building benchmark ---
    click.echo("Phase 2: JSON-LD building...")
    t0 = time.perf_counter()
    docs = [builder.build_one(m) for m in mapped]
    t_build = time.perf_counter() - t0

    # --- Serialization benchmark ---
    click.echo("Phase 3: Serialization...")
    t0 = time.perf_counter()
    for doc in docs:
        dumps(doc, pretty=False)
    t_ser = time.perf_counter() - t0

    t_total = t_map + t_build + t_ser

    click.echo()
    click.secho("Results:", bold=True)
    click.echo(f"  Records:        {records:>12,}")
    click.echo(f"  Mapping:        {t_map:>12.3f}s  ({records / t_map:>10,.0f} rec/s)")
    click.echo(f"  Building:       {t_build:>12.3f}s  ({records / t_build:>10,.0f} rec/s)")
    click.echo(f"  Serialization:  {t_ser:>12.3f}s  ({records / t_ser:>10,.0f} rec/s)")
    click.echo("  ────────────────────────────────────────")
    click.echo(f"  Total:          {t_total:>12.3f}s  ({records / t_total:>10,.0f} rec/s)")
    click.echo(f"  Per record:     {t_total / records * 1000:>12.4f} ms")


# ---------------------------------------------------------------------------
# map-wizard command
# ---------------------------------------------------------------------------


@cli.command("map-wizard")
@click.option(
    "-i",
    "--input",
    "input_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to input data file (CSV or Excel).",
)
@click.option("-s", "--shape", default=None, help="Shape name. Auto-detected if omitted.")
@click.option(
    "-o",
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="Output YAML path. Prints to stdout if omitted.",
)
@click.option("--no-llm", is_flag=True, default=False, help="Heuristic-only mode (no LLM).")
@click.option("--threshold", type=float, default=0.4, help="Minimum confidence threshold.")
@click.option(
    "--shapes-dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Additional shapes directory.",
)
def map_wizard(
    input_path: str,
    shape: str | None,
    output_path: str | None,
    no_llm: bool,
    threshold: float,
    shapes_dir: str | None,
) -> None:
    """AI-assisted mapping wizard — auto-map columns to CEDS shapes."""
    from ceds_jsonld.wizard import MappingWizard

    wizard = MappingWizard(
        use_llm=not no_llm,
        heuristic_threshold=threshold,
        shapes_dir=shapes_dir,
    )

    if shape is None:
        click.echo("Detecting best shape...")
        detected = wizard.detect_shape(input_path)
        if not detected:
            click.echo("Error: Could not detect a matching shape.", err=True)
            raise SystemExit(1)
        shape = detected[0][0]
        click.echo(f"Detected shape: {shape} (score: {detected[0][1]:.2f})")

    result = wizard.suggest(input_path, shape=shape)

    if output_path:
        result.save(output_path)
        click.echo(f"Mapping saved to {output_path}")
    else:
        click.echo(result.yaml_text)

    if result.unmapped_columns:
        click.echo(f"\nUnmapped columns: {', '.join(result.unmapped_columns)}", err=True)
    if result.unmapped_properties:
        click.echo(f"Unmapped properties: {', '.join(result.unmapped_properties)}", err=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the ``ceds-jsonld`` console script."""
    cli()


if __name__ == "__main__":
    main()
