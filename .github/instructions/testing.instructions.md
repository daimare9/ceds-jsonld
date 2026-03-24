---
applyTo: "tests/**/*.py,**/test_*.py,**/*_test.py"
---
# Testing Protocol — ceds-jsonld

## Testing is Mandatory

Every code change MUST have corresponding tests. No exceptions.

## Test Execution Rules — Do Not Waste Runs

- **Run tests ONCE after a logical set of changes.** Do not re-run passing tests expecting
  different results. If tests passed, move on.
- **Never grep or filter pytest output.** Run `pytest` directly and read the full output.
  Do not pipe through `Select-String`, `grep`, `findstr`, or any filter. The raw pytest
  output contains everything needed — pass/fail counts, coverage, and failure details.
- **One run per change set.** If you made 3 related edits (e.g., source + tests + config),
  run the suite once after all edits, not 3 times.
- **Do not re-run on success.** If the suite passes, report the results and continue.
  Never run the same suite again "to be sure."

## Install Real Dependencies — No Fake Tests

**Never mock or stub a library that can be installed.** Fake tests negate the validity of the test suite.

- Before writing tests that use an optional dependency (`httpx`, `sqlalchemy`, `openpyxl`, etc.),
  **install the real package** in the dev environment. Do not create a mock stand-in.
- Add all testable optional dependencies to `[project.optional-dependencies] dev` in `pyproject.toml`
  so they are always available in the test environment.
- **Mocks are only acceptable for true external services** — live APIs requiring auth tokens,
  production databases, Azure endpoints — where a real call is impractical or costly.
  Even then, prefer lightweight local substitutes:
  - Use **SQLite** (in-memory) for database adapter tests instead of mocking SQLAlchemy.
  - Use **`pytest-httpserver`** or a local fixture server for HTTP adapter tests instead of
    mocking httpx.
  - Use **temp files** for CSV/Excel/NDJSON adapter tests with real data.
- If a dependency truly cannot be installed (platform binary unavailable, etc.), mark the test
  with `@pytest.mark.skip(reason="...")` — do NOT write a passing fake.

## Test Framework & Tools

- **pytest** — Test runner. Use `pytest -v --tb=short` for verbose output with short tracebacks.
- **pytest-cov** — Coverage. Target >90% on core modules. Run with `pytest --cov=src/ceds_jsonld --cov-report=term-missing`.
- **hypothesis** — Property-based testing for data transformation functions.
- **ruff** — Lint test files too. Tests follow the same coding standards as source.

## Test File Organization

```
tests/
├── conftest.py              ← Shared fixtures (sample data, registries, mock configs)
├── test_registry.py         ← ShapeRegistry tests
├── test_builder.py          ← JSONLDBuilder tests
├── test_mapping.py          ← FieldMapper tests
├── test_transforms.py       ← Transform function tests
├── test_validator.py        ← SHACLValidator tests
├── test_introspector.py     ← SHACLIntrospector tests
├── adapters/
│   ├── test_csv_adapter.py
│   ├── test_excel_adapter.py
│   ├── test_dict_adapter.py
│   └── test_api_adapter.py
├── cosmos/
│   ├── test_client.py
│   └── test_partition.py
├── shapes/
│   ├── test_person_shape.py  ← Person-specific golden file tests
│   └── test_org_shape.py     ← Organization-specific golden file tests
├── benchmarks/
│   └── test_performance.py   ← Performance regression tests
└── fixtures/
    ├── person_sample.csv
    ├── person_expected.json   ← Golden file for Person output
    ├── org_sample.csv
    └── org_expected.json      ← Golden file for Organization output
```

## Test Categories

### 1. Unit Tests
Test individual functions and methods in isolation.
```python
def test_sex_prefix_transform():
    assert sex_prefix("Female") == "Sex_Female"
    assert sex_prefix("Male") == "Sex_Male"

def test_build_one_minimal_person():
    builder = JSONLDBuilder(person_shape_def)
    result = builder.build_one(minimal_row)
    assert result["@type"] == "Person"
    assert "@id" in result
```

### 2. Golden File Tests
Compare builder output against hand-verified reference JSON-LD documents.
```python
def test_person_output_matches_golden_file():
    """Output must exactly match ResearchFiles/person_example.json structure."""
    builder = JSONLDBuilder(person_shape_def)
    result = builder.build_one(sample_row)
    expected = load_golden_file("fixtures/person_expected.json")
    assert result == expected
```

### 3. Round-Trip Validation Tests
Prove that our JSON-LD output is valid RDF by parsing it back and validating with pySHACL.
```python
def test_person_jsonld_validates_against_shacl():
    """Built JSON-LD must pass SHACL validation when parsed as RDF."""
    builder = JSONLDBuilder(person_shape_def)
    doc = builder.build_one(sample_row)

    # Parse JSON-LD into rdflib graph
    g = Graph().parse(data=json.dumps(doc), format="json-ld")

    # Validate against SHACL
    conforms, _, report = validate(g, shacl_graph=person_shacl_graph)
    assert conforms, f"SHACL validation failed:\n{report}"
```

### 4. Property-Based Tests (Hypothesis)
Generate random but valid inputs and verify invariants.
```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1), st.text(min_size=1))
def test_person_name_always_has_required_fields(first, last):
    row = {"FirstName": first, "LastName": last, ...}
    result = builder.build_one(mapper.map(row))
    name = result["hasPersonName"]
    assert "FirstName" in name
    assert "LastOrSurname" in name
```

