"""Validation — pre-build lightweight checks and full SHACL validation.

Provides two validation strategies:

1.  **Pre-build validation** (``PreBuildValidator``) — Fast, pure-Python schema
    checks (~0.01 ms/record) derived from the mapping config and optionally
    enriched from SHACL introspection.  Runs on 100 % of records before they
    reach the builder.

2.  **SHACL validation** (``SHACLValidator``) — Full pySHACL round-trip
    validation (~50 ms/record).  Converts built JSON-LD documents back to
    an rdflib graph and validates against the SHACL shape.  Sample-based for
    bulk workflows.

Both validators return ``ValidationResult`` objects with structured,
human-readable error reports.
"""

from __future__ import annotations

import datetime
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ceds_jsonld.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class ValidationMode(Enum):
    """Validation modes controlling failure behaviour.

    Attributes:
        STRICT: Raise ``ValidationError`` on the first failure.
        REPORT: Collect all failures and return them; never raise.
        SAMPLE: Validate a random subset of records (report mode).
    """

    STRICT = "strict"
    REPORT = "report"
    SAMPLE = "sample"


@dataclass
class FieldIssue:
    """A single field-level validation issue.

    Attributes:
        property_path: Dot-separated path, e.g. ``"hasPersonName.FirstName"``.
        message: Human-readable description of the problem.
        severity: ``"error"`` or ``"warning"``.
        expected: What was expected (e.g. a datatype, a list of allowed values).
        actual: What was found.
    """

    property_path: str
    message: str
    severity: str = "error"
    expected: Any = None
    actual: Any = None


