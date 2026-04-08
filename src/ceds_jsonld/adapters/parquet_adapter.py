"""Parquet source adapter — read Parquet files using pandas + pyarrow.

Supports column selection, row-group-based batching, and fast metadata-only
row counting without loading the full dataset into memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from ceds_jsonld.adapters.base import SourceAdapter
from ceds_jsonld.exceptions import AdapterError


class ParquetAdapter(SourceAdapter):
    """Read records from a Parquet file.

    Example:
        >>> adapter = ParquetAdapter("students.parquet")
        >>> for row in adapter.read():
        ...     print(row["FirstName"])
    """

    def __init__(
        self,
        path: str | Path,
        *,
        columns: list[str] | None = None,
        **pandas_kwargs: Any,
    ) -> None:
        """Initialize with a file path and optional column filter.

        Args:
            path: Path to the Parquet file.
            columns: Subset of columns to read. ``None`` reads all columns.
            **pandas_kwargs: Additional keyword arguments forwarded to
                ``pandas.read_parquet()``.
        """
        self._path = Path(path)
        if not self._path.exists():
            msg = f"Parquet file not found: {self._path}"
            raise AdapterError(msg)
        self._columns = columns
        self._pandas_kwargs = pandas_kwargs

    def read(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Yield each row as a dict.

        Missing / NaN values are converted to empty strings.

        Returns:
            Iterator of dicts keyed by column name.
        """
        try:
            df = pd.read_parquet(
                self._path,
                columns=self._columns,
                **self._pandas_kwargs,
            )
        except Exception as exc:
            msg = f"Failed to read Parquet '{self._path}': {exc}"
            raise AdapterError(msg) from exc

        df = df.fillna("")
        yield from df.to_dict(orient="records")

    def read_batch(self, batch_size: int = 1000, **kwargs: Any) -> Iterator[list[dict[str, Any]]]:
        """Yield batches using pyarrow row-group-aware reading.

        Reads the Parquet file in row-group-sized chunks via pyarrow and
        converts each chunk to a list of dicts. If a single row group
        exceeds *batch_size*, it is yielded as-is (no splitting).

        Args:
            batch_size: Target number of rows per batch.

        Returns:
            Iterator of lists of dicts.
        """
        try:
            parquet_file = pq.ParquetFile(self._path)
        except Exception as exc:
            msg = f"Failed to open Parquet '{self._path}': {exc}"
            raise AdapterError(msg) from exc

        batch: list[dict[str, Any]] = []
        for i in range(parquet_file.metadata.num_row_groups):
            table = parquet_file.read_row_group(i, columns=self._columns)
            df = table.to_pandas().fillna("")
            rows = df.to_dict(orient="records")
            batch.extend(rows)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def count(self) -> int | None:
        """Return the total row count from Parquet metadata (no data read)."""
        try:
            metadata = pq.read_metadata(self._path)
            return int(metadata.num_rows)
        except Exception:
            return None
