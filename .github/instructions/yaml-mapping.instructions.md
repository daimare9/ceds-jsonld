---
applyTo: "**/*.yaml,**/*.yml"
---
# YAML Mapping Configuration Instructions — ceds-jsonld

## Purpose

Each SHACL shape has a companion `_mapping.yaml` file that tells the engine how to map source data fields to JSON-LD properties. SHACL defines *what is valid*; YAML defines *where data comes from*.

## Canonical Structure

```yaml
# Shape metadata
shape: PersonShape                    # References the sh:NodeShape name
context_url: "https://cepi-dev.state.mi.us/ontology/context-person.json"
context_file: person_context.json     # Local context file path (relative to shape folder)
base_uri: "cepi:person/"              # URI prefix for @id values
id_source: PersonIdentifiers          # Source field that provides the document ID
id_transform: first_pipe_split        # Transform to extract ID from multi-value field
id_is_uri: false                      # When true, id_source already contains a fully qualified URI
                                      # (base_uri is ignored and the value is used verbatim as @id)

# Top-level document type
type: Person                          # JSON-LD @type value

# Property mappings (one entry per sub-shape)
properties:
  hasPropertyName:                    # JSON-LD property name (matches context term)
    type: SubShapeName                # @type for the nested object
    cardinality: single|multiple      # single = one object, multiple = array of objects
    split_on: "|"                     # Delimiter for multiple instances (if cardinality=multiple)
    include_record_status: true       # Auto-inject hasRecordStatus sub-shape
    include_data_collection: true     # Auto-inject hasDataCollection sub-shape
    fields:
      TargetField:                    # JSON-LD property name in the context
        source: SourceColumn          # Column name in the source data
        target: TargetField           # JSON-LD term (usually same as key)
        datatype: string|xsd:date|xsd:dateTime|xsd:token  # Type hint
        transform: transform_name     # Optional named transform function
        optional: true|false          # Default: false (required)
        multi_value_split: ","        # Split this field into an array within one instance

# Default sub-shapes (appended to every sub-shape with include_X: true)
record_status_defaults:
  type: RecordStatus
  RecordStartDateTime:
    value: "1900-01-01T00:00:00"
    datatype: xsd:dateTime
  RecordEndDateTime:
    value: "9999-12-31T00:00:00"
    datatype: xsd:dateTime

data_collection_defaults:
  type: DataCollection
  value_id: "http://example.org/dataCollection/default"
```

## Rules

### MUST Follow
1. Every field in `fields:` must have a `source` (column name in source data) and a `target` (JSON-LD term).
2. `cardinality: multiple` requires `split_on` to specify how pipe-delimited groups are separated.
3. `datatype` should match the `sh:datatype` from the corresponding SHACL PropertyShape.
4. `transform` names must reference registered transform functions in the engine.
5. `optional: true` fields are silently skipped if the source value is None or empty string.
6. Required fields (default) cause a `MappingError` if the source value is missing.
7. `id_is_uri: true` means the `id_source` field already contains a fully qualified URI. When set, `base_uri` is ignored and the value is used verbatim as `@id` (no sanitization or prefixing). A warning is logged if the value doesn't look like a URI.

### Naming Conventions
- Property keys under `properties:` match the JSON-LD context term (e.g., `hasPersonBirth`, `hasPersonName`).
- Field keys under `fields:` match the JSON-LD output field name.
- `source:` values match the raw source data column names exactly (case-sensitive).

### Multi-Value Handling
- **Multiple instances of a sub-shape** (e.g., 3 PersonIdentification records): Use `cardinality: multiple` + `split_on: "|"`. The source fields are pipe-delimited with matching positions.
- **Multiple values within one instance** (e.g., 2 races in one PersonDemographicRace): Use `multi_value_split: ","` on the specific field.

Example source data for Person with 3 identifications:
```
PersonIdentifiers: "123456789|EDU001|MI999"
IdentificationSystems: "SSN|EducatorIdentificationNumber|State|CEPI"
```

### Multi-Table / Relational Sources (Star Schema)

When source data lives in separate relational tables (e.g., multiple Parquet files), use
`source_table` instead of `split_on`. The `source_table` value must match a key in the
`satellites` dict passed to `RelationalAdapter`.