### 5. Performance Regression Tests
Ensure performance does not degrade beyond acceptable thresholds.
```python
import time

def test_build_10k_persons_under_1_second():
    """Performance regression guard: 10K records must build in <1s."""
    rows = [sample_row] * 10_000
    t0 = time.perf_counter()
    results = [builder.build_one(r) for r in rows]
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"10K records took {elapsed:.2f}s (limit: 1.0s)"
    assert len(results) == 10_000
```

### 6. Edge Case Tests
Every shape must test these cases:
- Missing optional fields (should produce output without those fields)
- Missing required fields (should raise `MappingError`)
- Empty strings vs. None values
- Multi-value fields with varying counts (0, 1, many)
- Pipe-delimited fields with mismatched counts across columns
- Unicode characters in names
- Date format variations
- Very long strings (boundary testing)

### 7. User Journey Tests (Integration Scenarios)
Test complete workflows from the end user's perspective. These simulate real-world usage patterns, not just internal API correctness.
```python
def test_csv_with_nonstandard_columns_to_jsonld():
    """User story: I have a CSV with non-standard column names and
    I need to produce valid JSON-LD without writing a custom YAML file."""
    registry = ShapeRegistry()
    registry.load_shape("person")
    pipeline = Pipeline(
        source=CSVAdapter("my_data.csv"),
        shape="person",
        registry=registry,
        source_overrides={
            "hasPersonName": {"FirstName": "FIRST_NM", "LastOrSurname": "LAST_NM"},
        },
        id_source="STUDENT_ID",
    )
    docs = pipeline.build_all()
    assert all(doc["@type"] == "Person" for doc in docs)
    assert all("@id" in doc for doc in docs)
```

Every new feature should have at least one user journey test that exercises the feature through the Pipeline, not just through the lower-level API. Ask: "How would an end user use this?" and write that test.

## Test Reporting Protocol

After running tests, ALWAYS report:
```
Tests: X passed, Y failed, Z skipped
Coverage: XX% (module breakdown if relevant)
Failures:
  - test_name: brief description of failure
```

If any test fails:
1. Fix the issue
2. Re-run tests
3. Confirm all pass before moving on

## Running Tests

Always run pytest **directly** — never pipe or filter the output.

```powershell
# Run all tests
python -m pytest tests/ -v --tb=short

# Run with coverage
python -m pytest tests/ --cov=src/ceds_jsonld --cov-report=term-missing -v

# Run specific test file
python -m pytest tests/test_builder.py -v

# Run tests matching a pattern
python -m pytest tests/ -k "person" -v

# Run performance tests only
python -m pytest tests/benchmarks/ -v
```

**NEVER** do any of the following:
```powershell
# BAD — grepping test output hides context and is pointless
pytest 2>&1 | Select-String "passed|failed"
pytest | grep PASSED
pytest | findstr /i "error"

# BAD — piping through Select-Object to get "just the summary" breaks output
python -m pytest tests/ -q --tb=short 2>&1 | Select-Object -Last 15

# BAD — piping through any filter, period
python -m pytest tests/ | Out-String | Select-String "passed"
```

Read the raw pytest output. It already tells you everything.

## Terminal Output Hazards — Avoiding Stale Results

The shared PowerShell terminal **accumulates history from all previous commands**.
When pytest output is large (>60 KB), the tool writes it to a temp file that
contains the ENTIRE terminal buffer — including output from earlier runs.

**Critical rules:**

1. **Set adequate timeouts.** The full suite (900+ tests) takes 3–6 minutes.
   Use `timeout: 360000` (6 min) for a full run. Using a short timeout causes
   `KeyboardInterrupt` which looks like a real failure but is not.
2. **Never trust `[... PREVIOUS OUTPUT TRUNCATED ...]` files.** When output is
   written to a temp file, read from the END of the file, not the beginning.
   The beginning contains old terminal history. The last 20–30 lines have the
   real results.
3. **Use `cls ;` before the test command** when you need clean output. This
   clears the terminal buffer so there is no stale history mixed in:
   ```powershell
   cls ; python -m pytest tests/ -v --tb=short
   ```
4. **When in doubt, run the targeted test file first.** Before the full suite,
   run just the new/changed tests to confirm GREEN. This is fast (<2s) and
   gives unambiguous results:
   ```powershell
   python -m pytest tests/test_issue_NN_foo.py -v --tb=short
   ```
5. **After the full suite, verify the summary line.** The ONLY line that matters
   is the final `=== N passed, M failed ===` line. If you see failures, confirm
   they are from THIS run (not an earlier one in the buffer) by checking that the
   test count matches `collected N items`.

## Fixtures and Conftest

Use `conftest.py` for shared fixtures:
```python
@pytest.fixture
def person_shape_def():
    """Load the Person shape definition for testing."""
    registry = ShapeRegistry()
    registry.load_shape("person")
    return registry.get_shape("person")

@pytest.fixture
def sample_person_row():
    """A minimal valid Person data row."""
    return {
        "FirstName": "Jane",
        "LastName": "Doe",
        "Birthdate": "1990-01-15",
        "Sex": "Female",
        "RaceEthnicity": "White",
        "PersonIdentifiers": "123456789",
        "IdentificationSystems": "SSN",
        "PersonIdentifierTypes": "SSN",
    }
```