@dataclass
class ValidationResult:
    """Outcome of validating one or more records.

    Attributes:
        conforms: ``True`` when zero errors were found.
        record_count: Number of records examined.
        error_count: Total errors across all records.
        warning_count: Total warnings across all records.
        issues: Per-record list of ``FieldIssue`` items, keyed by a record
            identifier (``@id``, index, etc.).
        raw_report: For SHACL validation, the textual pySHACL report.
        run_id: Unique identifier for this validation run (auto-generated UUID).
        timestamp: ISO-8601 timestamp of the validation run (auto-generated).
        shape_name: Name of the shape being validated (e.g. ``"person"``).
        source_name: Description of the data source (e.g. ``"students.csv"``).
        library_version: Version of the ceds-jsonld library that ran the validation.
    """

    conforms: bool = True
    record_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    issues: dict[str, list[FieldIssue]] = field(default_factory=dict)
    raw_report: str = ""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat(),
    )
    shape_name: str = ""
    source_name: str = ""
    library_version: str = ""

    def add_issue(self, record_id: str, issue: FieldIssue) -> None:
        """Append an issue for a specific record.

        Args:
            record_id: Identifier for the record (e.g. ``@id`` value or index).
            issue: The ``FieldIssue`` to record.
        """
        self.issues.setdefault(record_id, []).append(issue)
        if issue.severity == "error":
            self.error_count += 1
            self.conforms = False
        else:
            self.warning_count += 1

    def summary(self) -> str:
        """Return a one-line human-readable summary.

        Returns:
            e.g. ``"10 records checked: 3 errors, 1 warning"``
        """
        parts = [f"{self.record_count} records checked"]
        parts.append(f"{self.error_count} errors")
        parts.append(f"{self.warning_count} warnings")
        return ": ".join([parts[0], ", ".join(parts[1:])])

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict.

        Returns a dict with all metadata, summary counts, and a flat
        list of issues (each issue includes its ``record_id``).
        """
        flat_issues: list[dict[str, Any]] = []
        for record_id, issue_list in self.issues.items():
            for issue in issue_list:
                flat_issues.append({
                    "record_id": record_id,
                    "property_path": issue.property_path,
                    "message": issue.message,
                    "severity": issue.severity,
                    "expected": issue.expected,
                    "actual": issue.actual,
                })

        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "shape_name": self.shape_name,
            "source_name": self.source_name,
            "library_version": self.library_version,
            "conforms": self.conforms,
            "record_count": self.record_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": flat_issues,
        }

    def to_dataframe(self) -> Any:
        """Convert issues to a pandas DataFrame.

        Returns a DataFrame with columns: run_id, timestamp, shape_name,
        source_name, record_id, property_path, severity, message, expected,
        actual.  If there are no issues, returns a DataFrame with those
        columns and zero rows.

        Raises:
            ImportError: If pandas is not installed.
        """
        import pandas as pd

        columns = [
            "run_id", "timestamp", "shape_name", "source_name",
            "record_id", "property_path", "severity", "message",
            "expected", "actual",
        ]
        rows: list[dict[str, Any]] = []
        for record_id, issue_list in self.issues.items():
            for issue in issue_list:
                rows.append({
                    "run_id": self.run_id,
                    "timestamp": self.timestamp,
                    "shape_name": self.shape_name,
                    "source_name": self.source_name,
                    "record_id": record_id,
                    "property_path": issue.property_path,
                    "severity": issue.severity,
                    "message": issue.message,
                    "expected": str(issue.expected) if issue.expected is not None else "",
                    "actual": str(issue.actual) if issue.actual is not None else "",
                })

        return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# Pre-build lightweight validator
# ---------------------------------------------------------------------------


class PreBuildValidator:
    """Fast, pure-Python validation of raw data rows against a mapping config.

    Checks that:
    - Required source columns exist and are non-empty.
    - Values destined for typed fields are plausible (e.g. dates look like
      dates, numerics are numeric).
    - The ``id_source`` column is present.

    Optionally enriched by SHACL introspection via
    :meth:`from_introspector`, which adds allowed-value checks (``sh:in``),
    cardinality checks, and datatype constraints.

    Example:
        >>> validator = PreBuildValidator(shape_def.mapping_config)
        >>> result = validator.validate_row(raw_row)
        >>> result.conforms
        True
    """

    def __init__(
        self,
        mapping_config: dict[str, Any],
        *,
        allowed_values: dict[str, list[str]] | None = None,
    ) -> None:
        """Initialise from a parsed mapping YAML config.

        Args:
            mapping_config: The mapping config dict (from ``ShapeDefinition``).
            allowed_values: Optional dict mapping dotted property paths
                (e.g. ``"hasPersonIdentification.hasPersonIdentificationSystem"``)
                to lists of allowed string values (from ``sh:in``).
        """
        self._config = mapping_config
        self._allowed_values = allowed_values or {}
        self._rules = self._compile_rules()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_row(
        self,
        raw_row: dict[str, Any],
        *,
        record_id: str | None = None,
        mode: ValidationMode = ValidationMode.REPORT,
    ) -> ValidationResult:
        """Validate a single raw data row before mapping.

        Args:
            raw_row: Dict of source field names to values (e.g. a CSV row).
            record_id: Optional identifier for the record (for issue tracking).
            mode: Validation mode.  ``STRICT`` raises on first error.

        Returns:
            A ``ValidationResult`` with any issues found.

        Raises:
            ValidationError: In ``STRICT`` mode, on the first error.
        """
        rid = record_id or str(raw_row.get(self._config.get("id_source", ""), "unknown"))
        result = ValidationResult(record_count=1)

        # Check id_source column
        id_source = self._config.get("id_source", "")
        id_val = raw_row.get(id_source)
        if self._is_empty(id_val):
            issue = FieldIssue(
                property_path="@id",
                message=(
                    f"ID source field '{id_source}' is missing or empty. Available columns: {sorted(raw_row.keys())}"
                ),
                expected=f"non-empty value in '{id_source}'",
                actual=id_val,
            )
            result.add_issue(rid, issue)
            if mode is ValidationMode.STRICT:
                raise ValidationError(issue.message)

        # Check each property's fields
        for rule in self._rules:
            self._check_rule(raw_row, rule, rid, result, mode)

        return result

    def validate_batch(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        mode: ValidationMode = ValidationMode.REPORT,
        sample_rate: float = 1.0,
    ) -> ValidationResult:
        """Validate a batch of raw rows.

        Args:
            rows: Sequence of raw data dicts.
            mode: Validation mode.
            sample_rate: Fraction of rows to validate (0.0–1.0).
                Only used when ``mode`` is ``SAMPLE``.

        Returns:
            Aggregated ``ValidationResult``.
        """
        result = ValidationResult()

        if mode is ValidationMode.SAMPLE:
            sample_size = max(1, int(len(rows) * sample_rate))
            indices = sorted(random.sample(range(len(rows)), min(sample_size, len(rows))))
            to_check = [(i, rows[i]) for i in indices]
        else:
            to_check = list(enumerate(rows))

        effective_mode = ValidationMode.STRICT if mode is ValidationMode.STRICT else ValidationMode.REPORT

        for idx, row in to_check:
            rid = str(row.get(self._config.get("id_source", ""), f"row_{idx}"))
            row_result = self.validate_row(row, record_id=rid, mode=effective_mode)
            result.record_count += 1
            if not row_result.conforms:
                result.conforms = False
            for rec_id, issues in row_result.issues.items():
                for issue in issues:
                    result.add_issue(rec_id, issue)

        return result

    @classmethod
    def from_introspector(
        cls,
        mapping_config: dict[str, Any],
        introspector: Any,
        *,
        context_lookup: dict[str, str] | None = None,
    ) -> PreBuildValidator:
        """Create a validator enriched with SHACL-derived rules.

        Extracts ``sh:in`` allowed values from the introspected shape tree
        and maps them to dotted property paths that match the mapping config.

        Args:
            mapping_config: The parsed mapping YAML config.
            introspector: A ``SHACLIntrospector`` instance.
            context_lookup: Optional context dict for IRI-to-name resolution.

        Returns:
            A ``PreBuildValidator`` with allowed-value constraints.
        """
        allowed: dict[str, list[str]] = {}

        try:
            root = introspector.root_shape()
        except Exception:
            return cls(mapping_config)

        lookup = context_lookup or {}
        iri_to_name = introspector._build_iri_to_name(lookup)

        for prop in root.properties:
            prop_name = iri_to_name.get(prop.path, prop.name or prop.path_local)
            if prop.node_shape:
                child_shapes = introspector.all_shapes()
                child = child_shapes.get(prop.node_shape)
                if child:
                    for child_prop in child.properties:
                        if child_prop.allowed_values:
                            field_name = iri_to_name.get(
                                child_prop.path,
                                child_prop.name or child_prop.path_local,
                            )
                            dotted = f"{prop_name}.{field_name}"
                            allowed[dotted] = child_prop.allowed_values

        return cls(mapping_config, allowed_values=allowed)

    # ------------------------------------------------------------------
    # Internal — rule compilation
    # ------------------------------------------------------------------

    @dataclass
    class _FieldRule:
        """Compiled validation rule for one field."""

        property_path: str
        source_column: str
        required: bool
        datatype: str | None
        allowed_values: list[str]
        is_multi_cardinality: bool
        split_on: str

    def _compile_rules(self) -> list[PreBuildValidator._FieldRule]:
        """Pre-compile per-field rules from the mapping config."""
        rules: list[PreBuildValidator._FieldRule] = []

        for prop_name, prop_def in self._config.get("properties", {}).items():
            cardinality = prop_def.get("cardinality", "single")
            split_on = prop_def.get("split_on", "|")
            is_multi = cardinality == "multiple"

            for _key, field_def in prop_def.get("fields", {}).items():
                target = field_def.get("target", _key)
                source = field_def.get("source", "")
                required = not field_def.get("optional", False)
                datatype = field_def.get("datatype")
                dotted = f"{prop_name}.{target}"
                allowed = self._allowed_values.get(dotted, [])

                rules.append(
                    PreBuildValidator._FieldRule(
                        property_path=dotted,
                        source_column=source,
                        required=required,
                        datatype=datatype,
                        allowed_values=allowed,
                        is_multi_cardinality=is_multi,
                        split_on=split_on,
                    )
                )

        return rules

    def _check_rule(
        self,
        raw_row: dict[str, Any],
        rule: _FieldRule,
        record_id: str,
        result: ValidationResult,
        mode: ValidationMode,
    ) -> None:
        """Check a single field rule against a raw row."""
        value = raw_row.get(rule.source_column)

        # Required field check
        if self._is_empty(value):
            if rule.required:
                issue = FieldIssue(
                    property_path=rule.property_path,
                    message=(
                        f"Required field '{rule.source_column}' is missing or empty. "
                        f"Available columns: {sorted(raw_row.keys())}"
                    ),
                    severity="error",
                    expected=f"non-empty value in '{rule.source_column}'",
                    actual=value,
                )
                result.add_issue(record_id, issue)
                if mode is ValidationMode.STRICT:
                    raise ValidationError(issue.message)
            return

        str_val = str(value)

        # Check for empty pipe segments in multi-cardinality fields (#26)
        if rule.is_multi_cardinality:
            segments = str_val.split(rule.split_on)
            empty_indices = [i for i, seg in enumerate(segments) if not seg.strip()]
            if empty_indices:
                issue = FieldIssue(
                    property_path=rule.property_path,
                    message=(
                        f"Pipe-delimited field '{rule.source_column}' has empty segments "
                        f"at positions {empty_indices} (0-based). "
                        f"Raw value: {str_val!r}. Empty segments produce ghost sub-nodes."
                    ),
                    severity="warning",
                    expected="no empty pipe segments",
                    actual=str_val,
                )
                result.add_issue(record_id, issue)
                if mode is ValidationMode.STRICT:
                    raise ValidationError(issue.message)

        # Datatype plausibility checks
        if rule.datatype:
            self._check_datatype(str_val, rule, record_id, result, mode)

        # Allowed value checks (from sh:in)
        if rule.allowed_values:
            self._check_allowed_values(str_val, rule, record_id, result, mode)

    def _check_datatype(
        self,
        value: str,
        rule: _FieldRule,
        record_id: str,
        result: ValidationResult,
        mode: ValidationMode,
    ) -> None:
        """Plausibility check for typed fields."""
        dt = rule.datatype or ""

        if dt in ("xsd:date",):
            # Strict ISO 8601 date check: must be exactly YYYY-MM-DD with
            # zero-padded components that form a valid calendar date.
            parts = value.split("-")
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                issue = FieldIssue(
                    property_path=rule.property_path,
                    message=(f"Value '{value}' does not look like a valid xsd:date (expected YYYY-MM-DD)"),
                    severity="warning",
                    expected="YYYY-MM-DD",
                    actual=value,
                )
                result.add_issue(record_id, issue)
                if mode is ValidationMode.STRICT:
                    raise ValidationError(issue.message)
                return

            # Enforce zero-padded ISO format: 4-digit year, 2-digit month/day
            year_s, month_s, day_s = parts
            if len(year_s) != 4 or len(month_s) != 2 or len(day_s) != 2:
                issue = FieldIssue(
                    property_path=rule.property_path,
                    message=(f"Value '{value}' is not zero-padded ISO 8601 (expected YYYY-MM-DD, e.g. '2026-02-07')"),
                    severity="warning",
                    expected="YYYY-MM-DD (zero-padded)",
                    actual=value,
                )
                result.add_issue(record_id, issue)
                if mode is ValidationMode.STRICT:
                    raise ValidationError(issue.message)
                return

            # Validate the date is a real calendar date
            try:
                datetime.date(int(year_s), int(month_s), int(day_s))
            except ValueError:
                issue = FieldIssue(
                    property_path=rule.property_path,
                    message=(
                        f"Value '{value}' is not a valid calendar date "
                        f"(e.g. month must be 1-12, day must exist in that month)"
                    ),
                    severity="warning",
                    expected="valid calendar date in YYYY-MM-DD format",
                    actual=value,
                )
                result.add_issue(record_id, issue)
                if mode is ValidationMode.STRICT:
                    raise ValidationError(issue.message) from None

        elif dt in ("xsd:dateTime",):
            if "T" not in value and " " not in value:
                issue = FieldIssue(
                    property_path=rule.property_path,
                    message=(
                        f"Value '{value}' does not look like a valid xsd:dateTime "
                        f"(expected ISO 8601 with time component)"
                    ),
                    severity="warning",
                    expected="YYYY-MM-DDThh:mm:ss",
                    actual=value,
                )
                result.add_issue(record_id, issue)
                if mode is ValidationMode.STRICT:
                    raise ValidationError(issue.message)

        elif dt in ("xsd:integer", "xsd:int"):
            try:
                int(float(value))
            except (ValueError, TypeError):
                issue = FieldIssue(
                    property_path=rule.property_path,
                    message=f"Value '{value}' is not a valid integer",
                    severity="warning",
                    expected="numeric string",
                    actual=value,
                )
                result.add_issue(record_id, issue)
                if mode is ValidationMode.STRICT:
                    raise ValidationError(issue.message) from None

    def _check_allowed_values(
        self,
        value: str,
        rule: _FieldRule,
        record_id: str,
        result: ValidationResult,
        mode: ValidationMode,
    ) -> None:
        """Check value against allowed values (from sh:in)."""
        # For multi-cardinality fields, the raw value may be pipe-delimited
        if rule.is_multi_cardinality:
            parts = value.split(rule.split_on)
        else:
            parts = [value]

        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part not in rule.allowed_values:
                issue = FieldIssue(
                    property_path=rule.property_path,
                    message=(
                        f"Value '{part}' is not in the allowed values list. "
                        f"Allowed: {rule.allowed_values[:5]}{'...' if len(rule.allowed_values) > 5 else ''}"
                    ),
                    severity="warning",
                    expected=rule.allowed_values,
                    actual=part,
                )
                result.add_issue(record_id, issue)
                if mode is ValidationMode.STRICT:
                    raise ValidationError(issue.message)

    @staticmethod
    def _is_empty(value: Any) -> bool:
        """Check if a value is effectively empty."""
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        try:
            import math

            if isinstance(value, float) and math.isnan(value):
                return True
        except (TypeError, ValueError):
            pass
        return False


# ---------------------------------------------------------------------------
# SHACL validator (full round-trip via pySHACL)
# ---------------------------------------------------------------------------


class SHACLValidator:
    """Full SHACL validation of built JSON-LD documents via pySHACL.

    Converts JSON-LD dicts to rdflib graphs and validates against a SHACL
    shape.  Expensive (~50 ms per record) — use sample-based validation for
    bulk workflows.

    Example:
        >>> validator = SHACLValidator("ontologies/person/Person_SHACL.ttl")
        >>> result = validator.validate_one(jsonld_doc)
        >>> result.conforms
        True
        >>> result = validator.validate_batch(docs, mode=ValidationMode.SAMPLE, sample_rate=0.01)
    """

    def __init__(
        self,
        shacl_source: str | Path,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Load the SHACL shape graph for validation.

        Args:
            shacl_source: Path to a SHACL Turtle file.
            context: Optional JSON-LD context dict.  If provided, it is injected
                into documents that use a URL-based ``@context`` before parsing.

        Raises:
            ValidationError: If pySHACL is not installed or SHACL file is invalid.
        """
        try:
            from pyshacl import validate as _pyshacl_validate  # noqa: F401
        except ImportError as exc:
            msg = (
                "SHACL validation requires the 'pyshacl' package. Install it with: pip install ceds-jsonld[validation]"
            )
            raise ValidationError(msg) from exc

        try:
            from rdflib import Graph
        except ImportError as exc:
            msg = "SHACL validation requires rdflib. Install it with: pip install rdflib"
            raise ValidationError(msg) from exc

        self._shacl_graph = Graph()
        source_path = Path(shacl_source)
        try:
            if source_path.exists():
                self._shacl_graph.parse(str(source_path), format="turtle")
            else:
                self._shacl_graph.parse(data=str(shacl_source), format="turtle")
        except Exception as exc:
            msg = f"Failed to parse SHACL source: {exc}"
            raise ValidationError(msg) from exc

        self._context = context

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_one(
        self,
        doc: dict[str, Any],
        *,
        mode: ValidationMode = ValidationMode.REPORT,
    ) -> ValidationResult:
        """Validate a single JSON-LD document against the SHACL shape.

        Args:
            doc: A JSON-LD document dict (output of ``JSONLDBuilder``).
            mode: ``STRICT`` raises on failure; ``REPORT`` collects issues.

        Returns:
            A ``ValidationResult``.

        Raises:
            ValidationError: In ``STRICT`` mode when the document does not
                conform.
        """
        import json as _json

        from pyshacl import validate as _pyshacl_validate
        from rdflib import Graph

        result = ValidationResult(record_count=1)
        record_id = doc.get("@id", "unknown")

        # Prepare the document for rdflib parsing
        doc_for_parse = self._prepare_doc(doc)
        json_str = _json.dumps(doc_for_parse)

        # Parse JSON-LD into rdflib Graph
        data_graph = Graph()
        try:
            data_graph.parse(data=json_str, format="json-ld")
        except Exception as exc:
            issue = FieldIssue(
                property_path="@document",
                message=f"Failed to parse JSON-LD as RDF: {exc}",
            )
            result.add_issue(str(record_id), issue)
            if mode is ValidationMode.STRICT:
                raise ValidationError(issue.message) from exc
            return result

        # Validate with pySHACL
        try:
            conforms, results_graph, results_text = _pyshacl_validate(
                data_graph,
                shacl_graph=self._shacl_graph,
                inference="none",
                abort_on_first=mode is ValidationMode.STRICT,
            )
        except Exception as exc:
            issue = FieldIssue(
                property_path="@document",
                message=f"pySHACL runtime error: {exc}",
            )
            result.add_issue(str(record_id), issue)
            if mode is ValidationMode.STRICT:
                raise ValidationError(issue.message) from exc
            return result

        result.raw_report = results_text

        if not conforms:
            issues = self._parse_shacl_results(results_graph, str(record_id))
            for issue in issues:
                result.add_issue(str(record_id), issue)

            if mode is ValidationMode.STRICT:
                msg = f"SHACL validation failed for '{record_id}':\n{results_text}"
                raise ValidationError(msg)

        return result

    def validate_batch(
        self,
        docs: Sequence[dict[str, Any]],
        *,
        mode: ValidationMode = ValidationMode.REPORT,
        sample_rate: float = 0.01,
    ) -> ValidationResult:
        """Validate a batch of JSON-LD documents.

        Args:
            docs: Sequence of JSON-LD documents.
            mode: Validation mode.
            sample_rate: Fraction of documents to validate in ``SAMPLE`` mode
                (default 1 %).

        Returns:
            Aggregated ``ValidationResult``.
        """
        result = ValidationResult()

        if mode is ValidationMode.SAMPLE:
            sample_size = max(1, int(len(docs) * sample_rate))
            indices = sorted(random.sample(range(len(docs)), min(sample_size, len(docs))))
            to_check = [(i, docs[i]) for i in indices]
        else:
            to_check = list(enumerate(docs))

        effective_mode = ValidationMode.STRICT if mode is ValidationMode.STRICT else ValidationMode.REPORT

        for _idx, doc in to_check:
            doc_result = self.validate_one(doc, mode=effective_mode)
            result.record_count += 1
            if not doc_result.conforms:
                result.conforms = False
            for rec_id, issues in doc_result.issues.items():
                for issue in issues:
                    result.add_issue(rec_id, issue)
            if doc_result.raw_report:
                result.raw_report += doc_result.raw_report + "\n"

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _prepare_doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Prepare a JSON-LD doc for rdflib parsing.

        If the document has a URL-based ``@context`` and we have a local
        context dict, inject the local context so parsing doesn't require
        network access.
        """
        if self._context is None:
            return doc

        context_val = doc.get("@context")
        if isinstance(context_val, str):
            # Replace URL context with local context dict
            prepared = dict(doc)
            prepared["@context"] = self._context.get("@context", self._context)
            return prepared

        return doc

    def _parse_shacl_results(
        self,
        results_graph: Any,
        record_id: str,
    ) -> list[FieldIssue]:
        """Extract structured issues from the pySHACL results graph.

        Args:
            results_graph: The rdflib Graph of validation results.
            record_id: Record identifier for issue tracking.

        Returns:
            List of ``FieldIssue`` objects.
        """
        from rdflib import Namespace

        SH = Namespace("http://www.w3.org/ns/shacl#")
        issues: list[FieldIssue] = []

        for result_node in results_graph.subjects(
            predicate=None,
            object=SH.ValidationResult,
        ):
            # Extract result path
            result_path = results_graph.value(result_node, SH.resultPath)
            result_msg = results_graph.value(result_node, SH.resultMessage)
            result_severity = results_graph.value(result_node, SH.resultSeverity)
            results_graph.value(result_node, SH.focusNode)
            value_node = results_graph.value(result_node, SH.value)

            # Map severity
            severity = "error"
            if result_severity and "Warning" in str(result_severity):
                severity = "warning"

            # Build human-readable path
            path_str = str(result_path) if result_path else "@document"
            # Try to extract local name from IRI
            if "#" in path_str:
                path_str = path_str.rsplit("#", 1)[1]
            elif "/" in path_str and path_str.startswith("http"):
                path_str = path_str.rsplit("/", 1)[1]

            issues.append(
                FieldIssue(
                    property_path=path_str,
                    message=str(result_msg) if result_msg else "SHACL constraint violation",
                    severity=severity,
                    expected=None,
                    actual=str(value_node) if value_node else None,
                )
            )

        # If no structured results found but we know it failed, add a generic issue
        if not issues:
            issues.append(
                FieldIssue(
                    property_path="@document",
                    message="SHACL validation failed (see raw_report for details)",
                    severity="error",
                )
            )

        return issues
