# Changelog

All notable changes to this project will be documented in this file.

This project follows [Semantic Versioning](https://semver.org/):
- **MAJOR** — incompatible API changes
- **MINOR** — new features, backward-compatible
- **PATCH** — bug fixes, backward-compatible

Release cadence: **monthly** (first week of each month), with ad-hoc patch releases for critical fixes.

---

## [Unreleased]

*Nothing yet.*

---

## [1.1.0] — 2026-04-08

### Added

- **ParquetAdapter** — New source adapter for reading Apache Parquet files.
  Supports column selection, row-group-aware batching via `read_batch()`, and
  metadata-only row counting via `count()`. `pyarrow` is now a core dependency.
  Importable from `ceds_jsonld` directly.

### Tests

- 976 tests passing (up from 967 at v1.0.3)

---

## [1.0.4] — 2026-04-08

### Changed

- **Compatibility** — Lowered minimum Python version from 3.12 to 3.11. No code
  changes required — the codebase uses only `X | Y` union syntax (3.10+) and
  lowercase generics (3.9+). CI matrix now tests 3.11, 3.12, and 3.13.

---

## [1.0.3] — 2026-04-06

### Fixed

- **CI** — Suppressed `transformers` type-stub `[misc]` error in mypy for
  `model.generate()` call in `wizard/llm_matcher.py`; added `torch` and
  `transformers` to mypy `ignore_missing_imports` overrides so CI and local
  dev environments both pass without the optional SDG dependencies installed

---

## [1.0.2] — 2026-04-06

### Added

- **Builder** — Concept scheme / `named_individual` properties now emit plain string values
  in JSON-LD output instead of verbose typed sub-node objects. Properties with
  `type: named_individual` in mapping YAML produce `"hasLocale": "Locale_CityMidsize"`
  instead of `{"@type": "Locale", "Locale": "Locale_CityMidsize"}`. Fields with
  `datatype: named_individual` inside object properties are also flattened (#52)

### Tests

- 967 tests passing (up from 952 at v1.0.1)

---

## [1.0.1] — 2026-03-24

### Fixed

- **Sanitization** — `sanitize_string_value` now strips DEL (U+007F) and C1 control characters
  (U+0080–U+009F) in addition to C0 characters. Legacy copy-paste artifacts from student records
  no longer corrupt downstream XML/RDF serialization (#50)
- **Serializer** — `write_json` no longer double-wraps `SerializationError`, producing clear
  single-prefix error messages instead of confusing nested "Failed to … Failed to …" output (#51)
- **Wizard** — `_infer_type` in profiler now classifies all-NaN/Infinity columns as `'string'`
  instead of `'float'`, preventing downstream validation errors (#47)

### Tests

- 952 tests passing (up from 886 at v1.0.0)

---

## [1.0.0] — 2026-03-24

### Summary

**First major release.** Promotes the library to v1.0.0 after 9 development phases. All core
features — Shape Registry, 6 source adapters, YAML-driven field mapping, high-performance
JSON-LD builder, SHACL validation, Cosmos DB loader, CLI, AI-assisted Mapping Wizard,
Synthetic Data Generator, HTML reports, structured logging, and dead-letter queue — are
production-ready. 886 tests passing.

### Added

- **Nested sub-properties** — YAML mapping configs now support recursive `properties` blocks,
  enabling shapes like Organization → Location → LocationAddress at any nesting depth (#41)
- **Array root `@type`** — Builder `root_types` parameter accepts a list, emitting `"@type": ["Person", "Student"]` (#42)
- **Simplified `xsd:string`** — Typed literals with `xsd:string` datatype now emit plain string
  values instead of `{"@value": "...", "@type": "xsd:string"}` (#43)

### Fixed

- **Wizard** — `printf`-style logging calls replaced with keyword-arg style to prevent crashes (#44)
- **Wizard** — LLM confidence scores clamped to `[0, 1]`; columns with all `NaN`/`Infinity` values
  now classified as `string` instead of `float` (#45, #47)
- **Mypy** — 9 strict type errors fixed across wizard modules (#46)

### Changed

- Testing instructions updated with terminal output hazard rules to prevent stale-buffer misreads

### Tests

- 886 tests passing (up from 841 at v0.12.1)

### Fixed

- Fix 9 mypy strict type errors that broke CI quality gate (concept_resolver, generator, fallback_generators, llm_generator, llm_matcher, collector).

---

## [0.12.0] — 2026-03-24

### Summary

Minor release adding the AI-assisted Mapping Wizard, HTML validation reports, Markdown introspection output, and `map-wizard` CLI command. Three-phase matching pipeline (concept-value → heuristic → LLM) auto-maps CSV/Excel columns to CEDS shape properties with confidence scoring. 875 tests passing.

### Added

- **Mapping Wizard** — `MappingWizard` class with `suggest()`, `detect_shape()`, and `preview()` methods for AI-assisted column-to-property mapping
- **ColumnProfiler** — column analysis with type inference, null rates, unique counts, and delimiter detection
- **ShapeMetadataCollector** — aggregates target property metadata from SHACL introspector
- **ConceptValueMatcher** — resolves columns by matching distinct values against CEDS concept scheme enums (zero LLM cost)
- **HeuristicMatcher** — scoring engine with exact/fuzzy name matching, datatype compatibility, and concept overlap
- **MatchingEngine** — three-phase orchestrator: concept-value → heuristic → LLM
- **MappingAssembler** + **WizardResult** — builds complete YAML config with confidence annotations, `save()`, and `yaml_text`
- **LLMMatcher** — optional LLM-assisted resolution for unresolved columns (local transformers or Ollama)
- **HTML validation reports** — `--report` flag on `validate` CLI command generates self-contained HTML reports
- **Markdown introspection** — `--format markdown` on `introspect` CLI command outputs property tables
- **`map-wizard` CLI command** — auto-map columns with `--no-llm`, `--threshold`, and shape auto-detection

### Changed

- README expanded with full Mapping Wizard documentation, CLI examples, and updated badge (875 tests)
- Optional Dependencies table now includes `[sdg]` and `[sdg-ollama]` extras

### Tests

- 148 new tests covering all wizard modules, CLI integration, HTML reports, and markdown output
- Total test count: **875 passed** (up from 727)

---

## [0.11.0] — 2026-03-20

### Summary

Minor release adding five new organization shapes: Organization (base), LEA, K-12 School, Facility, and Post-Secondary Institution. Each shape includes SHACL constraints, JSON-LD context, mapping YAML, example output, and sample CSV data.

### Added

- **Organization** shape — base organization with identifiers, addresses, contact info, and CEPI extensions
- **LEA** shape — Local Education Agency with NCES/state identifiers, operational status, and charter authorization
- **K-12 School** shape — K-12 school with grade levels, Title I status, magnet/charter indicators, and accreditation
- **Facility** shape — facility/building with capacity, condition, ownership, and geographic coordinates
- **Post-Secondary Institution** shape — post-secondary institution with Carnegie classification, accreditation, and enrollment metrics

---

## [0.10.2] — 2026-02-12

### Summary

Patch release re-fixing two re-opened bugs: custom transforms returning `None` on required fields now raise instead of silently dropping the field (#30), and `base_uri` is now validated by Pipeline, FieldMapper, and Builder for full defense-in-depth (#34). 727 tests passing.

### Fixed

- **Mapping** — `_map_single` and `_map_multiple` now raise `MappingError` when a custom transform returns `None` on a required field (one without `optional: true`). Previously, `None` results silently dropped the field from output. Optional fields continue to skip silently as before. (#30)
- **Mapping** — `FieldMapper.__init__()` now calls `validate_base_uri()` on the mapping config's `base_uri`, raising `MappingError` for invalid URIs (missing trailing `/` or `#`, whitespace, dangerous schemes). Catches bad URIs even when FieldMapper is used standalone via `compose()`. (#34)
- **Pipeline** — `Pipeline.__init__()` now calls `validate_base_uri()` before constructing FieldMapper or Builder, giving an early `PipelineError` with an actionable message. Together with FieldMapper and Builder validation, `base_uri` is now validated at three levels. (#34)

### Tests

- Updated `test_transform_returning_none_skips_field` → `test_transform_returning_none_on_required_field_raises` (expected behaviour changed)
- Added `test_transform_returning_none_on_optional_field_skips`
- Added 8 new tests across `TestFieldMapperValidatesBaseUri` and `TestPipelineValidatesBaseUri`
- Total test count: **727 passed** (up from 719)

---

## [0.10.1] — 2026-02-11

### Summary

Patch release fixing 10 bugs across adapter subsystem — OneRoster data loss, missing standard endpoints, and PowerSchool dot-path extraction. 719 tests passing.

### Fixed

- **OneRoster** — `_flatten_record` now uses indexed keys (`org_0_sourcedId`, `org_1_sourcedId`, …) to preserve **all** list elements instead of silently dropping elements beyond the first (#37)
- **OneRoster** — `_flatten_record` raises `AdapterError` on key collisions instead of silently overwriting existing keys (#37)
- **OneRoster** — Added `students`, `teachers`, `terms`, `categories` to `_ONEROSTER_RESOURCES` — these are standard OneRoster 1.1 endpoints (#38)
- **APIAdapter** — `_extract_records` now supports dot-notation path traversal (e.g. `"students.student"` → `data["students"]["student"]`), fixing all 7 PowerSchool resource types (#39)
- **BigQuery** — `BigQueryAdapter.__init__` now rejects whitespace-only queries, consistent with Snowflake/Databricks/Database adapters (#40)
- **OneRoster** — `_fetch_page` now uses `_import_httpx()` instead of bare `import httpx`, preserving the friendly `AdapterError` when httpx is not installed (#40)
- **BigQuery** — `_build_job_config` checks `isinstance(value, bool)` before `isinstance(value, int)` to correctly type boolean parameters as `BOOL` instead of `INT64` (#36)
- **Pipeline** — `Pipeline.run()` now wraps mapping/build failures in `PipelineError` with `__cause__` chain, matching `stream()` behaviour (#35)
- **Builder** — IRI components properly sanitised to prevent injection (#31–34)
- **Serializer** — `NaN`/`Inf` values handled correctly in JSON output (#25)

### Tests

- 39 new tests across 4 test files covering all fixed issues
- Total test count: **719 passed** (up from 680)

---

## [0.10.0] — 2026-02-11

### Added — Native Adapters

Six new source adapters for education-sector data sources:

- **`GoogleSheetsAdapter`** — Read from Google Sheets via `gspread` v6+. Supports
  credentials, service account file, or API key authentication. Open by title, key,
  or URL; select worksheet by name or index. (`pip install ceds-jsonld[sheets]`)
- **`SnowflakeAdapter`** — Query Snowflake data warehouses via native connector with
  DictCursor. Supports password, key-pair, and OAuth authentication. Batch streaming
  via `fetchmany()`. (`pip install ceds-jsonld[snowflake]`)
- **`BigQueryAdapter`** — Query Google BigQuery or read tables directly. Supports
  parameterised queries with typed `ScalarQueryParameter`. (`pip install ceds-jsonld[bigquery]`)
- **`DatabricksAdapter`** — Query Databricks SQL warehouses via `databricks-sql-connector`.
  Context-manager-based connection management with batch `fetchmany()`.
  (`pip install ceds-jsonld[databricks]`)
- **`CanvasAdapter`** — Read from Canvas LMS via `canvasapi`. Supports account-level
  (users, courses, SIS imports) and course-level (enrollments, students, assignments,
  sections) resources. (`pip install ceds-jsonld[canvas]`)
- **`OneRosterAdapter`** — Read from any OneRoster 1.1–compliant SIS (Infinite Campus,
  ClassLink, Clever, Aeries). OAuth client-credentials flow, offset pagination, nested
  JSON flattening. (`pip install ceds-jsonld[oneroster]`)

Two factory functions for vendor-specific SIS platforms:

- **`powerschool_adapter()`** — Pre-configured `APIAdapter` for PowerSchool REST API
  with 5 standard resources and offset pagination.
- **`blackbaud_adapter()`** — Pre-configured `APIAdapter` for Blackbaud SKY API with
  6 standard resources and subscription key header.

New extras groups in `pyproject.toml`:

- `[sheets]`, `[canvas]`, `[oneroster]`, `[snowflake]`, `[bigquery]`, `[databricks]`,
  `[sis]` (canvas + oneroster), `[warehouse]` (snowflake + bigquery + databricks),
  `[all-adapters]` (all adapter extras combined)

All new adapters are importable from the top-level `ceds_jsonld` package.

### Tests

- 76 new tests across 8 test classes covering all new adapters and factory functions
- Total test count: **680 passed** (up from 557)

---

## [0.9.6] — 2026-02-08

### Summary

Patch release with 5 bug fixes hardening pipe-delimited field handling, transform validation, and date format enforcement. 557 tests passing.

### Fixed

- **Transforms** — `first_pipe_split` returns `None` for empty/whitespace input instead of empty string (#26)
- **Transforms** — `date_format` rewritten with full ISO 8601 validation: zero-pads unpadded dates, strips time components, rejects invalid dates (#27)
- **Transforms** — `race_prefix`/`sex_prefix` return `None` for empty/whitespace input instead of bare trailing underscore (#28)
- **Mapping** — Mismatched pipe counts use empty string + warning instead of silently forward-filling last value (#29)
- **Mapping** — New `_validate_transform_result()` post-transform validation rejects dict/list/bool, coerces int/float to str, skips on None (#30)
- **Mapping** — Transform exceptions wrapped in `MappingError` with actionable messages
- **Mapping** — Empty pipe segments skipped entirely in multi-cardinality fields (#26)
- **Validator** — `PreBuildValidator` warns on empty pipe segments with position list (#26)
- **Data** — Person mapping YAML: added `transform: date_format` to Birthdate field (#27)

---

## [0.9.5] — 2026-02-08

### Summary

Patch release fixing a flaky CI benchmark that caused the v0.9.4 main workflow to fail on Windows runners. No functional code changes. 526 tests passing.

### Fixed

- **Benchmarks** — Increased 100K pipeline performance test limits (15s base, 8× CI multiplier) to eliminate false failures on shared Windows CI runners

---

## [0.9.4] — 2026-02-08

### Summary

Patch release with 5 bug fixes hardening the pipeline against non-finite floats, booleans, None values, and empty lists across the mapper, builder, and serializer. 526 tests passing.

### Fixed

- **Pipeline** — `validate()` no longer double-counts errors and warnings; `add_issue()` already increments counters internally (#21)
- **Mapping** — `_ensure_scalar()` now rejects `bool` values and non-finite floats (`inf`, `-inf`, `nan`) with actionable error messages instead of silently coercing them to strings (#22)
- **Builder** — `_typed_literal()` returns `None` for `None`, `NaN`, and `Infinity` inputs instead of producing `@value: "None"` string literals; lists are filtered to remove non-finite entries (#23)
- **Builder** — `_build_sub_nodes()` guards against empty list values that previously caused `IndexError` on the single-element unwrap logic (#24)
- **Serializer** — `dumps()` now rejects `NaN`/`Infinity`/`-Infinity` floats with a `SerializationError` for both orjson and stdlib backends, preventing invalid JSON output (#25)

---

## [0.9.3] — 2026-02-08

### Summary

Patch release with 5 bug fixes for transform precision, adapter edge cases, and Pipeline DLQ reliability. 493 tests passing.

### Fixed

- **Transforms** — `first_pipe_split` avoids `float()` for pure-digit strings, preventing IEEE 754 precision loss on 16+ digit numeric IDs (#16)
- **Adapters** — `CSVAdapter.count()` skips blank lines and handles empty files (returns 0 instead of -1), matching `read()` behavior (#17)
- **Adapters** — `NDJSONAdapter` defaults to `utf-8-sig` encoding, transparently stripping UTF-8 BOM from Windows-exported files (#18)
- **Pipeline** — `to_json()` and `to_ndjson()` now properly track `records_failed` and `dead_letter_path` in `PipelineResult` (#19)
- **Pipeline** — Dead-letter writer uses fallback serialization (`repr()`/`default=str`) for non-JSON-serializable `raw_row` values like sets and datetimes (#20)

---

## [0.9.2] — 2026-02-08

### Summary

Patch release with 5 bug fixes covering validation counting, Cosmos DB preparation, serialization error handling, and PII masking. 471 tests passing.

### Fixed

- **Validator** — `PreBuildValidator.validate_batch()` and `SHACLValidator.validate_batch()` no longer double-count errors and warnings (#11)
- **Cosmos** — `prepare_for_cosmos()` uses `copy.deepcopy()` so nested objects are not shared between original and result (#12)
- **Cosmos** — `prepare_for_cosmos()` raises `CosmosError` for empty or slash-only `@id` values instead of silently producing an empty `id` (#13)
- **Serializer** — `dumps()` and `loads()` now wrap backend errors in `SerializationError`, matching `write_json()`/`read_json()` behaviour (#14)
- **Logging** — `_mask_pii()` recursively walks nested dicts/lists and detects SSN and email patterns in string values (#15)

---

## [0.9.1] — 2026-02-08

### Summary

Patch release with 8 bug fixes resolved from issue tracker. 456 tests passing.

### Fixed

- **Transforms** — `int_clean` no longer loses precision on large integers (>15 digits); uses `Decimal` path instead of `float()` (#5)
- **Transforms** — `int_clean` and `first_pipe_split` handle `Infinity`/`-Infinity`/`NaN` gracefully instead of crashing (#4)
- **Validator** — `PreBuildValidator` rejects impossible dates (`2026-02-30`), American format (`MM-DD-YYYY`), and non–zero-padded dates (#2, #3)
- **Mapping** — `FieldMapper` rejects falsy values (`0`, `False`, `None`, empty string) as document IDs with actionable error messages (#1)
- **Mapping** — `FieldMapper` rejects nested `dict`/`list` values in scalar fields instead of silently corrupting output (#6)
- **Sanitize** — `validate_base_uri()` enforces trailing `/` or `#` separator as its docstring claimed (#7)
- **Sanitize** — `sanitize_iri_component()` encodes path-traversal sequences (`../`, `..\`) and strips null bytes / control chars (#9, #10)
- **Data** — Bundled `person_sample.csv` regenerated with 90 unique `PersonIdentifiers` (was 20 unique across 90 rows) (#8)

### Added

- `Pipeline.build_all()` now logs a warning when duplicate `@id` values are detected in output
- Null-byte and control-character stripping in all string field values via `sanitize_string_value()`
- `sanitize_iri_component()` and `validate_base_uri()` hardened with path-traversal and injection protection

---

## [0.9.0] — 2026-02-07

### Summary

First public release. All core functionality complete across 7 development phases.
398 tests passing, 88% coverage.

### Added

- **Shape Registry** — Load and manage SHACL shape definitions with `ShapeRegistry.load_shape()`
- **Field Mapper** — Declarative YAML-driven column mapping with type coercion, transforms, and multi-value splitting
- **JSON-LD Builder** — High-performance direct-dict construction (161x faster than rdflib+PyLD)
- **SHACL Introspector** — Parse SHACL shapes into structured Python representations; generate mapping templates; validate mappings against SHACL constraints
- **Source Adapters** — 6 pluggable data sources:
  - `CSVAdapter` — CSV files (included)
  - `ExcelAdapter` — Excel .xlsx/.xls files (`pip install ceds-jsonld[excel]`)
  - `DictAdapter` — Python dicts (included)
  - `NDJSONAdapter` — Newline-delimited JSON (included)
  - `APIAdapter` — REST endpoints with pagination (`pip install ceds-jsonld[api]`)
  - `DatabaseAdapter` — SQL databases via SQLAlchemy (`pip install ceds-jsonld[database]`)
- **Pipeline** — High-level orchestrator connecting adapter → mapper → builder → output
  - `stream()` — constant-memory generator for large datasets
  - `build_all()` — batch processing
  - `to_json()` / `to_ndjson()` — file output
  - `to_cosmos()` — Azure Cosmos DB bulk loading
  - `validate()` — pre-build and SHACL validation
  - `PipelineResult` with throughput metrics
- **Validation** — Two-tier validation system:
  - `PreBuildValidator` — fast pure-Python schema checks (~0.01ms/record)
  - `SHACLValidator` — full pySHACL round-trip validation (~50ms/record)
  - Three modes: `strict`, `report`, `sample`
- **Cosmos DB Integration** — `CosmosLoader` with async bulk upsert, `prepare_for_cosmos()` utility, partition key management
- **CLI** — 6 commands: `convert`, `validate`, `introspect`, `generate-mapping`, `list-shapes`, `benchmark`
- **Serializer** — orjson backend (10x faster) with stdlib json fallback
- **Structured Logging** — structlog integration with PII masking (16 field patterns)
- **Dead-Letter Queue** — failed records written to NDJSON file for reprocessing
- **Progress Tracking** — tqdm + custom callback support
- **IRI Sanitization** — `sanitize_iri_component()` and `validate_base_uri()` for injection protection
- **Mapping Overrides** — `FieldMapper.with_overrides()` and `FieldMapper.compose()` for runtime column renaming
- **URI-Based Shape Fetching** — `ShapeRegistry.fetch_shape()` with local caching
- **Person shape** — Shipped as reference implementation with SHACL, context, mapping YAML, and sample data

### Shipped Shapes

- `person` — Person shape with PersonName, PersonBirth, PersonSexGender, PersonDemographicRace, PersonIdentification sub-shapes

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 0.10.0 | 2026-02-11 | 6 native adapters + 2 SIS factory functions. 680 tests. |
| 0.9.6 | 2026-02-08 | Patch: 5 bug fixes (pipe handling, transforms, date validation). 557 tests. |
| 0.9.5 | 2026-02-08 | Patch: fix flaky 100K benchmark on CI Windows runners. |
| 0.9.4 | 2026-02-08 | Patch: 5 bug fixes (non-finite floats, booleans, None handling, empty lists). |
| 0.9.3 | 2026-02-08 | Patch: 5 bug fixes (transform precision, adapter edges, DLQ reliability). |
| 0.9.2 | 2026-02-08 | Patch: 5 bug fixes (validation counting, Cosmos prep, serialization, PII). |
| 0.9.1 | 2026-02-08 | Patch: 8 bug fixes (validation, mapping, sanitization, sample data). |
| 0.9.0 | 2026-02-07 | First public release. All 7 phases complete. |

---

[Unreleased]: https://github.com/daimare9/ceds-jsonld/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/daimare9/ceds-jsonld/compare/v0.9.6...v0.10.0
[0.9.6]: https://github.com/daimare9/ceds-jsonld/compare/v0.9.5...v0.9.6
[0.9.5]: https://github.com/daimare9/ceds-jsonld/compare/v0.9.4...v0.9.5
[0.9.4]: https://github.com/daimare9/ceds-jsonld/compare/v0.9.3...v0.9.4
[0.9.3]: https://github.com/daimare9/ceds-jsonld/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/daimare9/ceds-jsonld/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/daimare9/ceds-jsonld/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/daimare9/ceds-jsonld/releases/tag/v0.9.0
