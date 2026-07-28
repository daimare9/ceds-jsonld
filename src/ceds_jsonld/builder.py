"""JSON-LD builder — construct JSON-LD documents from mapped data.

Uses direct dict construction (161x faster than rdflib+PyLD, proven in benchmarks).
Driven by mapping configs and shape definitions, not hand-coded per shape.
"""

from __future__ import annotations

import math
from typing import Any

from ceds_jsonld.exceptions import BuildError
from ceds_jsonld.logging import get_logger
from ceds_jsonld.registry import ShapeDefinition
from ceds_jsonld.sanitize import sanitize_iri_component, validate_base_uri

_log = get_logger(__name__)


class JSONLDBuilder:
    """Build JSON-LD documents from mapped data rows.

    Example:
        >>> builder = JSONLDBuilder(person_shape_def)
        >>> doc = builder.build_one(mapped_row)
        >>> doc["@type"]
        'Person'
        >>> len(builder.build_many([row1, row2, row3]))
        3
    """

    def __init__(self, shape_def: ShapeDefinition) -> None:
        """Initialize the builder with a shape definition.

        Args:
            shape_def: A loaded ShapeDefinition from the registry.
        """
        self._shape = shape_def
        self._config = shape_def.mapping_config
        self._id_is_uri: bool = bool(self._config.get("id_is_uri", False))

        # Validate base_uri early so malformed URIs fail at init, not per-row.
        # Skip validation when id_is_uri is set — the source supplies the full @id.
        base_uri = self._config.get("base_uri", "")
        if base_uri and not self._id_is_uri:
            try:
                validate_base_uri(base_uri)
            except ValueError as exc:
                msg = f"Shape '{shape_def.name}' has an invalid base_uri in its mapping config: {exc}"
                raise BuildError(msg) from exc

        # Pre-build static sub-shapes for performance
        self._record_status_template: dict[str, Any] | None = None
        self._data_collection_template: dict[str, Any] | None = None
        self._init_templates()
        _log.debug("builder.initialized", shape=shape_def.name)

    def build_one(self, mapped_row: dict[str, Any]) -> dict[str, Any]:
        """Build a single JSON-LD document from a mapped data row.

        Args:
            mapped_row: Output of FieldMapper.map() — structured dict with
                ``"__id__"`` and property-name keys.

        Returns:
            A complete JSON-LD document as a plain Python dict.

        Raises:
            BuildError: If the document cannot be constructed.
        """
        doc_id = mapped_row.get("__id__")
        if not doc_id:
            msg = "Mapped row is missing '__id__' — was FieldMapper.map() used?"
            raise BuildError(msg)

        if self._id_is_uri:
            # Source value is already a fully qualified URI — use verbatim.
            id_str = str(doc_id).strip()
            if "://" not in id_str and not id_str.startswith("urn:"):
                _log.warning(
                    "builder.id_is_uri_suspect",
                    value=id_str,
                    hint="id_is_uri is set but the value does not look like a URI",
                )
            at_id = id_str
        else:
            # Sanitize the ID component to prevent IRI injection
            safe_id = sanitize_iri_component(str(doc_id))
            at_id = f"{self._config['base_uri']}{safe_id}"

        doc: dict[str, Any] = {
            "@context": self._config.get("context_url", ""),
            "@id": at_id,
            "@type": self._config["type"],
        }

        for prop_name, prop_def in self._config.get("properties", {}).items():
            instances = mapped_row.get(prop_name)
            if not instances:
                continue

            if prop_def.get("type") == "named_individual":
                # Concept scheme: flatten to plain string value(s)
                values = self._flatten_named_individuals(instances, prop_def)
                if not values:
                    continue
                doc[prop_name] = values if len(values) > 1 else values[0]
            elif prop_def.get("type") in ("id_ref", "iri_ref"):
                # IRI reference (sh:nodeKind sh:IRI): emit {"@id": value} with NO @type
                refs = self._build_id_refs(instances, prop_def)
                if not refs:
                    continue
                doc[prop_name] = refs if len(refs) > 1 else refs[0]
            else:
                nodes = self._build_sub_nodes(instances, prop_def)
                if not nodes:
                    continue
                # Single instance → unwrap from array
                doc[prop_name] = nodes if len(nodes) > 1 else nodes[0]

        return doc

    def build_many(self, mapped_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build JSON-LD documents for a batch of mapped rows.

        Args:
            mapped_rows: List of mapped data dicts.

        Returns:
            List of JSON-LD documents.
        """
        return [self.build_one(row) for row in mapped_rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_templates(self) -> None:
        """Pre-build record status and data collection templates."""
        rs_defaults = self._config.get("record_status_defaults")
        if rs_defaults:
            self._record_status_template = self._build_record_status_template(rs_defaults)

        dc_defaults = self._config.get("data_collection_defaults")
        if dc_defaults:
            self._data_collection_template = self._build_data_collection_template(dc_defaults)

    @staticmethod
    def _flatten_named_individuals(
        instances: list[dict[str, Any]],
        prop_def: dict[str, Any],
    ) -> list[str]:
        """Extract plain string values from named-individual instances.

        Named-individual / concept-scheme properties carry a single
        concept-code value that should appear as a plain string in JSON-LD,
        not wrapped in a typed sub-node object.
        """
        values: list[str] = []
        fields = prop_def.get("fields", {})
        for instance in instances:
            for _fk, fdef in fields.items():
                target = fdef.get("target", _fk)
                if target in instance and instance[target] is not None:
                    values.append(str(instance[target]))
                    break  # one value per instance
        return values

    @staticmethod
    def _build_id_refs(
        instances: list[dict[str, Any]],
        prop_def: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build ``@id``-only reference nodes for ``sh:nodeKind sh:IRI`` properties.

        Object-property references (e.g. ``OrganizationRelationship →
        hasOrganizationRelationshipSubject``) must serialize as the node-object
        form ``{"@id": <value>}`` with **no** ``@type`` key.  The source value is
        an absolute IRI that maps to the ``@id`` target field.  Supports both
        single and multiple cardinality (an array of reference nodes).
        """
        refs: list[dict[str, Any]] = []
        fields = prop_def.get("fields", {})
        for instance in instances:
            # Prefer the field explicitly targeting @id; fall back to first
            # populated field value.
            value: Any = instance.get("@id")
            if value is None:
                for _fk, fdef in fields.items():
                    target = fdef.get("target", _fk)
                    if target in instance and instance[target] is not None:
                        value = instance[target]
                        break
            if value is None:
                continue
            refs.append({"@id": str(value)})
        return refs

    def _build_sub_nodes(
        self,
        instances: list[dict[str, Any]],
        prop_def: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build typed sub-shape nodes from mapped instances.

        Supports an optional two-level wrapper pattern via ``wrapper_field`` and
        ``inner_type``.  When both keys are present the mapped fields are placed
        on an inner node (``@type = inner_type``) which is then nested under
        ``wrapper_field`` inside an outer node (``@type = type``).  This
        satisfies SHACL shapes that require an intermediate container node, e.g.
        ``Organization → hasLocation → Location → hasLocationAddress →
        LocationAddress``.

        YAML example::

            hasLocation:
              source_table: addresses
              type: Location          # outer node @type
              wrapper_field: hasLocationAddress
              inner_type: LocationAddress   # inner node @type
              fields:
                street:
                  source: AddressStreetNumberAndName
                  target: AddressStreetNumberAndName
                  optional: true
        """
        wrapper_field: str | None = prop_def.get("wrapper_field")
        inner_type: str | None = prop_def.get("inner_type")
        use_wrapper = bool(wrapper_field and inner_type)

        nodes: list[dict[str, Any]] = []

        for instance in instances:
            # When wrapper_field + inner_type are set, fields are placed on the
            # inner node; the outer node only carries @type and wrapper_field.
            if use_wrapper:
                inner_node: dict[str, Any] = {"@type": inner_type}
                field_target = inner_node
            else:
                field_target = {}

            node: dict[str, Any] = {"@type": prop_def["type"]}

            # Add mapped fields with optional typed literals
            for _field_key, field_def in prop_def.get("fields", {}).items():
                target = field_def.get("target", _field_key)
                if target not in instance:
                    continue

                value = instance[target]
                datatype = field_def.get("datatype")

                if datatype:
                    typed = self._typed_literal(value, datatype)
                    if typed is not None:
                        field_target[target] = typed
                else:
                    # Plain value — unwrap single-element lists
                    if isinstance(value, list):
                        if not value:
                            continue
                        field_target[target] = value if len(value) > 1 else value[0]
                    else:
                        field_target[target] = value

            # Recursively build nested sub-properties (on the field target node)
            for nested_name, nested_def in prop_def.get("properties", {}).items():
                nested_instances = instance.get(nested_name)
                if not nested_instances:
                    continue
                nested_nodes = self._build_sub_nodes(nested_instances, nested_def)
                if not nested_nodes:
                    continue
                field_target[nested_name] = nested_nodes if len(nested_nodes) > 1 else nested_nodes[0]

            if use_wrapper:
                # Only emit the outer node when the inner node has real content
                # beyond just its @type.
                if len(inner_node) > 1:
                    node[wrapper_field] = inner_node  # type: ignore[index]
                    nodes.append(node)
            else:
                # Flat mode: merge field_target into node
                node.update(field_target)

                # Inject record status
                if prop_def.get("include_record_status") and self._record_status_template:
                    node["hasRecordStatus"] = self._copy_template(self._record_status_template)

                # Inject data collection
                if prop_def.get("include_data_collection") and self._data_collection_template:
                    node["hasDataCollection"] = self._copy_template(self._data_collection_template)

                nodes.append(node)

        return nodes

    @staticmethod
    def _typed_literal(value: Any, datatype: str) -> dict[str, str] | list | str | None:
        """Wrap a value as a JSON-LD typed literal.

        Args:
            value: The value or list of values.
            datatype: The XSD datatype (e.g. "xsd:date").

        Returns:
            ``{"@type": datatype, "@value": value}``, a list of such dicts,
            a plain string (when *datatype* is ``"xsd:string"``),
            or ``None`` if the value is ``None`` or non-finite.
        """
        if value is None:
            return None
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        is_string = datatype in {"xsd:string", "named_individual"}
        if isinstance(value, list):
            clean: list = [
                str(v) if is_string else {"@type": datatype, "@value": str(v)}
                for v in value
                if v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
            ]
            return clean or None
        if is_string:
            return str(value)
        return {"@type": datatype, "@value": str(value)}

    @staticmethod
    def _build_record_status_template(defaults: dict[str, Any]) -> dict[str, Any]:
        """Build a record status dict from defaults config."""
        node: dict[str, Any] = {"@type": defaults.get("type", "RecordStatus")}

        for key, val_def in defaults.items():
            if key == "type":
                continue
            if isinstance(val_def, dict):
                if "value_id" in val_def:
                    node[key] = {"@id": val_def["value_id"]}
                elif "value" in val_def:
                    datatype = val_def.get("datatype")
                    if datatype:
                        node[key] = {"@type": datatype, "@value": val_def["value"]}
                    else:
                        node[key] = val_def["value"]

        return node

    @staticmethod
    def _build_data_collection_template(defaults: dict[str, Any]) -> dict[str, Any]:
        """Build a data collection dict from defaults config."""
        node: dict[str, Any] = {}
        if "value_id" in defaults:
            node["@id"] = defaults["value_id"]
        node["@type"] = defaults.get("type", "DataCollection")
        return node

    @staticmethod
    def _copy_template(template: dict[str, Any]) -> dict[str, Any]:
        """Shallow-copy a template dict (one level of nesting).

        Faster than copy.deepcopy for our fixed-structure templates.
        """
        result: dict[str, Any] = {}
        for k, v in template.items():
            if isinstance(v, dict):
                result[k] = dict(v)
            else:
                result[k] = v
        return result
