"""Relational adapter — join a primary source with satellite sources.

Enables star-schema data (separate Parquet/CSV/database tables per relationship)
to be processed through the existing Pipeline without any pre-join ETL.
Satellite tables are loaded eagerly into memory at init time, keyed by the
foreign-key column, then injected into each primary row under ``__related__``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from ceds_jsonld.adapters.base import SourceAdapter
from ceds_jsonld.exceptions import AdapterError
from ceds_jsonld.logging import get_logger

_log = get_logger(__name__)

#: Key injected into each enriched primary row to carry satellite data.
RELATED_KEY = "__related__"


class RelationalAdapter(SourceAdapter):
    """Join a primary source adapter with satellite adapters for one-to-many data.

    Loads all satellite data into memory at initialization, keyed by the join
    column. For each primary row yielded, injects a ``__related__`` dict
    containing the matching satellite rows for each logical table name.

    This allows YAML mapping configs to reference satellite rows via the
    ``source_table`` property key, enabling relational one-to-many data to
    become embedded typed arrays in JSON-LD output — with no pre-join ETL.

    Example:
        >>> adapter = RelationalAdapter(
        ...     primary=ParquetAdapter("students.parquet"),
        ...     join_key="student_id",
        ...     satellites={
        ...         "identifications": ParquetAdapter("student_ids.parquet"),
        ...         "races": ParquetAdapter("student_races.parquet"),
        ...     }
        ... )
        >>> for row in adapter.read():
        ...     ids = row["__related__"]["identifications"]
        ...     print(row["student_id"], len(ids))
    """

    def __init__(
        self,
        primary: SourceAdapter,
        join_key: str,
        satellites: dict[str, SourceAdapter],
        *,
        satellite_join_key: str | None = None,
    ) -> None:
        """Initialize and eagerly load all satellite data into memory.

        Args:
            primary: The primary (one-side) adapter. Yields one row per entity.
            join_key: Column name in the primary table that identifies each
                entity (e.g. ``"student_id"``).
            satellites: Dict mapping a logical table name to its adapter.
                Each adapter yields many-side rows for that relationship.
                At least one entry is required.
            satellite_join_key: Column name in the satellite tables used to
                match back to the primary. Defaults to the same value as
                ``join_key``.

        Raises:
            AdapterError: If ``join_key`` is blank or ``satellites`` is empty.
        """
        if not join_key or not join_key.strip():
            msg = "join_key must be a non-empty string."
            raise AdapterError(msg)
        if not satellites:
            msg = (
                "RelationalAdapter requires at least one satellite adapter. "
                "If you have no satellites, use the primary adapter directly."
            )
            raise AdapterError(msg)

        self._primary = primary
        self._join_key = join_key
        self._sat_join_key = satellite_join_key or join_key
        self._satellite_index: dict[str, dict[str, list[dict[str, Any]]]] = {}

        # Eagerly build in-memory index for every satellite table
        for table_name, sat_adapter in satellites.items():
            index: dict[str, list[dict[str, Any]]] = defaultdict(list)
            rows_loaded = 0
            for row in sat_adapter.read():
                fk_value = row.get(self._sat_join_key)
                if fk_value is None or str(fk_value).strip() == "":
                    _log.warning(
                        "relational_adapter.missing_fk",
                        table=table_name,
                        fk_column=self._sat_join_key,
                    )
                    continue
                index[str(fk_value)].append(row)
                rows_loaded += 1
            self._satellite_index[table_name] = dict(index)
            _log.info(
                "relational_adapter.satellite_loaded",
                table=table_name,
                rows=rows_loaded,
                unique_keys=len(self._satellite_index[table_name]),
            )

    def read(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Yield enriched primary rows with satellite data injected.

        Each primary row is yielded with an additional ``__related__`` key
        whose value is ``{table_name: [matching_satellite_rows]}``. If a
        primary entity has no satellite rows for a given table, an empty list
        is used — the property will be omitted from the JSON-LD output.

        Returns:
            Iterator of dicts. Each dict contains all primary row fields plus
            ``{"__related__": {table_name: [satellite_row, ...]}}``.
        """
        for primary_row in self._primary.read(**kwargs):
            pk_value = primary_row.get(self._join_key)
            pk_str = "" if pk_value is None else str(pk_value)

            related: dict[str, list[dict[str, Any]]] = {
                table_name: index.get(pk_str, []) for table_name, index in self._satellite_index.items()
            }

            enriched = dict(primary_row)
            enriched[RELATED_KEY] = related
            yield enriched

    def count(self) -> int | None:
        """Return primary row count if the primary adapter supports it."""
        return self._primary.count()
