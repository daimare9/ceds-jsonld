"""Mapping-aware assembler — build source rows from generated values.

Reads a mapping YAML config and produces flat dicts that look like CSV rows,
ready to be fed through the existing FieldMapper → JSONLDBuilder pipeline.
Handles pipe-delimited multi-value fields and comma-delimited sub-arrays.
"""

from __future__ import annotations

import random
from typing import Any


class MappingAwareAssembler:
    """Assemble flat source rows from generated values using a mapping config.

    The assembler reads the mapping YAML to understand which source columns
    exist and how sub-shapes map to pipe-delimited fields. It then draws from
    pre-generated value pools to produce rows that look exactly like real
    CSV input.

    Example:
        >>> assembler = MappingAwareAssembler(mapping_config, value_pools)
        >>> row = assembler.assemble_one()
        >>> row["FirstName"]
        'Emma'
        >>> "|" in row["PersonIdentifiers"]  # multi-value
        True
    """

    def __init__(
        self,
        mapping_config: dict[str, Any],
        value_pools: dict[str, list[str]],
        *,
        seed: int | None = None,
        instances_range: tuple[int, int] = (1, 4),
    ) -> None:
        """Initialize the assembler.

        Args:
            mapping_config: Parsed YAML mapping configuration dict.
            value_pools: Pre-generated value pools keyed by source column name.
            seed: Random seed for reproducibility.
            instances_range: Min/max number of instances for ``cardinality: multiple``
                sub-shapes. Default ``(1, 4)`` produces 1–3 instances.
        """
        self._config = mapping_config
        self._pools = value_pools
        self._rng = random.Random(seed)
        self._min_instances = instances_range[0]
        self._max_instances = instances_range[1]

    def assemble_one(self) -> dict[str, str]:
        """Assemble a single flat row dict (like a CSV row).

        Returns:
            Dict mapping source column names to string values, with
            pipe-delimited multi-value fields where appropriate.
        """
        row: dict[str, str] = {}
        properties = self._config.get("properties", {})

        for _prop_name, prop_cfg in properties.items():
            cardinality = prop_cfg.get("cardinality", "single")
            fields = prop_cfg.get("fields", {})

            if cardinality == "multiple":
                num_instances = self._rng.randint(
                    self._min_instances,
                    self._max_instances - 1,
                )
                self._assemble_multiple(fields, num_instances, row)
            else:
                self._assemble_single(fields, row)

        return row

    def assemble_batch(self, count: int) -> list[dict[str, str]]:
        """Assemble multiple flat row dicts.

        Args:
            count: Number of rows to generate.

        Returns:
            List of row dicts.
        """
        return [self.assemble_one() for _ in range(count)]

    def _assemble_single(
        self,
        fields: dict[str, Any],
        row: dict[str, str],
    ) -> None:
        """Assemble field values for a single-cardinality sub-shape."""
        for field_name, field_cfg in fields.items():
            source_col = field_cfg.get("source", field_name)
            optional = field_cfg.get("optional", False)
            multi_split = field_cfg.get("multi_value_split")

            if optional and self._rng.random() < 0.15:
                # Occasionally skip optional fields
                continue

            if source_col in self._pools:
                pool = self._pools[source_col]
                if multi_split:
                    # Generate 1-3 comma-separated values
                    num = self._rng.randint(1, 3)
                    values = [self._rng.choice(pool) for _ in range(num)]
                    row[source_col] = multi_split.join(values)
                else:
                    row[source_col] = self._rng.choice(pool)

    def _assemble_multiple(
        self,
        fields: dict[str, Any],
        num_instances: int,
        row: dict[str, str],
    ) -> None:
        """Assemble field values for a multiple-cardinality sub-shape.

        Each field becomes pipe-delimited with matching positions across fields.
        E.g. if we have 3 PersonIdentification instances:
            PersonIdentifiers: "123|456|789"
            IdentificationSystems: "SSN|State|EducatorID"
        """
        # Collect per-field value lists
        field_values: dict[str, list[str]] = {}

        for field_name, field_cfg in fields.items():
            source_col = field_cfg.get("source", field_name)
            optional = field_cfg.get("optional", False)
            multi_split = field_cfg.get("multi_value_split")

            if source_col not in self._pools:
                continue

            pool = self._pools[source_col]
            values: list[str] = []

            for _ in range(num_instances):
                if optional and self._rng.random() < 0.1:
                    values.append("")
                    continue
                if multi_split:
                    num = self._rng.randint(1, 3)
                    sub_values = [self._rng.choice(pool) for _ in range(num)]
                    values.append(multi_split.join(sub_values))
                else:
                    values.append(self._rng.choice(pool))

            field_values[source_col] = values

        # Join each field's values with pipe delimiter
        for source_col, values in field_values.items():
            row[source_col] = "|".join(values)
