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
