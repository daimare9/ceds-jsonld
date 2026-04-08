"""ceds-jsonld — Python library for CEDS/CEPI JSON-LD generation."""

from __future__ import annotations

from ceds_jsonld.adapters import (
    APIAdapter,
    BigQueryAdapter,
    CanvasAdapter,
    CSVAdapter,
    DatabaseAdapter,
    DatabricksAdapter,
    DictAdapter,
    ExcelAdapter,
    GoogleSheetsAdapter,
    NDJSONAdapter,
    OneRosterAdapter,
    SnowflakeAdapter,
    SourceAdapter,
    blackbaud_adapter,
    powerschool_adapter,
)
from ceds_jsonld.builder import JSONLDBuilder
from ceds_jsonld.cosmos import CosmosLoader, prepare_for_cosmos
from ceds_jsonld.introspector import NodeShapeInfo, PropertyInfo, SHACLIntrospector
from ceds_jsonld.logging import get_logger
from ceds_jsonld.mapping import FieldMapper
from ceds_jsonld.pipeline import Pipeline, PipelineResult
from ceds_jsonld.registry import ShapeDefinition, ShapeRegistry
from ceds_jsonld.sanitize import sanitize_iri_component, sanitize_string_value, validate_base_uri
from ceds_jsonld.validator import (
    FieldIssue,
    PreBuildValidator,
    SHACLValidator,
    ValidationMode,
    ValidationResult,
)
from ceds_jsonld.wizard import MappingWizard

__version__ = "1.0.4"
__all__ = [
    "APIAdapter",
    "BigQueryAdapter",
    "CanvasAdapter",
    "CSVAdapter",
    "CosmosLoader",
    "DatabaseAdapter",
    "DatabricksAdapter",
    "DictAdapter",
    "ExcelAdapter",
    "FieldIssue",
    "GoogleSheetsAdapter",
    "JSONLDBuilder",
    "FieldMapper",
    "MappingWizard",
    "NDJSONAdapter",
    "NodeShapeInfo",
    "OneRosterAdapter",
    "Pipeline",
    "PipelineResult",
    "PreBuildValidator",
    "PropertyInfo",
    "SHACLIntrospector",
    "SHACLValidator",
    "ShapeDefinition",
    "ShapeRegistry",
    "SnowflakeAdapter",
    "SourceAdapter",
    "ValidationMode",
    "ValidationResult",
    "blackbaud_adapter",
    "get_logger",
    "powerschool_adapter",
    "prepare_for_cosmos",
    "sanitize_iri_component",
    "sanitize_string_value",
    "validate_base_uri",
]
