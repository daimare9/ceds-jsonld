"""Sample: Synthetic Data Generator usage.

Run this script to generate synthetic CEDS Person data and see
the full round-trip from generated rows to JSON-LD documents.

Usage:
    python examples/sdg_demo.py
"""

from __future__ import annotations

from pathlib import Path

from ceds_jsonld import DictAdapter, FieldMapper, JSONLDBuilder, Pipeline, ShapeRegistry
from ceds_jsonld.sdg import SyntheticDataGenerator

OUTPUT_DIR = Path("examples/output")


def main() -> None:
    # ── 1. Set up the registry and generator ──────────────────────────
    registry = ShapeRegistry()
    registry.load_shape("person")
    shape_def = registry.get_shape("person")

    gen = SyntheticDataGenerator(registry, seed=42, pool_size=300)

    # ── 2. Generate raw rows (flat dicts, like CSV input) ─────────────
    rows = gen.generate("person", count=10)

    print("=" * 70)
    print("  SYNTHETIC DATA GENERATOR — DEMO")
    print("=" * 70)

    print(f"\nGenerated {len(rows)} synthetic Person rows.\n")
    print("── Sample Row (first record) ─────────────────────────────────")
    for key, val in rows[0].items():
        print(f"  {key:30s} = {val}")

    # ── 3. Convert rows to JSON-LD via the standard pipeline ──────────
    mapper = FieldMapper(shape_def.mapping_config)
    builder = JSONLDBuilder(shape_def)

    docs = []
    for row in rows:
        mapped = mapper.map(row)
        doc = builder.build_one(mapped)
        docs.append(doc)

    print("\n── First JSON-LD Document ────────────────────────────────────")
    import json
    print(json.dumps(docs[0], indent=2))

    # ── 4. Write outputs to files ─────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # CSV
    csv_path = gen.generate_csv("person", OUTPUT_DIR / "persons.csv", count=50)
    print(f"\n✓ CSV written:    {csv_path}  (50 rows)")

    # NDJSON
    ndjson_path = gen.generate_ndjson("person", OUTPUT_DIR / "persons.ndjson", count=50)
    print(f"✓ NDJSON written: {ndjson_path}  (50 rows)")

    # JSON-LD (the 10 docs we already built)
    jsonld_path = OUTPUT_DIR / "persons_jsonld.json"
    jsonld_path.write_text(json.dumps(docs, indent=2), encoding="utf-8")
    print(f"✓ JSON-LD written: {jsonld_path}  ({len(docs)} documents)")

    # ── 5. Quick pipeline round-trip ──────────────────────────────────
    print("\n── Pipeline Round-Trip ───────────────────────────────────────")
    source = DictAdapter(rows)
    pipeline = Pipeline(source, "person", registry)
    docs_pipeline = pipeline.build_all()
    print(f"  Records in:  {len(rows)}")
    print(f"  Docs out:    {len(docs_pipeline)}")
    print(f"  All have @type=Person: {all(d.get('@type') == 'Person' for d in docs_pipeline)}")

    print("\nDone! Check the examples/output/ directory for generated files.")


if __name__ == "__main__":
    main()
