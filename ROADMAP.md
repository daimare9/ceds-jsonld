# CEDS JSON-LD Generator — Roadmap

**Project:** `ceds-jsonld` — A Python library for ingesting education data from any source,
mapping it to CEDS/CEPI ontology-backed RDF shapes, outputting conformant JSON-LD, and
loading it into Azure Cosmos DB.

**Date:** February 11, 2026
**Current Release:** v0.10.0 (published to PyPI) · 680 tests

---

## Table of Contents

1. [v1.0 Summary](#v10-summary)
2. [v0.10.0 — Native Adapters](#v0100--native-adapters)
3. [v2.0 — Phase 1: Synthetic Data Generator](#v20--phase-1-synthetic-data-generator)
4. [v2.0 — Phase 2: AI-Assisted Mapping Wizard + Quick-Wins](#v20--phase-2-ai-assisted-mapping-wizard--quick-wins)
5. [v2.0 — Future Features (Backlog)](#v20--future-features-backlog)
6. [Risk Register](#risk-register)
7. [Research Backlog](#research-backlog)
8. [Summary Timeline](#summary-timeline)

---

## v1.0 Summary

v1.0 shipped February 2026 after 9 phases. The library provides: Shape Registry,
6 source adapters (CSV, Excel, Dict, NDJSON, API, Database), YAML-driven field mapping,
high-performance JSON-LD builder (direct dict construction, 161x faster than rdflib+PyLD),
SHACL validation (optional), Cosmos DB async bulk loader, CLI (6 commands), Sphinx docs,
structured logging, dead-letter queue, and CI/CD via GitHub Actions.

See the [README](README.md) for current features, installation, and usage examples.
Architectural decisions are documented in [docs/adr/](docs/adr/).

---

## v0.10.0 — Native Adapters

**Status:** ✅ Complete (680 tests passing)
**Research:** `ResearchFiles/FEATURE7_NATIVE_ADAPTERS_RESEARCH.md`
**Target extras:** `[sheets]`, `[canvas]`, `[oneroster]`, `[snowflake]`, `[bigquery]`, `[databricks]`

Extend the adapter layer with native connectors for education-sector data sources:
Google Sheets, SIS platforms (Canvas, OneRoster/PowerSchool/Blackbaud), and cloud
data warehouses (Snowflake, BigQuery, Databricks). All adapters follow the existing
`SourceAdapter` ABC and yield plain dicts — zero changes to downstream components.

### Key Research Findings

- **Google Sheets** — `gspread` v6+ returns `list[dict]` via `get_all_records()`. Highest demand in K-12.
- **Cloud warehouses** — All three follow PEP 249 DB-API 2.0 with dict-convertible rows. ~80-120 lines each.
- **Canvas LMS** — Official Python library (`canvasapi`), paginated `PaginatedList` objects.
- **OneRoster** — One adapter covers Infinite Campus, ClassLink, Clever, Aeries via standard 1.1 endpoints.
- **PowerSchool / Blackbaud** — Factory functions pre-configure `APIAdapter` (no custom adapter needed).

### Tasks

| # | Task | Effort |
|---|------|--------|
| **Phase A — Spreadsheets & Cloud Warehouses** |||
| 1.1 | `GoogleSheetsAdapter` (`gspread` v6+) | ✅ Done |
| 1.2 | `SnowflakeAdapter` (`snowflake-connector-python`) | ✅ Done |
| 1.3 | `BigQueryAdapter` (`google-cloud-bigquery`) | ✅ Done |
| 1.4 | `DatabricksAdapter` (`databricks-sql-connector`) | ✅ Done |
| 1.5 | Tests: Phase A adapters | ✅ Done |
| **Phase B — SIS Platforms** |||
| 1.6 | `CanvasAdapter` (`canvasapi` v3+) | ✅ Done |
| 1.7 | `OneRosterAdapter` (`httpx`, standard 1.1 endpoints) | ✅ Done |
| 1.8 | Tests: Phase B adapters | ✅ Done |
| **Phase C — Templates & Documentation** |||
| 1.9 | PowerSchool factory function | ✅ Done |
| 1.10 | Blackbaud factory function | ✅ Done |
| 1.11 | New extras in `pyproject.toml` | ✅ Done |
| 1.12 | Sphinx adapter guides + README updates | ✅ Done |

### Deliverables

- [x] `GoogleSheetsAdapter`, `SnowflakeAdapter`, `BigQueryAdapter`, `DatabricksAdapter`
- [x] `CanvasAdapter`, `OneRosterAdapter`
- [x] `powerschool_adapter()` and `blackbaud_adapter()` factory functions
- [x] New extras groups: `[sheets]`, `[snowflake]`, `[bigquery]`, `[databricks]`, `[canvas]`, `[oneroster]`, `[sis]`, `[warehouse]`, `[all-adapters]`
- [x] 76 new tests (680 total, all passing). Sphinx docs and README updated.

---

## v2.0 — Phase 1: Synthetic Data Generator

**Status:** ✅ Research Validated with End-to-End PoC (Feb 9, 2026)
**Research:** `ResearchFiles/FEATURE4_SYNTHETIC_DATA_RESEARCH.md`
**PoC Script:** `ResearchFiles/phase1_benchmarks/bench_person_jsonld_dynamic.py`
**Target extras:** `pip install ceds-jsonld[sdg]`

Generate fully valid, realistic CEDS-conformant synthetic data for any registered shape.

### Approach

1. **Concept Scheme properties** (Sex, Race, GradeLevel, etc.) — extract valid
   `NamedIndividual` IRIs from the ontology. Random selection, zero LLM cost.
2. **Literal value properties** (names, dates, IDs) — local LLM generates contextually
   appropriate values using ontology metadata. Three-tier fallback: LLM → cache →
   deterministic generators.

**Runtime:** `transformers` + `torch` (pre-built wheels, no C compiler). Ollama
auto-detected as power-user alternative. Default model: Qwen3 4B (~8 GB, BFloat16).

### PoC Validation Highlights

- Three ontology sources required: CEDS-Ontology.rdf (235K triples) + Common.ttl + Person_Extension_Ontology.ttl.
- Two concept scheme resolution strategies: `sh:in` direct resolve + `schema:rangeIncludes` → class → NamedIndividual.
- SHACL property corrections applied (hasSex → P000255, hasRaceAndEthnicity → P001943).
- Performance: 9s ontology load, 7.3s model load, 6.1s LLM generation, 0.088ms dict construction.
- All 557 project tests pass after fixes.

### Tasks

| # | Task |
|---|------|
| 1.1 | `ConceptSchemeResolver` — parse ontology RDF, resolve values via `sh:in` and `schema:rangeIncludes` |
| 1.2 | `FallbackGenerators` — pure-Python generators for all XSD types + name-aware defaults |
| 1.3 | `MappingAwareAssembler` — read mapping YAML, assemble CSV rows, pipe-delimited fields |
| 1.4 | `SyntheticDataGenerator` — core orchestrator |
| 1.5 | CSV + NDJSON output writers |
| 1.6 | Round-trip integration tests (generate → Pipeline → JSON-LD → SHACL validate) |
| 1.7 | `[sdg]` extras (`torch`, `transformers`, `huggingface-hub`) |
| 1.8 | `OntologyMetadataExtractor` — extract labels, descriptions, constraints for prompts |
| 1.9 | `LLMValueGenerator` — prompt building + structured output parsing |
| 1.10 | Ollama auto-detection (prefer over in-process when available) |
| 1.11 | File-based caching layer (`~/.ceds_jsonld/cache/`) |
| 1.12 | Three-tier fallback logic (LLM → cache → deterministic) |
| 1.13 | Post-generation validation (datatype constraints, date formats, numeric ranges) |
| 1.14 | `generate-sample` CLI command |
| 1.15 | `generate-cache` CLI command (pre-warm cache for CI) |
| 1.16 | Ship default Person cache for zero-setup CI |
| 1.17 | Streaming mode for 100K+ row generation |
| 1.18 | JSON-LD output mode (generate → Pipeline → JSON-LD end-to-end) |
| 1.19 | Benchmark suite (LLM generation, cached, 10K/100K/1M assembly) |
| 1.20 | Model comparison (Qwen3 4B vs. Granite4 3B vs. Phi-4 Mini) |
| 1.21 | Distribution profiles (optional YAML config for demographic distributions) |
| 1.22 | Documentation |

### Deliverables

- [ ] `ConceptSchemeResolver` + `FallbackGenerators` — zero-LLM synthetic data for any shape
- [ ] `LLMValueGenerator` + `OntologyMetadataExtractor` — LLM-powered realistic literals
- [ ] Caching layer (generate once, reuse everywhere including CI)
- [ ] CLI commands: `generate-sample`, `generate-cache`
- [ ] `[sdg]` extras group in `pyproject.toml`
- [ ] Round-trip tests + benchmarks
- [ ] Docs: user guide, API reference, README section

---

## v2.0 — Phase 2: AI-Assisted Mapping Wizard + Quick-Wins

**Status:** ✅ Complete (March 21, 2026)
**Research:** `ResearchFiles/FEATURE1_AI_MAPPING_WIZARD_RESEARCH.md`

AI-assisted wizard that reads CSV/Excel column headers and sample values, then suggests
a complete `_mapping.yaml` config — including transform recommendations and confidence scores.

### Three-Phase Matching (validated by PoC)

1. **Concept-value matching** — compare distinct values against CEDS concept scheme enums.
   Resolves ~38% of columns in <1ms. Zero LLM calls.
2. **Heuristic name matching** — exact/fuzzy name matching + datatype compatibility.
3. **LLM-assisted resolution** — for remaining columns, local `transformers` engine suggests
   mappings with confidence scores. FERPA compliant (local-only).

### PoC Validation Highlights

- 100% mapping accuracy across 34 columns in 3 test CSVs (abbreviated, verbose, short-code naming).
- Concept-value matching is the breakout finding — resolves columns by value overlap, no AI needed.
- Correct transform suggestions: `date_format`, `sex_prefix`, `race_prefix`, `int_clean`.
- Architecture upgraded from two-phase to three-phase based on PoC findings.

### Tasks

| # | Task |
|---|------|
| 2.1 | `ColumnProfiler` — column analysis with type inference, null rates, delimiters |
| 2.2 | `ShapeMetadataCollector` — aggregate target properties from introspector + ontology |
| 2.3 | `HeuristicMatcher` — scoring engine: name matching, fuzzy, datatype, concept overlap |
| 2.4 | `MatchingEngine` orchestrator — three-phase: concept-value → heuristic → LLM |
| 2.5 | `MappingAssembler` — build complete YAML config + confidence annotations |
| 2.6 | `WizardResult` dataclass — config + confidence report + unmapped lists |
| 2.7 | Tests: heuristic matching |
| 2.8 | Tests: end-to-end (CSV → wizard → YAML → Pipeline → valid JSON-LD) |
| 2.9 | LLM prompt builder + response validator |
| 2.10 | Integration with Phase 1 LLM engine |
| 2.11 | Transform suggestion logic (pattern-based + LLM-assisted) |
| 2.12 | Tests: LLM matching |
| 2.13 | `map-wizard` CLI command |
| 2.14 | Preview mode (run N records through Pipeline, show output) |
| 2.15 | Shape auto-detection (column overlap scoring across shapes) |
| 2.16 | YAML annotation output (confidence comments, review markers) |
| 2.17 | QW-1: `--validate-only` HTML report |
| 2.18 | QW-2: `introspect` Markdown table output |
| 2.19 | QW-3: Built-in `benchmark` command |
| 2.20 | Documentation |

### Deliverables

- [x] `MappingWizard` — heuristic + LLM-assisted column→property matching
- [x] `ColumnProfiler`, `HeuristicMatcher`, `MatchingEngine`
- [x] LLM integration (reuses Phase 1 engine, zero new deps)
- [x] `map-wizard` CLI command with annotated YAML output
- [x] QW-1: HTML validation report (`--report` on validate command)
- [x] QW-2: `introspect` Markdown table output (`--format markdown`)
- [ ] QW-3: Built-in `benchmark` command (deferred to next phase)
- [x] Tests and docs

> **Phase 2 completed March 21, 2026.** Three-phase matching pipeline (concept-value → heuristic → LLM) with `MappingWizard` orchestrator, CLI integration, HTML validation reports, introspect markdown output. QW-3 benchmark command deferred.

---

## v2.0 — Future Features (Backlog)

Candidate features for v2.1+. Nothing committed — each needs research and prioritization.

### Feature 2: Visual Mapping Dashboard (Web UI)

Drag-and-drop column → shape property with live JSON-LD preview. Save mapping profile → reusable YAML.

**Open questions:** Framework choice (Streamlit, Gradio, FastAPI + React), hosting model,
scope boundary (keep library headless, ship UI as separate package?).

### Feature 3: Verifiable Credentials (VC) Generator

Turn Person + Enrollment + Course into a W3C Verifiable Credential. Open Badges 3.0 / CLR 2.0 support.

**Open questions:** VC Data Model 2.0, DID method support, signing libraries + key management.

### Feature 5: Multi-format Round-trip (JSON-LD ↔ RDF ↔ CSV/Parquet)

`to_turtle()`, `to_rdf_graph()`, `from_rdf()` — triplestore/SPARQL integration.

**Open questions:** rdflib round-trip fidelity, Parquet schema from SHACL, triplestore compatibility.

### Feature 6: CEDS Version Migration Tool

Auto-detect source CEDS version → target version. Apply predefined migration rules.

**Open questions:** CEDS versioning scheme analysis, breaking vs. non-breaking changes, migration rule format.

### Feature 8: Observability That Actually Matters

OpenTelemetry traces + metrics, Grafana dashboard, PII leakage alerts.

**Open questions:** OTel Python SDK patterns, span design, Azure Monitor / App Insights exporters.

### Feature 9: Community Shape Marketplace

`ceds-jsonld list-shapes --remote` — pull community-contributed shapes from a central registry.

**Open questions:** Shape packaging format, central registry (GitHub org? PyPI sub-packages?), governance model.

### Feature 10: Docker + One-click Deploy

Docker image with all extras, Helm chart / Azure Container App template.

**Open questions:** Image size optimization, Conda-forge recipe, ARM/Bicep template.

---

## Risk Register

| # | Risk | Impact | Likelihood | Mitigation |
|---|------|--------|------------|------------|
| R8 | Local LLM model too large for user's hardware | Medium | Medium | Default ~2.5 GB; fallback generators work without LLM. `--no-llm` flag. |
| R9 | PyPI size limit prevents bundling model | Low | High (confirmed) | Model auto-downloaded via `huggingface-hub`. Pre-generated cache ships for CI. |
| R10 | LLM-generated values fail SHACL validation | Medium | Medium | Post-generation validation + deterministic fallback. |
| R11 | SIS vendor APIs behind login walls; evolving endpoints | Medium | Medium | Build to standards (OneRoster); factory functions for vendor-specific REST APIs. |
| R12 | Cloud warehouse connectors bring heavy transitive deps | Low | Medium | Each adapter in its own extras group; document minimum install. |

---

## Research Backlog

Open questions to investigate as the project progresses:

### JSON-LD 1.1 Features

- [ ] `@nest` for grouping properties without creating new nodes
- [ ] `@import` in contexts to reduce duplication across shape-specific contexts
- [ ] `@container: @set` for normalizing arrays

### Alternative Validation Approaches

- [ ] JSON Schema from SHACL (ultra-fast, no RDF round-trip)
- [ ] Pydantic models from SHACL (type-safe Python validation)
- [ ] Cosmos DB stored procedures (server-side validation on upsert)

### Graph Database Integration

- [ ] Azure Cosmos DB Gremlin API for graph queries
- [ ] Apache Jena / Oxigraph for SPARQL endpoints
- [ ] Neo4j import from JSON-LD

### Change Data Capture

- [ ] Cosmos DB Change Feed for downstream propagation
- [ ] Event-driven: new JSON-LD → Azure Function → notification/ETL

### CEDS Ontology Evolution

- [ ] Ontology update propagation strategy
- [ ] Version-pin ontology files, test against new versions in CI

---

## Summary Timeline

| Phase | Status | Key Deliverable |
|-------|--------|----------------|
| **v1.0 (Phases 0–8)** | ✅ Complete | Full library: 557 tests, published to PyPI. See [README](README.md). |
| **v0.10.0** | ✅ Complete | Native Adapters — 6 adapters + 2 factory functions. 76 new tests (680 total). |
| **v2.0 Phase 1** | 📋 Planning | Synthetic Data Generator — concept scheme extraction + local LLM. |
| **v2.0 Phase 2** | ✅ Complete | AI-Assisted Mapping Wizard — three-phase matching, QW-1 HTML reports, QW-2 markdown. |
