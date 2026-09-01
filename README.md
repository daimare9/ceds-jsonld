# ceds-jsonld

[![PyPI version](https://img.shields.io/pypi/v/ceds-jsonld.svg)](https://pypi.org/project/ceds-jsonld/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/daimare9/ceds-jsonld/actions/workflows/ci.yml/badge.svg)](https://github.com/daimare9/ceds-jsonld/actions/workflows/ci.yml)
[![Tests: 1111 passed](https://img.shields.io/badge/tests-1111%20passed-brightgreen.svg)](tests/)
[![Coverage: 88%](https://img.shields.io/badge/coverage-88%25-yellowgreen.svg)]()

**Python library for converting education data into standards-compliant JSON-LD documents backed by the [CEDS ontology](https://ceds.ed.gov/).**

Read data from CSV, Excel, databases, APIs, Google Sheets, SIS platforms, or cloud warehouses. Map it to SHACL-defined shapes like Person, Organization, or K-12 Enrollment. Get back clean JSON-LD that validates against the ontology and is ready for Cosmos DB or any downstream system.

```
CSV / Excel / API / DB / Sheets / SIS / Warehouse
        │
        ▼
  ┌───────────┐     ┌───────────┐     ┌───────────┐
  │  Source    │────▶│  Field    │────▶│  JSON-LD  │────▶  .json / .ndjson / Cosmos DB
  │  Adapter   │     │  Mapper   │     │  Builder  │           │
  └───────────┘     └───────────┘     └───────────┘           ▼
        ▲                 ▲                 ▲           ┌───────────┐
        │                 │                 │           │  Output   │
        └─────── Pipeline orchestrates ─────┘           │  Sink     │
                                                        └───────────┘
                                                          NDJSONSink
                                                          ADLSink
```

---

## Installation

```bash
# Core library (CSV + NDJSON + dict support included)
pip install ceds-jsonld

# With Excel support
pip install ceds-jsonld[excel]

# With REST API support
pip install ceds-jsonld[api]

# With database support (SQL Server, PostgreSQL, SQLite, etc.)
pip install ceds-jsonld[database]

# With fast JSON serialization (recommended for production)
pip install ceds-jsonld[fast]

# With Azure Data Lake Storage output sink
pip install ceds-jsonld[adls]

# Everything for development
pip install ceds-jsonld[dev]

# Or install from source
pip install -e ".[dev]"
```

Requires **Python 3.11+**.

---

## Quick Start

### The simplest path: CSV to JSON-LD in 5 lines

```python
from ceds_jsonld import Pipeline, ShapeRegistry, CSVAdapter

registry = ShapeRegistry()
registry.load_shape("person")

pipeline = Pipeline(source=CSVAdapter("students.csv"), shape="person", registry=registry)
pipeline.to_json("output/students.json")
```

That's it. The library reads your CSV, maps each row to the Person SHACL shape using the declarative YAML config, builds JSON-LD documents, and writes them to a file.

> **Tip:** All adapters (`CSVAdapter`, `ExcelAdapter`, `APIAdapter`, etc.) are importable directly from `ceds_jsonld` — no need to reach into sub-packages.

### What comes out

Each record becomes a self-contained JSON-LD document:

```json
{
    "@context": "https://cepi-dev.state.mi.us/ontology/context-person.json",
    "@type": "Person",
    "@id": "cepi:person/989897099",
    "hasPersonName": {
        "@type": "PersonName",
        "FirstName": "EDITH",
        "MiddleName": "M",
        "LastOrSurname": "ADAMS",
        "GenerationCodeOrSuffix": "III",
        "hasRecordStatus": { ... },
        "hasDataCollection": { ... }
    },
    "hasPersonBirth": {
        "@type": "PersonBirth",
        "Birthdate": { "@type": "xsd:date", "@value": "1965-05-15" },
        ...
    },
    ...
}
```

---

## Core Concepts

### Shapes

A **shape** is a self-contained definition of a data collection type. The Person shape, for example, defines what a Person document looks like — its fields, sub-shapes, data types, and cardinalities. Shapes are defined by:

| File | Purpose |
|------|---------|
| `Person_SHACL.ttl` | SHACL constraints — what properties are required, their types, and allowed values |
| `person_context.json` | JSON-LD context — maps short names to full ontology IRIs |
| `person_mapping.yaml` | Field mapping — how your source columns map to JSON-LD properties |
| `person_sample.csv` | Sample data for testing |

The library ships with six shapes: **Person**, **Organization**, **LEA**, **K-12 School**, **Facility**, and **Post-Secondary Institution**. Additional shapes (Enrollment, Staff, etc.) follow the same pattern.

### The Pipeline

The `Pipeline` is the main entry point for most users. It connects a data source to a shape and handles the full transformation chain:

```python
pipeline = Pipeline(
    source=CSVAdapter("students.csv"),  # Where to read data
    shape="person",                      # Which shape to map to
    registry=registry,                   # Shape definitions
)
```

### Adapters

Adapters are how data gets into the pipeline. Pick the one that matches your data source:

| Adapter | Input | Install |
|---------|-------|---------|
| `CSVAdapter` | `.csv` files | included |
| `ExcelAdapter` | `.xlsx` / `.xls` files | `pip install ceds-jsonld[excel]` |
| `DictAdapter` | Python dicts (for APIs, tests, etc.) | included |
| `NDJSONAdapter` | Newline-delimited JSON files | included |
| `APIAdapter` | REST/HTTP endpoints with pagination | `pip install ceds-jsonld[api]` |
| `DatabaseAdapter` | SQL databases via SQLAlchemy | `pip install ceds-jsonld[database]` |
| `GoogleSheetsAdapter` | Google Sheets spreadsheets | `pip install ceds-jsonld[sheets]` |
| `SnowflakeAdapter` | Snowflake data warehouse | `pip install ceds-jsonld[snowflake]` |
| `BigQueryAdapter` | Google BigQuery tables / queries | `pip install ceds-jsonld[bigquery]` |
| `DatabricksAdapter` | Databricks SQL warehouses | `pip install ceds-jsonld[databricks]` |
| `CanvasAdapter` | Canvas LMS (users, enrollments, etc.) | `pip install ceds-jsonld[canvas]` |
| `OneRosterAdapter` | OneRoster 1.1 SIS (Infinite Campus, ClassLink, etc.) | `pip install ceds-jsonld[oneroster]` |
| `RelationalAdapter` | Star-schema multi-table joins (Parquet, CSV, etc.) | included |
| `powerschool_adapter()` | PowerSchool SIS (factory function) | `pip install ceds-jsonld[api]` |
| `blackbaud_adapter()` | Blackbaud SKY API (factory function) | `pip install ceds-jsonld[api]` |

---

## Usage Examples

### Validation

Validate your data before building, or validate built documents against the SHACL shape:

```python
from ceds_jsonld import Pipeline, ShapeRegistry, CSVAdapter

registry = ShapeRegistry()
registry.load_shape("person")
pipeline = Pipeline(source=CSVAdapter("students.csv"), shape="person", registry=registry)

# Pre-build validation (fast — checks required fields, datatypes, allowed values)
result = pipeline.validate(mode="report")
print(result.summary())  # "100 records checked: 3 errors, 1 warning"

# Full SHACL round-trip validation (thorough — validates against the SHACL shape)
result = pipeline.validate(mode="report", shacl=True)

# Inline validation during streaming — invalid rows are skipped automatically
for doc in pipeline.stream(validate=True):
    send_to_downstream_system(doc)

# Strict mode raises on the first error
try:
    docs = pipeline.build_all(validate=True, validation_mode="strict")
except ValidationError as e:
    print(f"Validation failed: {e}")
```

Three validation modes are available:

| Mode | Behaviour |
|------|-----------|
| `"report"` | Collect all issues, never raise. Invalid rows skipped in `stream()`. |
| `"strict"` | Raise `ValidationError` on the first failure. |
| `"sample"` | Validate a random subset (default 1%) — ideal for large batches. |

### Validation Reports

Export validation results to HTML, JSON, CSV, or Parquet for dashboards, data lakes, or auditing:

```python
from ceds_jsonld import (
    Pipeline, ShapeRegistry, CSVAdapter,
    generate_json_report, generate_csv_report, generate_parquet_report,
)
from pathlib import Path

registry = ShapeRegistry()
registry.load_shape("person")
pipeline = Pipeline(source=CSVAdapter("students.csv"), shape="person", registry=registry)
result = pipeline.validate(mode="report")

# Each result carries run metadata automatically
print(result.run_id)           # UUID for this validation run
print(result.timestamp)        # ISO-8601 UTC timestamp
print(result.shape_name)       # "person"
print(result.library_version)  # "1.2.0"

# Export to JSON (uses orjson when available)
json_str = generate_json_report(result)
Path("report.json").write_text(json_str)

# Export to CSV
csv_str = generate_csv_report(result)
Path("report.csv").write_text(csv_str)

# Export to Parquet (great for data lake ingestion)
generate_parquet_report(result, "report.parquet")

# Work with results as a pandas DataFrame
df = result.to_dataframe()
print(df.columns.tolist())
# ['run_id', 'timestamp', 'shape_name', 'source_name',
#  'record_id', 'property_path', 'severity', 'message', 'expected', 'actual']

# Or as a plain dict (for custom serialization)
data = result.to_dict()
```

### Stream processing (constant memory)

For large datasets, use `stream()` to process one record at a time without loading everything into memory:

```python
for doc in pipeline.stream():
    send_to_downstream_system(doc)
```

### Batch processing

Build all documents at once when the dataset fits in memory:

```python
docs = pipeline.build_all()
print(f"Built {len(docs)} documents")
```

### File output

```python
# JSON array (human-readable)
pipeline.to_json("output/persons.json")

# NDJSON (one document per line — ideal for streaming ingestion)
pipeline.to_ndjson("output/persons.ndjson")
```

### Output sinks (chunked streaming)

For large datasets or Azure Spark notebook workflows, use **output sinks** to stream JSON-LD documents into chunked part files — similar to how Spark writes partitioned output.

```python
from ceds_jsonld import Pipeline, ShapeRegistry, CSVAdapter, NDJSONSink

registry = ShapeRegistry()
registry.load_shape("person")
pipeline = Pipeline(source=CSVAdapter("students.csv"), shape="person", registry=registry)

# Write chunked NDJSON part files to local disk
sink = NDJSONSink(path="output/persons", chunk_size=10_000)
result = pipeline.to_sink(sink)
print(f"Wrote {result.records_out} records in {result.elapsed_seconds:.2f}s")
# output/persons/part-00000.ndjson  (10,000 records)
# output/persons/part-00001.ndjson  (10,000 records)
# output/persons/part-00002.ndjson  (remaining records)
```

#### Write modes (Spark-style)

Sinks accept a `mode` parameter that mirrors Spark's `DataFrameWriter.mode()`:

| Mode | Behaviour |
|------|----------|
| `"error"` (default) | Raise `FileExistsError` if part files already exist |
| `"overwrite"` | Delete existing part files, then write |
| `"append"` | Continue numbering from the highest existing part index + 1 |

```python
from ceds_jsonld import NDJSONSink, WriteMode

# Overwrite previous output
sink = NDJSONSink(path="output/persons", chunk_size=10_000, mode="overwrite")

# Or use the WriteMode enum for type safety
sink = NDJSONSink(path="output/persons", chunk_size=10_000, mode=WriteMode.APPEND)
```

#### Parallel writes

Set `workers` to enable concurrent part-file writing. This is useful for large datasets where I/O is the bottleneck. `orjson` releases the GIL, so threads can serialize and write in parallel:

```python
# Auto-detect core count
sink = NDJSONSink(path="output/persons", chunk_size=10_000, mode="overwrite", workers="auto")

# Or specify explicitly
sink = NDJSONSink(path="output/persons", chunk_size=10_000, workers=4)
```

When `workers=1` (the default), no thread pool is created — zero overhead for single-threaded use.

#### Parallel pipeline processing (multiprocessing)

For large datasets where the CPU-bound map → build → serialize loop is the bottleneck, pass `workers` to `Pipeline.to_sink()` to distribute processing across multiple cores:

```python
from ceds_jsonld import Pipeline, ShapeRegistry, CSVAdapter, NDJSONSink

registry = ShapeRegistry()
registry.load_shape("person")
pipeline = Pipeline(source=CSVAdapter("students.csv"), shape="person", registry=registry)

sink = NDJSONSink(path="output/persons", chunk_size=10_000, mode="overwrite")

# Use 8 worker processes for map → build → serialize → write
result = pipeline.to_sink(sink, workers=8)

# Or auto-detect based on CPU count
result = pipeline.to_sink(sink, workers="auto")
```

Each worker receives a chunk of raw rows, reconstructs the mapper and builder from config, and writes its own part file directly — bypassing Python's GIL entirely. With `workers=1` (default), the existing serial path is used with zero overhead.

> **Note:** Custom transforms (lambdas/closures) cannot be pickled for multiprocessing. If `custom_transforms` is set, `workers` must be `1` or a `PipelineError` is raised.

#### `_SUCCESS` marker

After all part files are written, `close()` writes an empty `_SUCCESS` marker file to the output directory, following the Hadoop/Spark convention for job-complete signaling. In `"overwrite"` mode, any existing `_SUCCESS` file is removed when `open()` is called.

For Azure Data Lake Storage (ADLS Gen2), use `ADLSink` with `fsspec` + `adlfs`:

```python
from ceds_jsonld import ADLSink

sink = ADLSink(
    path="abfss://container@account.dfs.core.windows.net/ceds/persons",
    chunk_size=10_000,
    mode="overwrite",
    workers="auto",
    storage_options={"account_name": "mystorageaccount", "account_key": "..."},
)
result = pipeline.to_sink(sink)
```

Both sinks produce `part-NNNNN.ndjson` files and a `_SUCCESS` marker on completion. The `SinkResult` returned by `close()` (or available on the `PipelineResult`) reports `total_records`, `total_bytes`, and `files_written`.

> **Tip:** Install ADLS support with `pip install ceds-jsonld[adls]`. The `NDJSONSink` requires no extra dependencies.

### Production features

The `Pipeline` returns a `PipelineResult` with detailed metrics, and supports progress tracking and dead-letter queues for failed records:

```python
from ceds_jsonld import Pipeline, ShapeRegistry, CSVAdapter

registry = ShapeRegistry()
registry.load_shape("person")

pipeline = Pipeline(
    source=CSVAdapter("students.csv"),
    shape="person",
    registry=registry,
    progress=True,              # show tqdm progress bar (install ceds-jsonld[observability])
    dead_letter_path="failures.ndjson",  # failed records written here
)

result = pipeline.to_json("output/students.json")
print(f"Wrote {result.records_out} records in {result.elapsed_seconds:.2f}s")
print(f"Throughput: {result.records_per_second:.0f} rec/s")
print(f"Failed: {result.records_failed}")
```

Structured logging with PII masking is built in:

```python
from ceds_jsonld import get_logger

log = get_logger("my_app")
log.info("pipeline.complete", records=1000, ssn="123-45-6789")
# ssn is automatically redacted in log output
```

### Mapping Wizard

Auto-map source CSV/Excel columns to CEDS shape properties using a three-phase matching pipeline:
concept-value matching → heuristic name matching → optional LLM-assisted resolution.

```python
from ceds_jsonld import MappingWizard

wizard = MappingWizard()                        # use_llm=True by default
result = wizard.suggest("students.csv", shape="person")

# Review confidence scores
for col, prop, score, method in result.confidence_report:
    print(f"  {col} → {prop}  ({score:.0%} via {method})")

# Save the generated YAML mapping
result.save("person_mapping.yaml")

# Auto-detect the best shape for a file
scores = wizard.detect_shape("students.csv")
print(scores)  # [("person", 0.85), ("organization", 0.12), ...]

# Preview JSON-LD output before committing to the mapping
docs = wizard.preview("students.csv", result, count=3)
for doc in docs:
    print(doc["@type"])
```

Or from the CLI:

```bash
# Specify shape explicitly
ceds-jsonld map-wizard --input students.csv --shape person --output person_mapping.yaml

# Auto-detect shape (omit --shape)
ceds-jsonld map-wizard --input students.csv --output mapping.yaml

# Heuristic-only mode (no LLM), custom confidence threshold
ceds-jsonld map-wizard --input students.csv --shape person --no-llm --threshold 0.5
```

Pass `--no-llm` to skip the LLM phase entirely (faster, no model download required).

### Reading from Excel

```python
from ceds_jsonld import ExcelAdapter

pipeline = Pipeline(
    source=ExcelAdapter("students.xlsx", sheet_name="Enrollment"),
    shape="person",
    registry=registry,
)
```

### Reading from a database

```python
from ceds_jsonld import DatabaseAdapter

pipeline = Pipeline(
    source=DatabaseAdapter(
        connection_string="mssql+pyodbc://server/db?driver=ODBC+Driver+17+for+SQL+Server",
        query="SELECT * FROM dbo.Students WHERE SchoolYear = 2026",
    ),
    shape="person",
    registry=registry,
)
```

### Reading from a REST API

```python
from ceds_jsonld import APIAdapter

pipeline = Pipeline(
    source=APIAdapter(
        url="https://sis.example.com/api/v2/students",
        headers={"Authorization": "Bearer YOUR_TOKEN"},
        pagination="offset",
        page_size=500,
        results_key="data",
    ),
    shape="person",
    registry=registry,
)
```

### Using in-memory data

```python
from ceds_jsonld import DictAdapter

records = [
    {"FirstName": "Jane", "LastName": "Doe", "Birthdate": "1990-01-15", ...},
    {"FirstName": "John", "LastName": "Smith", "Birthdate": "1985-06-20", ...},
]
pipeline = Pipeline(source=DictAdapter(records), shape="person", registry=registry)
```

### Reading from Google Sheets

```python
from ceds_jsonld import GoogleSheetsAdapter

pipeline = Pipeline(
    source=GoogleSheetsAdapter(
        spreadsheet="Student Roster 2026",
        worksheet="Sheet1",
        service_account_file="credentials.json",
    ),
    shape="person",
    registry=registry,
)
```

### Reading from a cloud data warehouse

```python
from ceds_jsonld import SnowflakeAdapter, BigQueryAdapter, DatabricksAdapter

# Snowflake
pipeline = Pipeline(
    source=SnowflakeAdapter(
        query="SELECT * FROM students WHERE school_year = 2026",
        account="myorg-myaccount",
        user="etl_user",
        private_key_file="rsa_key.p8",
        warehouse="COMPUTE_WH",
        database="EDUCATION",
        schema="PUBLIC",
    ),
    shape="person",
    registry=registry,
)

# BigQuery
pipeline = Pipeline(
    source=BigQueryAdapter(
        query="SELECT * FROM `project.dataset.students` WHERE year = 2026",
        project="my-gcp-project",
    ),
    shape="person",
    registry=registry,
)

# Databricks
pipeline = Pipeline(
    source=DatabricksAdapter(
        query="SELECT * FROM education.students",
        server_hostname="myworkspace.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abc123",
        access_token="dapi...",
    ),
    shape="person",
    registry=registry,
)
```

### Reading from Canvas LMS

```python
from ceds_jsonld import CanvasAdapter

pipeline = Pipeline(
    source=CanvasAdapter(
        base_url="https://myschool.instructure.com",
        api_key="YOUR_CANVAS_TOKEN",
        resource="users",
        account_id="1",
    ),
    shape="person",
    registry=registry,
)
```

### Reading from a OneRoster SIS

```python
from ceds_jsonld import OneRosterAdapter

pipeline = Pipeline(
    source=OneRosterAdapter(
        base_url="https://sis.example.com/ims/oneroster/v1p1",
        resource="students",
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_SECRET",
        token_url="https://sis.example.com/oauth/token",
    ),
    shape="person",
    registry=registry,
)
```

### Reading from star-schema / relational Parquet files

If your data lives in multiple related tables — e.g., a star schema of Parquet files
where students, their identifiers, and their races are in separate files — use
`RelationalAdapter` to join them at the adapter layer without any pre-join ETL:

```python
from ceds_jsonld import RelationalAdapter, ParquetAdapter

pipeline = Pipeline(
    source=RelationalAdapter(
        primary=ParquetAdapter("students.parquet"),
        join_key="student_id",
        satellites={
            "identifications": ParquetAdapter("student_ids.parquet"),
            "races": ParquetAdapter("student_races.parquet"),
        },
    ),
    shape="person",
    registry=registry,
)
```

In your mapping YAML, reference satellite rows with `source_table` instead of `split_on`:

```yaml
properties:
  hasIdentification:
    type: Identification
    cardinality: multiple
    source_table: identifications   # matches the key in satellites={}
    fields:
      IdentifierValue:
        source: id_value
        target: IdentifierValue
      IdentifierType:
        source: id_type
        target: IdentifierType
        optional: true
```

Satellite tables are loaded into memory once at initialization, keyed by the join column.
Each satellite row becomes one instance of the sub-shape in the JSON-LD output. If a
primary entity has no matching satellite rows, the property is omitted — not an error.
The adapter works with any `SourceAdapter` (Parquet, CSV, database, dict, etc.).

---

### IRI reference properties (`sh:nodeKind sh:IRI`)

Some SHACL object properties are plain references to another node — they must
serialize as the node-object form `{"@id": "https://..."}` with **no** `@type`.
Declare such a property with `type: id_ref` (or the alias `iri_ref`) and map the
source column to the `@id` target:

```yaml
properties:
  hasOrganizationRelationshipSubject:
    type: id_ref
    cardinality: single
    fields:
      orgId:
        source: hasOrganizationRelationshipSubject.@id
        target: "@id"
```

For a row containing
`{"hasOrganizationRelationshipSubject.@id": "https://cepi-dev.state.mi.us/organization/03040"}`
this emits:

```json
{
  "hasOrganizationRelationshipSubject": {
    "@id": "https://cepi-dev.state.mi.us/organization/03040"
  }
}
```

Use `cardinality: multiple` (with `split_on`) to emit an array of `{"@id": ...}`
reference nodes. No `@type` key is ever emitted for these properties. The
`id_ref` / `iri_ref` type also works when nested inside another shape's
`properties:` block (e.g. `Organization → hasOrganizationRelationship →
hasOrganizationRelationshipSubject`).

---

### Reading from PowerSchool or Blackbaud

```python
from ceds_jsonld import powerschool_adapter, blackbaud_adapter

# PowerSchool
pipeline = Pipeline(
    source=powerschool_adapter(
        base_url="https://mydistrict.powerschool.com",
        access_token="YOUR_PS_TOKEN",
        resource="students",
    ),
    shape="person",
    registry=registry,
)

# Blackbaud
pipeline = Pipeline(
    source=blackbaud_adapter(
        access_token="YOUR_BB_TOKEN",
        subscription_key="YOUR_SUB_KEY",
        resource="students",
    ),
    shape="person",
    registry=registry,
)
```

---

## Customizing Mappings

The default mapping YAML works out of the box for the standard CSV column names. But your data likely has different column names. There are three ways to handle that:

### Option 1: Override column names at runtime (via Pipeline)

Pass `source_overrides` directly to the Pipeline — no extra setup needed:

```python
pipeline = Pipeline(
    source=CSVAdapter("students.csv"),
    shape="person",
    registry=registry,
    source_overrides={
        "hasPersonName": {
            "FirstName": "FIRST_NM",
            "LastOrSurname": "LAST_NM",
        },
        "hasPersonBirth": {
            "Birthdate": "DOB",
        },
    },
    id_source="STUDENT_ID",
)
pipeline.to_json("output/students.json")
```

Or use the lower-level `FieldMapper` directly:

```python
from ceds_jsonld import FieldMapper

person_shape = registry.get_shape("person")
mapper = FieldMapper(person_shape.mapping_config)

# Override specific column names for your source
my_mapper = mapper.with_overrides(
    id_source="STUDENT_ID",
    source_overrides={
        "hasPersonName": {
            "FirstName": "FIRST_NM",
            "LastOrSurname": "LAST_NM",
        },
        "hasPersonBirth": {
            "Birthdate": "DOB",
        },
    },
)
```

### Option 2: Compose a base mapping with per-source overrides

```python
import yaml
from ceds_jsonld import FieldMapper

person_shape = registry.get_shape("person")

# Load your district-specific overlay
with open("district_47_overlay.yaml") as f:
    overlay = yaml.safe_load(f)

# Merge it on top of the base Person mapping
mapper = FieldMapper.compose(
    base_config=person_shape.mapping_config,
    overlay_config=overlay,
)
```

### Option 3: Write your own mapping YAML

Copy the default `person_mapping.yaml` and modify it to match your source columns. Then load it with a custom shape directory:

```python
registry = ShapeRegistry()
registry.load_shape("person", path="my_shapes/person")
```

### URI-based identifiers (`id_is_uri`)

If your source data already contains fully qualified URIs for record identifiers (e.g., from a linked-data system), set `id_is_uri: true` in the mapping YAML. The builder will use the value verbatim as `@id` instead of prefixing it with `base_uri`:

```yaml
# person_mapping.yaml
shape: PersonShape
id_source: PersonURI
id_is_uri: true        # use the source value as-is for @id
base_uri: ""           # ignored when id_is_uri is true
```

```python
from ceds_jsonld import DictAdapter

records = [{"PersonURI": "https://example.org/person/12345", "FirstName": "Jane", ...}]
pipeline = Pipeline(source=DictAdapter(records), shape="person", registry=registry)
doc = list(pipeline.stream())[0]
print(doc["@id"])  # "https://example.org/person/12345"
```

A warning is logged if the value doesn't look like a URI (no `://` or `:` prefix).

### Custom transforms

If your data needs custom transformations beyond the built-in ones, pass them to the pipeline:

```python
def clean_ssn(value: str) -> str:
    """Strip dashes from SSN."""
    return value.replace("-", "")

pipeline = Pipeline(
    source=CSVAdapter("students.csv"),
    shape="person",
    registry=registry,
    custom_transforms={"clean_ssn": clean_ssn},
)
```

Then reference `clean_ssn` by name in your mapping YAML.

---

## Loading to Azure Cosmos DB

The library includes an async bulk loader for Azure Cosmos DB NoSQL. Documents are automatically prepared (Cosmos-required `id` and `partitionKey` fields are injected).

### Via Pipeline (simplest)

```python
from azure.identity import DefaultAzureCredential

pipeline = Pipeline(
    source=CSVAdapter("students.csv"),
    shape="person",
    registry=registry,
)
result = pipeline.to_cosmos(
    endpoint="https://myaccount.documents.azure.com:443/",
    credential=DefaultAzureCredential(),
    database="ceds",
)
print(f"Loaded {result.succeeded}/{result.total} docs ({result.total_ru:.0f} RU)")
```

The container defaults to the shape name (`"person"`). You can override it:

```python
result = pipeline.to_cosmos(
    endpoint="https://myaccount.documents.azure.com:443/",
    credential="your-master-key",  # string key works for local emulator
    database="ceds",
    container="my_custom_container",
    partition_value="collection_2026",  # explicit partition key
    concurrency=50,                     # parallel upserts (default 25)
)
```

### Via CosmosLoader (advanced)

```python
from ceds_jsonld import CosmosLoader
from azure.identity.aio import DefaultAzureCredential

async with CosmosLoader(
    endpoint="https://myaccount.documents.azure.com:443/",
    credential=DefaultAzureCredential(),
    database="ceds",
    container="person",
) as loader:
    result = await loader.upsert_many(docs)
    # or one at a time:
    single = await loader.upsert_one(doc)
```

### Document preparation

If you need to prepare documents manually (e.g., for a different data store):

```python
from ceds_jsonld import prepare_for_cosmos

cosmos_doc = prepare_for_cosmos(jsonld_doc)
# cosmos_doc now has "id" (from @id) and "partitionKey" (from @type)
```

---

## Command-Line Interface

The library includes a full CLI for common workflows. Install with `pip install ceds-jsonld[cli]`.

### Convert data to JSON-LD

```bash
# CSV to JSON file
ceds-jsonld convert -s person -i students.csv -o students.json

# CSV to NDJSON (one document per line, ideal for streaming)
ceds-jsonld convert -s person -i students.csv -o students.ndjson

# Excel with sheet selection
ceds-jsonld convert -s person -i data.xlsx --sheet Enrollment -o out.json

# Compact output (no indentation)
ceds-jsonld convert -s person -i students.csv -o students.json --compact
```

### Validate data

```bash
# Pre-build validation (fast — checks types, required fields, allowed values)
ceds-jsonld validate -s person -i students.csv

# Full SHACL round-trip validation
ceds-jsonld validate -s person -i students.csv --shacl

# Sample-based validation for large files
ceds-jsonld validate -s person -i students.csv --shacl --mode sample --sample-rate 0.05

# Generate a validation report (html, json, csv, or parquet)
ceds-jsonld validate -s person -i students.csv --report-format html
ceds-jsonld validate -s person -i students.csv --report-format json --report-path results.json
ceds-jsonld validate -s person -i students.csv --report-format csv
ceds-jsonld validate -s person -i students.csv --report-format parquet --report-path validation.parquet
```

When `--report-path` is omitted, the report is written to `validation_report.{format}` in the current directory.

### AI-assisted mapping

```bash
# Auto-map columns to a CEDS shape
ceds-jsonld map-wizard --input students.csv --shape person --output person_mapping.yaml

# Auto-detect the best shape (omit --shape)
ceds-jsonld map-wizard --input students.csv --output mapping.yaml

# Heuristic-only (no LLM download required)
ceds-jsonld map-wizard --input students.csv --shape person --no-llm
```

### Inspect SHACL shapes

```bash
# Human-readable shape tree
ceds-jsonld introspect --shacl ontologies/person/Person_SHACL.ttl

# JSON output
ceds-jsonld introspect --shacl Person_SHACL.ttl --json

# Markdown table (great for docs and READMEs)
ceds-jsonld introspect --shacl Person_SHACL.ttl --format markdown
```

### Generate mapping templates

```bash
# Generate a starter mapping YAML from a SHACL shape
ceds-jsonld generate-mapping --shacl Person_SHACL.ttl -o person_mapping.yaml

# With context file for human-readable property names
ceds-jsonld generate-mapping --shacl Person_SHACL.ttl --context-file person_context.json
```

### Other commands

```bash
# List available shapes
ceds-jsonld list-shapes

# Benchmark a shape (default: 100K records)
ceds-jsonld benchmark -s person
ceds-jsonld benchmark -s person -n 1000000
```

---

## SHACL Introspection

The `SHACLIntrospector` lets you examine SHACL shapes programmatically — useful for generating mapping templates, validating mappings, or building tooling:

```python
from ceds_jsonld import SHACLIntrospector

introspector = SHACLIntrospector("ontologies/person/Person_SHACL.ttl")

# See the full shape tree
for shape in introspector.shapes.values():
    print(f"{shape.name}: {len(shape.properties)} properties")

# Generate a starter mapping YAML from a SHACL shape
template = introspector.generate_mapping_template("PersonShape")

# Validate an existing mapping against the SHACL constraints
errors, warnings = introspector.validate_mapping(
    mapping_config=person_shape.mapping_config,
    shape_name="PersonShape",
)
```

---

## Lower-Level API

For advanced use cases, you can use the components individually instead of the Pipeline:

```python
from ceds_jsonld import ShapeRegistry, FieldMapper, JSONLDBuilder
from ceds_jsonld.serializer import write_json

# 1. Load shape
registry = ShapeRegistry()
person = registry.load_shape("person")

# 2. Create mapper and builder
mapper = FieldMapper(person.mapping_config)
builder = JSONLDBuilder(person)

# 3. Transform a row
raw_row = {"FirstName": "Jane", "LastName": "Doe", ...}
mapped = mapper.map(raw_row)
doc = builder.build_one(mapped)

# 4. Serialize
write_json(doc, "output/jane.json")
```

---

## Performance

The library is designed for high throughput. JSON-LD documents are built as plain Python dicts — no RDF graph construction, no JSON-LD compaction algorithms. This approach is **161x faster** than the rdflib + PyLD alternative (proven in our benchmarks).

| Operation | Time |
|-----------|------|
| Single record (map + build) | ~0.1 ms |
| 10,000 records | < 2 seconds |
| 100,000 records → NDJSON file | < 10 seconds |

JSON serialization uses [orjson](https://github.com/ijl/orjson) (Rust-backed, ~10x faster than stdlib `json`) when installed, with automatic fallback to stdlib.

---

## Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| 0 — Research | ✅ Complete | Performance benchmarks, architecture decisions |
| 1 — Core Foundation | ✅ Complete | Registry, mapper, builder, serializer. 89 tests. |
| 2 — SHACL Engine | ✅ Complete | Introspector, mapping templates, validation, overrides. 142 tests. |
| 3 — Data Ingestion | ✅ Complete | 6 source adapters, Pipeline class. 213 tests, 87% coverage. |
| 4 — Cosmos DB | ✅ Complete | CosmosLoader, Pipeline.to_cosmos(), document prep. 241 tests. |
| 5 — Validation | ✅ Complete | PreBuildValidator, SHACLValidator, 3 modes, Pipeline.validate(). 331 tests, 88% coverage. |
| 6 — CLI & Docs | ✅ Complete | Full CLI (6 commands), Sphinx API docs, user guides. 356 tests. |
| 7 — Production | ✅ Complete | Structured logging, PipelineResult metrics, dead-letter queue, progress tracking, PII masking, IRI sanitization. 398 tests. |
| 8 — Publishing | ✅ Complete | Open source on PyPI, GitHub Actions CI/CD, monthly releases. |
| Pre-1.0 Stabilization | ✅ Complete | Bug fixes (#2–#30), transform hardening, validation improvements. **557 tests**. |
| 0.10.0 — Native Adapters | ✅ Complete | 6 new adapters (Sheets, Snowflake, BigQuery, Databricks, Canvas, OneRoster) + 2 SIS factory functions. **680 tests**. |
| 0.10.1–0.10.2 — Patch Fixes | ✅ Complete | Adapter bug fixes, IRI sanitization, transform hardening. **727 tests**. |
| 0.11.0 — Organization Shapes | ✅ Complete | 5 new shapes: Organization, LEA, K-12 School, Facility, Post-Secondary Institution. |
| 2.0 — Mapping Wizard | ✅ Complete | AI-assisted `MappingWizard`, three-phase matching, HTML validation reports, introspect markdown, benchmark CLI. **875 tests**. |
| 2.0 — Synthetic Data Generator | ✅ Core Complete | `SyntheticDataGenerator`, concept scheme resolution, LLM + Ollama + deterministic fallback, caching, model comparison benchmarks. **81 SDG tests**. |
| 1.0.0 | ✅ Released | First major release. All core features production-ready. **886 tests**. |
| 1.0.1 | ✅ Released | Patch: DEL/C1 sanitization (#50), serializer double-wrap (#51), wizard NaN (#47). **952 tests**. |
| 1.1.0 | ✅ Released | `ParquetAdapter` for reading Parquet files. **976 tests**. |
| 1.1.1 | ✅ Released | mypy CI fix for pyarrow imports. |
| 1.2.0 | ✅ Released | Structured validation reports (JSON, CSV, Parquet). Run metadata on `ValidationResult`. CLI `--report-format`. **993 tests**. |
| 1.2.2 | ✅ Released | Report bug fixes: shape_name precedence, CSV formula injection whitespace bypass. |
| 1.3.0 | ✅ Released | `id_is_uri` mapping flag, output sinks (`NDJSONSink`, `ADLSink`), `Pipeline.to_sink()`, chunked NDJSON streaming, ADLS Gen2 support. **1032 tests**. |
| 1.3.1 | ✅ Released | Spark-style write modes (`error`/`overwrite`/`append`), parallel part-file writes (`workers`), `_SUCCESS` marker, `WriteMode` enum. **1055 tests**. |
| 1.4.0 | ✅ Released | Multiprocessing parallel pipeline (`workers` param on `to_sink()`), `ProcessPoolExecutor`-based map→build→serialize, custom-transforms guard. **1062 tests**. |
| 1.5.0 | ✅ Released | `RelationalAdapter` for star-schema multi-table joins; `source_table` YAML key for satellite table mapping; graceful degradation for flat adapters. **1081 tests**. |
| 1.6.0 | ✅ Released | `sanitize_cosmos_id()` utility; `inject_cosmos_id` Pipeline parameter; full-URI Cosmos ID sanitization (breaking: `id` now preserves full URI with `/`→`\|`). **1091 tests**. |
| 1.7.0 | ✅ Released | `wrapper_field` / `inner_type` YAML mapping keys for intermediate container nodes in property graphs. **1103 tests**. |
| 1.8.0 | ✅ Released | `id_ref` / `iri_ref` property type for `sh:nodeKind sh:IRI` references — emits `{"@id": ...}` with no `@type` (single & multiple cardinality). **1108 tests**. |
| 1.9.0 | ✅ Released | Nested `id_ref` / `iri_ref` support — reference type honoured inside sub-node `properties:` blocks at any depth. **1111 tests**. |

See [ROADMAP.md](ROADMAP.md) for the full plan.

---

## Optional Dependencies

| Extra | Packages | Purpose |
|-------|----------|---------|
| `fast` | orjson | 10x faster JSON serialization |
| `excel` | openpyxl | Excel file reading |
| `api` | httpx | REST API adapter |
| `database` | sqlalchemy | Database adapter |
| `sheets` | gspread, google-auth | Google Sheets adapter |
| `snowflake` | snowflake-connector-python | Snowflake data warehouse adapter |
| `bigquery` | google-cloud-bigquery | Google BigQuery adapter |
| `databricks` | databricks-sql-connector | Databricks SQL adapter |
| `canvas` | canvasapi | Canvas LMS adapter |
| `oneroster` | httpx | OneRoster 1.1 SIS adapter |
| `adls` | fsspec, adlfs | Azure Data Lake Storage output sink |
| `sis` | canvasapi, httpx | All SIS adapters (Canvas + OneRoster) |
| `warehouse` | snowflake + bigquery + databricks | All cloud warehouse adapters |
| `all-adapters` | all adapter deps | Every adapter extra combined |
| `cosmos` | azure-cosmos, azure-identity | Cosmos DB loading |
| `observability` | structlog, tqdm | Structured logging & progress bars |
| `validation` | pyshacl | SHACL validation |
| `cli` | click | Command-line interface |
| `sdg` | torch, transformers, huggingface-hub | Synthetic data generation (local LLM) |
| `sdg-ollama` | ollama | Synthetic data generation via Ollama |
| `all` | all of the above | Everything for production |
| `dev` | pytest, ruff, mypy, etc. | Development and testing |

---

## Development

```bash
# Clone and install
git clone https://github.com/daimare9/ceds-jsonld.git
cd ceds-jsonld
pip install -e ".[dev,cli]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=src/ceds_jsonld --cov-report=term-missing

# Lint
ruff check src/ tests/

# Type check
mypy src/

# Build documentation
cd docs
make html   # or on Windows: .\make.bat html
```

---

## License

MIT