```yaml
properties:
  hasIdentification:
    type: Identification
    cardinality: multiple
    source_table: identifications   # matches satellites={"identifications": adapter}
    fields:
      IdentifierValue:
        source: id_value            # column in the satellite table
        target: IdentifierValue
      IdentifierType:
        source: id_type
        target: IdentifierType
        optional: true
```

Python wiring:
```python
from ceds_jsonld import RelationalAdapter, ParquetAdapter

adapter = RelationalAdapter(
    primary=ParquetAdapter("students.parquet"),
    join_key="student_id",
    satellites={
        "identifications": ParquetAdapter("student_ids.parquet"),
        "races": ParquetAdapter("student_races.parquet"),
    },
)
```

**Rules for `source_table`:**
- `source_table` and `split_on` are mutually exclusive. `source_table` takes precedence when both are present.
- Each satellite row becomes one instance of the sub-shape. `cardinality` is effectively always `multiple`.
- Fields under a `source_table` property reference **satellite table columns**, not primary table columns.
- If no satellite rows exist for a primary entity, the property is omitted from the JSON-LD output — not an error.
- When used with a flat (non-relational) adapter, the property is silently omitted (graceful degradation).
- `satellite_join_key` on `RelationalAdapter` allows different FK column names in primary vs. satellite tables.

### Intermediate Container Nodes (`wrapper_field` / `inner_type`)

Some SHACL shapes require an intermediate container node between the subject property and the actual
data node.  For example `Organization → hasLocation → Location → hasLocationAddress → LocationAddress`
cannot be expressed with a single `type:` key.  Use `wrapper_field` and `inner_type` together:

```yaml
hasLocation:
  source_table: addresses     # or use cardinality: multiple / split_on for flat sources
  type: Location              # @type of the OUTER (container) node
  wrapper_field: hasLocationAddress   # property name on the outer node
  inner_type: LocationAddress # @type of the INNER (data) node
  fields:
    city:
      source: AddressCity
      target: AddressCity
      optional: true
    street:
      source: AddressStreetNumberAndName
      target: AddressStreetNumberAndName
      optional: true
```

This produces:

```json
"hasLocation": {
  "@type": "Location",
  "hasLocationAddress": {
    "@type": "LocationAddress",
    "AddressCity": "GRAND RAPIDS",
    "AddressStreetNumberAndName": "100 Main St"
  }
}
```

**Rules for `wrapper_field` / `inner_type`:**
- Both keys must be present together; using only one is a configuration error.
- All `fields` are placed on the **inner** node (`inner_type`), never on the outer node (`type`).
- If all inner fields are optional and all are missing for a row, that row is suppressed (no empty outer node emitted).
- `properties:` (recursive nested sub-shapes) are also placed on the inner node when a wrapper is active.
- `include_record_status` and `include_data_collection` are only injected in the **non-wrapper** (flat) path;
  for wrapper shapes, add those fields directly in `fields:` if required.
- Works with both `source_table` (relational) and flat pipe-delimited (`cardinality: multiple`) sources.

### Transforms
Built-in transforms are referenced by name:
- `sex_prefix` — Adds "Sex_" prefix (e.g., "Female" → "Sex_Female")
- `race_prefix` — Adds "RaceAndEthnicity_" prefix
- `first_pipe_split` — Takes the first value from a pipe-delimited string
- `date_format` — Normalizes date strings to ISO 8601
- `int_clean` — Strips non-numeric characters
- `code_list_lookup` — Maps human-readable values to named individual URIs

Custom transforms can be registered at runtime.

## Validation

When loading a mapping YAML:
1. Validate that all required top-level keys are present (`shape`, `type`, `properties`).
2. Validate that each property has `type`, `cardinality`, and `fields`.
3. Validate that field `datatype` values match known XSD types.
4. Validate that `transform` names reference registered transforms.
5. If a SHACL introspector is available, cross-validate against the SHACL shape: warn on missing required properties, unknown properties.

## Testing Mapping Configs

Every mapping YAML should have a corresponding test that:
1. Loads the YAML and the sample CSV
2. Maps every row successfully (no MappingErrors)
3. Produces output that matches the golden file
4. Handles all edge cases in the sample data (missing optionals, multi-value variations)
