"""Source adapters for ingesting data from CSV, Excel, APIs, databases, and more."""

from __future__ import annotations

from ceds_jsonld.adapters.api_adapter import APIAdapter
from ceds_jsonld.adapters.base import SourceAdapter
from ceds_jsonld.adapters.bigquery_adapter import BigQueryAdapter
from ceds_jsonld.adapters.canvas_adapter import CanvasAdapter
from ceds_jsonld.adapters.csv_adapter import CSVAdapter
from ceds_jsonld.adapters.database_adapter import DatabaseAdapter
from ceds_jsonld.adapters.databricks_adapter import DatabricksAdapter
from ceds_jsonld.adapters.dict_adapter import DictAdapter
from ceds_jsonld.adapters.excel_adapter import ExcelAdapter
from ceds_jsonld.adapters.google_sheets_adapter import GoogleSheetsAdapter
from ceds_jsonld.adapters.ndjson_adapter import NDJSONAdapter
from ceds_jsonld.adapters.oneroster_adapter import OneRosterAdapter
from ceds_jsonld.adapters.parquet_adapter import ParquetAdapter
from ceds_jsonld.adapters.relational_adapter import RelationalAdapter
from ceds_jsonld.adapters.sis_factories import blackbaud_adapter, powerschool_adapter
from ceds_jsonld.adapters.snowflake_adapter import SnowflakeAdapter

__all__ = [
    "APIAdapter",
    "BigQueryAdapter",
    "CanvasAdapter",
    "CSVAdapter",
    "DatabaseAdapter",
    "DatabricksAdapter",
    "DictAdapter",
    "ExcelAdapter",
    "GoogleSheetsAdapter",
    "NDJSONAdapter",
    "OneRosterAdapter",
    "ParquetAdapter",
    "RelationalAdapter",
    "SnowflakeAdapter",
    "SourceAdapter",
    "blackbaud_adapter",
    "powerschool_adapter",
]
