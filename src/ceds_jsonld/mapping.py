"""Field mapper — apply declarative mapping configs to raw data rows.

The FieldMapper reads a mapping YAML config and transforms raw source dicts
(e.g. from CSV rows) into structured dicts ready for JSONLDBuilder.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from typing import Any

from ceds_jsonld.exceptions import MappingError
from ceds_jsonld.sanitize import sanitize_string_value, validate_base_uri
from ceds_jsonld.transforms import get_transform


class FieldMapper:
    """Map raw data rows to structured dicts using a YAML mapping config.

    Example:
        >>> mapper = FieldMapper(shape_def.mapping_config)
        >>> mapped = mapper.map({"FirstName": "Jane", "LastName": "Doe", ...})
        >>> mapped["__id__"]
        '987654321'
        >>> mapped["hasPersonName"]
        [{"FirstName": "Jane", "LastOrSurname": "Doe"}]
    """

    def __init__(
        self,
        mapping_config: dict[str, Any],
        custom_transforms: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        """Initialize the mapper with a parsed mapping config.

        Args:
            mapping_config: Parsed YAML mapping configuration dict.
            custom_transforms: Optional user-defined transforms keyed by name.
        """
        self._config = mapping_config
        self._custom_transforms = custom_transforms

        # Validate base_uri early so malformed URIs are caught even when
        # FieldMapper is used without Builder (e.g. via compose()).
        # Skip validation when id_is_uri — the source supplies complete URIs.
        id_is_uri = mapping_config.get("id_is_uri", False)
        base_uri = mapping_config.get("base_uri", "")
        if base_uri and not id_is_uri:
            try:
                validate_base_uri(base_uri)
            except ValueError as exc:
                msg = (
                    f"Mapping config has an invalid base_uri: {exc}. "
                    f"The base_uri must end with '/' or '#' to separate the "
                    f"namespace from the identifier (e.g. 'cepi:person/')."
                )
                raise MappingError(msg) from exc

    # ------------------------------------------------------------------
    # Mapping flexibility — overrides & composition
    # ------------------------------------------------------------------

    def with_overrides(
        self,
        *,
        source_overrides: dict[str, dict[str, str]] | None = None,
        transform_overrides: dict[str, dict[str, str]] | None = None,
        id_source: str | None = None,
        id_transform: str | None = None,
    ) -> FieldMapper:
        """Create a new FieldMapper with selective overrides applied.

        Returns a new mapper instance — the original is not mutated.

        Args:
            source_overrides: Dict mapping property name → field name → new source column.
                Example: ``{"hasPersonName": {"FirstName": "FIRST_NM"}}``
            transform_overrides: Dict mapping property name → field name → new transform.
                Example: ``{"hasPersonSexGender": {"hasSex": "my_custom_fn"}}``
            id_source: Override the ``id_source`` field.
            id_transform: Override the ``id_transform`` field.

        Returns:
            A new FieldMapper with the overrides applied.
        """
        new_config = copy.deepcopy(self._config)

        if id_source is not None:
            new_config["id_source"] = id_source
        if id_transform is not None:
            new_config["id_transform"] = id_transform

        if source_overrides:
            for prop_name, field_overrides in source_overrides.items():
                prop = new_config.get("properties", {}).get(prop_name)
                if prop is None:
                    continue
                for field_name, new_source in field_overrides.items():
                    for _key, field_def in prop.get("fields", {}).items():
                        if field_def.get("target") == field_name or _key == field_name:
                            field_def["source"] = new_source

        if transform_overrides:
            for prop_name, field_overrides in transform_overrides.items():
                prop = new_config.get("properties", {}).get(prop_name)
                if prop is None:
                    continue
                for field_name, new_transform in field_overrides.items():
                    for _key, field_def in prop.get("fields", {}).items():
                        if field_def.get("target") == field_name or _key == field_name:
                            field_def["transform"] = new_transform

        return FieldMapper(new_config, self._custom_transforms)

    @classmethod
    def compose(
        cls,
        base_config: dict[str, Any],
        overlay_config: dict[str, Any],
        custom_transforms: dict[str, Callable[..., Any]] | None = None,
    ) -> FieldMapper:
        """Create a FieldMapper by deep-merging a base config with an overlay.

        The overlay selectively overrides fields in the base. Useful for
        per-district or per-source customization on top of a shared base mapping.

        Merge rules:
        - Top-level scalar keys in overlay replace base.
        - ``properties`` are merged per-property: overlay properties replace base
          properties of the same name; new properties are added.
        - Within a property, ``fields`` are merged per-field (same logic).
        - ``record_status_defaults`` and ``data_collection_defaults`` are deep-merged.

        Args:
            base_config: The base mapping config dict.
            overlay_config: The overlay mapping config dict.
            custom_transforms: Optional custom transforms.

        Returns:
            A new FieldMapper with the merged config.
        """
        merged = copy.deepcopy(base_config)

        for key, value in overlay_config.items():
            if key == "properties":
                base_props = merged.setdefault("properties", {})
                for prop_name, prop_def in value.items():
                    if prop_name in base_props:
                        # Merge fields within property
                        base_prop = base_props[prop_name]
                        for prop_key, prop_val in prop_def.items():
                            if prop_key == "fields" and "fields" in base_prop:
                                # Deep-merge per field: overlay keys
                                # override base keys, but unmentioned
                                # base keys (datatype, optional, target)
                                # are preserved.
                                for field_name, field_def in prop_val.items():
                                    if field_name in base_prop["fields"]:
                                        base_prop["fields"][field_name].update(field_def)
                                    else:
                                        base_prop["fields"][field_name] = copy.deepcopy(field_def)
                            else:
                                base_prop[prop_key] = prop_val
                    else:
                        base_props[prop_name] = copy.deepcopy(prop_def)
            elif key in ("record_status_defaults", "data_collection_defaults"):
                if key in merged and isinstance(merged[key], dict):
                    merged[key].update(value)
                else:
                    merged[key] = copy.deepcopy(value)
            else:
                merged[key] = value

        return cls(merged, custom_transforms)

    @property
    def config(self) -> dict[str, Any]:
        """Return the current mapping config (read-only copy)."""
        return copy.deepcopy(self._config)

    def map(self, raw_row: dict[str, Any]) -> dict[str, Any]:
        """Map a single raw data row to a structured dict for the builder.

        Args:
            raw_row: Dict of source field names to values (e.g. a CSV row).

        Returns:
            Structured dict with ``"__id__"`` and property-name keys, each
            mapping to a list of instance dicts.

        Raises:
            MappingError: If a required field is missing or a transform fails.
        """
        result: dict[str, Any] = {}

        # Extract document ID
        id_source = self._config["id_source"]
        id_raw = raw_row.get(id_source)
        if self._is_empty(id_raw):
            msg = f"ID source field '{id_source}' is missing or empty in row"
            raise MappingError(msg)
        self._ensure_scalar(id_raw, id_source, "@id")
        # Reject non-string falsy values that are meaningless as document IDs
        # (0, 0.0, False).  These pass _is_empty because they are legitimate
        # *field* values, but they are never valid identifiers.
        if not isinstance(id_raw, str) and not id_raw:
            msg = (
                f"ID source field '{id_source}' has a falsy non-string value "
                f"{id_raw!r} which is not a valid document identifier"
            )
            raise MappingError(msg)
        id_value = sanitize_string_value(str(id_raw))

        id_transform_name = self._config.get("id_transform")
        if id_transform_name:
            transform_fn = get_transform(id_transform_name, self._custom_transforms)
            id_value = transform_fn(id_value)
        result["__id__"] = id_value

        # Map each property
        for prop_name, prop_def in self._config.get("properties", {}).items():
            instances = self._map_property(raw_row, prop_name, prop_def)
            if instances:
                result[prop_name] = instances

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _map_property(
        self,
        raw_row: dict[str, Any],
        prop_name: str,
        prop_def: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Map a single property, respecting cardinality and source_table."""
        # Satellite table mode: delegate to relational mapper when source_table
        # is declared — takes precedence over cardinality/split_on.
        if "source_table" in prop_def:
            return self._map_from_table(raw_row, prop_name, prop_def)
        cardinality = prop_def.get("cardinality", "single")

        if cardinality == "multiple":
            return self._map_multiple(raw_row, prop_name, prop_def)
        return self._map_single(raw_row, prop_name, prop_def)

    def _map_single(
        self,
        raw_row: dict[str, Any],
        prop_name: str,
        prop_def: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Map a single-cardinality property (one instance)."""
        fields = prop_def.get("fields", {})
        instance: dict[str, Any] = {}

        for _field_key, field_def in fields.items():
            target = field_def.get("target", _field_key)
            source = field_def["source"]
            value = raw_row.get(source)

            if self._is_empty(value):
                if not field_def.get("optional", False):
                    msg = f"Required field '{source}' is missing or empty in row for property '{prop_name}'"
                    raise MappingError(msg)
                continue

            self._ensure_scalar(value, source, prop_name)
            value = sanitize_string_value(str(value))
            transform_name = field_def.get("transform")
            if transform_name:
                transform_fn = get_transform(transform_name, self._custom_transforms)
                try:
                    raw_result = transform_fn(value)
                except Exception as exc:
                    msg = (
                        f"Transform '{transform_name}' raised {type(exc).__name__} on field "
                        f"'{source}' in property '{prop_name}': {exc}"
                    )
                    raise MappingError(msg) from exc
                value = self._validate_transform_result(
                    raw_result,
                    value,
                    transform_name,
                    source,
                    prop_name,
                )

            if value is None:
                # Transform returned None — check if this is a required field.
                # None is acceptable for optional fields (signals "skip"),
                # but required fields must not be silently dropped.
                if not field_def.get("optional", False):
                    msg = (
                        f"Transform '{transform_name or '(none)'}' on required field "
                        f"'{source}' in property '{prop_name}' produced None. "
                        f"Required fields cannot be nullified by transforms. "
                        f"Mark the field as 'optional: true' in the mapping config "
                        f"if this behaviour is intentional."
                    )
                    raise MappingError(msg)
            else:
                instance[target] = value

        # Recursively map nested properties (e.g. hasLocationAddress inside Location)
        for nested_name, nested_def in prop_def.get("properties", {}).items():
            nested_instances = self._map_property(raw_row, nested_name, nested_def)
            if nested_instances:
                instance[nested_name] = nested_instances

        return [instance] if instance else []

    def _map_multiple(
        self,
        raw_row: dict[str, Any],
        prop_name: str,
        prop_def: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Map a multiple-cardinality property (pipe-delimited instances)."""
        split_on = prop_def.get("split_on", "|")
        fields = prop_def.get("fields", {})

        # Determine instance count from the first field's source column
        first_field_def = next(iter(fields.values()))
        first_source = first_field_def["source"]
        first_raw = raw_row.get(first_source)

        if self._is_empty(first_raw):
            # All fields missing — skip this property
            if first_field_def.get("optional", False):
                return []
            return []

        self._ensure_scalar(first_raw, first_source, prop_name)
        parts = str(first_raw).split(split_on)
        num_instances = len(parts)

        instances: list[dict[str, Any]] = []
        for i in range(num_instances):
            # Skip empty pipe segments entirely (#26)
            primary_segment = parts[i].strip()
            if not primary_segment:
                continue

            instance: dict[str, Any] = {}

            for _field_key, field_def in fields.items():
                target = field_def.get("target", _field_key)
                source = field_def["source"]
                raw_value = raw_row.get(source)

                if self._is_empty(raw_value):
                    if not field_def.get("optional", False):
                        continue
                    continue

                self._ensure_scalar(raw_value, source, prop_name)
                field_parts = str(raw_value).split(split_on)

                # Fix #29: Use None for out-of-range segments instead of
                # forward-filling.  Log a warning when pipe counts differ.
                if i < len(field_parts):
                    segment = field_parts[i].strip()
                else:
                    from ceds_jsonld.logging import get_logger

                    _log = get_logger(__name__)
                    _log.warning(
                        "mapper.pipe_count_mismatch",
                        property=prop_name,
                        field=source,
                        expected=num_instances,
                        actual=len(field_parts),
                    )
                    segment = ""

                if not segment:
                    # Empty segment — treat as missing
                    continue

                value = sanitize_string_value(segment)

                # Handle multi_value_split within a single instance
                multi_split = field_def.get("multi_value_split")
                if multi_split:
                    sub_values = [v.strip() for v in value.split(multi_split) if v.strip()]
                    transform_name = field_def.get("transform")
                    if transform_name:
                        transform_fn = get_transform(transform_name, self._custom_transforms)
                        transformed = []
                        for v in sub_values:
                            try:
                                raw_result = transform_fn(v)
                            except Exception as exc:
                                msg = (
                                    f"Transform '{transform_name}' raised {type(exc).__name__} on field "
                                    f"'{source}' in property '{prop_name}': {exc}"
                                )
                                raise MappingError(msg) from exc
                            validated = self._validate_transform_result(
                                raw_result,
                                v,
                                transform_name,
                                source,
                                prop_name,
                            )
                            if validated is not None:
                                transformed.append(validated)
                            elif not field_def.get("optional", False):
                                msg = (
                                    f"Transform '{transform_name}' on required field "
                                    f"'{source}' in property '{prop_name}' produced None. "
                                    f"Required fields cannot be nullified by transforms."
                                )
                                raise MappingError(msg)
                        sub_values = transformed
                    # Store as list (builder decides single vs array)
                    if sub_values:
                        instance[target] = sub_values
                else:
                    transform_name = field_def.get("transform")
                    if transform_name:
                        transform_fn = get_transform(transform_name, self._custom_transforms)
                        try:
                            raw_result = transform_fn(value)
                        except Exception as exc:
                            msg = (
                                f"Transform '{transform_name}' raised {type(exc).__name__} on field "
                                f"'{source}' in property '{prop_name}': {exc}"
                            )
                            raise MappingError(msg) from exc
                        xform_result = self._validate_transform_result(
                            raw_result,
                            value,
                            transform_name,
                            source,
                            prop_name,
                        )
                        if xform_result is None:
                            if not field_def.get("optional", False):
                                msg = (
                                    f"Transform '{transform_name}' on required field "
                                    f"'{source}' in property '{prop_name}' produced None. "
                                    f"Required fields cannot be nullified by transforms."
                                )
                                raise MappingError(msg)
                            continue  # optional field — transform says skip
                        value = xform_result
                    if value is not None:
                        instance[target] = value

            # Recursively map nested properties within each instance
            for nested_name, nested_def in prop_def.get("properties", {}).items():
                nested_instances = self._map_property(raw_row, nested_name, nested_def)
                if nested_instances:
                    instance[nested_name] = nested_instances

            if instance:
                instances.append(instance)

        return instances

    @staticmethod
    def _validate_transform_result(
        result: Any,
        original: str,
        transform_name: str,
        field_name: str,
        prop_name: str,
    ) -> str | None:
        """Validate and coerce the result of a transform function.

        Ensures transforms do not silently produce ``None``, non-string types,
        or other invalid outputs that would bypass downstream validation.

        Args:
            result: The value returned by the transform.
            original: The original pre-transform value (for error messages).
            transform_name: Name of the transform (for error messages).
            field_name: Source field name (for error messages).
            prop_name: Property name (for error messages).

        Returns:
            A validated string, or ``None`` if the transform intentionally
            signals "skip this value" (e.g. empty-input guards in prefix
            transforms).

        Raises:
            MappingError: If the transform returns an invalid type (dict, list,
                bool, non-finite float).
        """
        # None means "skip this value" — transforms like sex_prefix/race_prefix
        # return None for empty inputs to signal the field should be omitted.
        if result is None:
            return None

        # Reject complex / invalid types the same way _ensure_scalar does
        if isinstance(result, dict):
            msg = (
                f"Transform '{transform_name}' on field '{field_name}' in property "
                f"'{prop_name}' returned a dict. Transforms must return str or None. "
                f"Original value: {original!r}, got: {result!r}"
            )
            raise MappingError(msg)
        if isinstance(result, (list, tuple, set, frozenset)):
            msg = (
                f"Transform '{transform_name}' on field '{field_name}' in property "
                f"'{prop_name}' returned a sequence. Transforms must return str or None. "
                f"Original value: {original!r}, got: {result!r}"
            )
            raise MappingError(msg)
        if isinstance(result, bool):
            msg = (
                f"Transform '{transform_name}' on field '{field_name}' in property "
                f"'{prop_name}' returned a boolean. Transforms must return str or None. "
                f"Original value: {original!r}, got: {result!r}"
            )
            raise MappingError(msg)

        # Coerce non-string scalars (int, float) to str with a warning
        if not isinstance(result, str):
            from ceds_jsonld.logging import get_logger

            _log = get_logger(__name__)
            _log.warning(
                "mapper.transform_type_coerced",
                transform=transform_name,
                field=field_name,
                property=prop_name,
                expected_type="str",
                actual_type=type(result).__name__,
                value=result,
            )
            return str(result)

        return result

    @staticmethod
    def _ensure_scalar(value: Any, field_name: str, prop_name: str) -> Any:
        """Raise MappingError if value is a complex type (dict/list).

        Fields in CEDS mapping configs expect scalar values (str, int, float,
        bool).  A nested dict or list indicates a structural mismatch between
        the source data and the mapping — e.g. an API response with nested
        objects fed into a flat mapping.

        Args:
            value: The raw value from the source row.
            field_name: The source field name (for error message).
            prop_name: The property name (for error message).

        Returns:
            The value unchanged if it is a scalar.

        Raises:
            MappingError: If the value is a dict or list.
        """
        if isinstance(value, dict):
            msg = (
                f"Field '{field_name}' in property '{prop_name}' contains a nested dict "
                f"where a scalar value was expected. Got: {value!r}. "
                f"Use a custom transform or flatten the source data before mapping."
            )
            raise MappingError(msg)
        if isinstance(value, (list, tuple, set, frozenset)):
            msg = (
                f"Field '{field_name}' in property '{prop_name}' contains a list/sequence "
                f"where a scalar value was expected. Got: {value!r}. "
                f"Use a custom transform or flatten the source data before mapping."
            )
            raise MappingError(msg)
        if isinstance(value, bool):
            msg = (
                f"Field '{field_name}' in property '{prop_name}' contains a boolean "
                f"where a scalar string/number was expected. Got: {value!r}. "
                f"Boolean-to-string coercion is almost always a bug in upstream data. "
                f"Use a custom transform to convert booleans to the expected string value."
            )
            raise MappingError(msg)
        if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
            msg = (
                f"Field '{field_name}' in property '{prop_name}' contains a non-finite float "
                f"({value!r}) where a valid scalar was expected. "
                f"NaN and Infinity values are not valid for any CEDS field. "
                f"Clean the source data or use a custom transform to handle missing values."
            )
            raise MappingError(msg)
        return value

    def _map_from_table(
        self,
        raw_row: dict[str, Any],
        prop_name: str,
        prop_def: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Map a property from satellite rows injected by RelationalAdapter.

        Each satellite row in ``raw_row["__related__"][source_table]`` becomes
        one instance of the sub-shape, using the same field-mapping logic as
        ``_map_single`` but applied per satellite row rather than per
        pipe-delimited segment.

        Args:
            raw_row: The enriched primary row from RelationalAdapter, which
                carries a ``__related__`` key with satellite data.
            prop_name: YAML property name (used in error messages).
            prop_def: The property definition dict from the mapping config.

        Returns:
            List of mapped instance dicts, one per satellite row. Returns an
            empty list when no satellite rows exist for this entity — the
            property is then omitted from the JSON-LD output. Also returns
            an empty list when called with a non-relational (flat) row,
            ensuring backwards-compatible graceful degradation.
        """
        from ceds_jsonld.adapters.relational_adapter import RELATED_KEY

        source_table = prop_def["source_table"]
        related = raw_row.get(RELATED_KEY)
        if not related or source_table not in related:
            # Flat adapter or table not registered — silently skip.
            return []

        satellite_rows: list[dict[str, Any]] = related[source_table]
        if not satellite_rows:
            return []

        fields = prop_def.get("fields", {})
        instances: list[dict[str, Any]] = []

        for sat_row in satellite_rows:
            instance: dict[str, Any] = {}
            skip_instance = False

            for _field_key, field_def in fields.items():
                target = field_def.get("target", _field_key)
                source = field_def["source"]
                value = sat_row.get(source)

                if self._is_empty(value):
                    if not field_def.get("optional", False):
                        from ceds_jsonld.logging import get_logger

                        _log = get_logger(__name__)
                        _log.warning(
                            "mapper.satellite_missing_required",
                            property=prop_name,
                            field=source,
                            table=source_table,
                        )
                        skip_instance = True
                        break
                    continue

                self._ensure_scalar(value, source, prop_name)
                value = sanitize_string_value(str(value))

                transform_name = field_def.get("transform")
                if transform_name:
                    transform_fn = get_transform(transform_name, self._custom_transforms)
                    try:
                        raw_result = transform_fn(value)
                    except Exception as exc:
                        msg = (
                            f"Transform '{transform_name}' raised {type(exc).__name__} "
                            f"on field '{source}' in satellite table '{source_table}' "
                            f"for property '{prop_name}': {exc}"
                        )
                        raise MappingError(msg) from exc
                    value = self._validate_transform_result(raw_result, value, transform_name, source, prop_name)

                if value is None:
                    if not field_def.get("optional", False):
                        msg = (
                            f"Transform on required field '{source}' in satellite table "
                            f"'{source_table}' for property '{prop_name}' produced None. "
                            f"Mark the field as 'optional: true' if this is intentional."
                        )
                        raise MappingError(msg)
                    continue

                # Handle multi_value_split within a satellite field
                multi_split = field_def.get("multi_value_split")
                if multi_split:
                    sub_values = [v.strip() for v in value.split(multi_split) if v.strip()]
                    if sub_values:
                        instance[target] = sub_values
                else:
                    instance[target] = value

            if not skip_instance and instance:
                instances.append(instance)

        return instances

    @staticmethod
    def _is_empty(value: Any) -> bool:
        """Check if a value is effectively empty.

        Catches ``None``, empty/whitespace-only strings, ``float('nan')``,
        and empty collections (``[]``, ``{}``, ``()``).  Numeric zero and
        ``False`` are **not** considered empty here because they can be
        legitimate field values — ID-specific rejection is handled
        separately in :meth:`map`.
        """
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        # Empty collections / sequences
        if isinstance(value, (list, tuple, set, frozenset, dict)) and not value:
            return True
        # Handle pandas NaN
        try:
            import math

            if isinstance(value, float) and math.isnan(value):
                return True
        except (TypeError, ValueError):
            pass
        return False
