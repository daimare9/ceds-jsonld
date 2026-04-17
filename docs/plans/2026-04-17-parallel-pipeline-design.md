# Parallel Pipeline Design — Closing the Spark Performance Gap

**Date:** 2026-04-17
**Status:** Proposed
**Relates to:** Sink `workers` parameter, `to_sink()` hot path

---

## Problem Statement

Spark processes 1.8M records in ~40 seconds using distributed executors.
Our `Pipeline.to_sink()` takes 4+ minutes for a comparable workload on a
22-core machine. The current `workers` parameter only parallelizes **file
writes** (I/O), but the bottleneck is the **CPU-bound Python hot loop**:

```
for raw_row in source.read():       # sequential
    mapped = mapper.map(raw_row)     # CPU: dict manipulation
    doc = builder.build_one(mapped)  # CPU: dict construction
    chunk.append(doc)                # memory
    if len(chunk) >= chunk_size:
        sink.write_chunk(chunk)      # I/O (parallelized by workers)
```

Threading cannot help because `map()` and `build_one()` are pure Python
(GIL-bound). Only multiprocessing bypasses the GIL.

---

## Architecture: Producer → Worker Pool → Writer

```
┌──────────────┐     ┌──────────────────────────┐     ┌────────────┐
│  Main Process │     │   Worker Pool (N procs)   │     │   Sink     │
│              │     │                          │     │            │
│  source.read()─────►  Partition rows into      │     │            │
│  (batches of  │     │  chunks of chunk_size    │     │            │
│   chunk_size) │     │                          │     │            │
│              │     │  Worker(chunk) →          │     │            │
│              │     │    mapper.map(row)        │     │            │
│              │     │    builder.build_one(row) │     │            │
│              │     │    serialize (orjson)     │     │            │
│              │     │    return bytes           ─────►  write_part │
│              │     │                          │     │            │
└──────────────┘     └──────────────────────────┘     └────────────┘
```

### Key insight: merge map + build + serialize into one worker task

Each worker receives a batch of raw rows and returns **serialized bytes**
ready to be written directly to a part file. This eliminates:

1. Per-row Python function call overhead in the main process
2. IPC cost of sending large dicts back (bytes are cheaper)
3. Separate write step — workers can write their own part files

### Why this mirrors Spark

| Spark concept | Our equivalent |
|---------------|----------------|
| Partition | Chunk of `chunk_size` raw rows |
| Executor | `multiprocessing.Process` in a pool |
| Task | `map → build → serialize → write` on one chunk |
| Driver | Main process: reads source, distributes chunks |

---

## Approach Options

### Option A: `ProcessPoolExecutor` with chunked map (Recommended)

- Main process reads source in batches of `chunk_size`
- Submit each batch to a `ProcessPoolExecutor`
- Worker function: `map_build_serialize(rows, mapping_config, shape_def) → bytes`
- Worker writes its own part file OR returns bytes for main process to write
- Workers reconstruct `FieldMapper` + `JSONLDBuilder` from config (pickle-safe)

**Pros:** Simple API change (just add `workers` to Pipeline), familiar stdlib
**Cons:** Pickle overhead for sending rows to workers, memory for N batches in flight

**Expected speedup:** 4-8x on 22 cores (not full 22x due to IPC overhead)

### Option B: `multiprocessing.Pool` with `imap_unordered`

- Same as A but uses `imap_unordered` for streaming back-pressure
- Each result is yielded as ready, main process writes part files in arrival order

**Pros:** Better memory control (bounded queue)
**Cons:** Part file ordering is non-deterministic (acceptable — Spark doesn't guarantee order either)

### Option C: Partitioned source reads

- If the source adapter supports slicing (e.g. SQL LIMIT/OFFSET, CSV seek),
  each worker reads its own partition directly
- Fully independent: read → map → build → serialize → write

**Pros:** Maximum parallelism, no IPC for row data
**Cons:** Requires adapter changes (`Readable.partition(n)`), not all sources support it

### Recommendation

**Start with Option A** — it works with all existing adapters unchanged.
Add Option C later as an optimization for adapters that support partitioning.

---

## API Design

```python
# Current (unchanged for workers=1):
result = pipeline.to_sink(sink)

# Parallel (new):
result = pipeline.to_sink(sink, workers=4)
result = pipeline.to_sink(sink, workers="auto")  # os.cpu_count()
```

The `workers` parameter on `to_sink()` controls the **pipeline parallelism**
(map+build+serialize), separate from `sink.workers` which controls I/O
parallelism. When `to_sink(workers=N)` is used with N > 1:

- Sink's own `workers` parameter is ignored (each pipeline worker writes
  its own part file directly)
- The sink still handles `open()` / `close()` / `_SUCCESS` semantics

For `workers=1` (default), behaviour is identical to today.

---

## Worker Function (Pickle-Safe)

```python
def _pipeline_worker(
    chunk: list[dict[str, Any]],
    part_index: int,
    output_path: str,
    mapping_config: dict[str, Any],
    shape_def_data: dict[str, Any],  # serializable shape config
) -> tuple[int, int]:
    """Process one chunk: map → build → serialize → write.

    Returns (records_written, bytes_written).
    """
    mapper = FieldMapper(mapping_config)
    builder = JSONLDBuilder.from_config(shape_def_data)

    part_file = Path(output_path) / f"part-{part_index:05d}.ndjson"
    total_bytes = 0
    with part_file.open("wb") as fh:
        for raw_row in chunk:
            mapped = mapper.map(raw_row)
            doc = builder.build_one(mapped)
            line = dumps(doc, pretty=False) + b"\n"
            fh.write(line)
            total_bytes += len(line)
    return len(chunk), total_bytes
```

### Pickle considerations

- `mapping_config` is a plain dict — pickle-safe ✓
- `ShapeDefinition` needs a `to_dict()` / `from_config()` pair for
  reconstructing in workers without filesystem access
- Raw rows from adapters are plain dicts — pickle-safe ✓
- Custom transforms (callables) are NOT pickle-safe → must be registered
  by name, resolved in worker

---

## Performance Estimates

Based on the current 4-minute run (1.8M records) and assuming the hot loop
is ~80% of total time:

| Workers | Est. time | Speedup | Notes |
|---------|-----------|---------|-------|
| 1 | ~240s | 1x | Current baseline |
| 4 | ~70s | 3.4x | Conservative (IPC overhead) |
| 8 | ~40s | 6x | Matches Spark for this workload |
| 16 | ~30s | 8x | Diminishing returns from IPC |
| "auto" (22) | ~28s | 8.5x | Memory-bound at this point |

The goal is **sub-60 seconds for 1.8M records** with `workers=8`.

---

## Implementation Phases

### Phase 1: Core multiprocessing (this feature)
- Add `workers` param to `Pipeline.to_sink()`
- Implement `_pipeline_worker` as a module-level function
- Add `ShapeDefinition.to_serializable()` for pickle transport
- Tests: correctness, ordering, error handling, DLQ with workers

### Phase 2: Benchmarks and tuning
- Benchmark 100K, 500K, 1M, 1.8M records with various worker counts
- Tune chunk_size for optimal IPC/compute ratio
- Profile IPC overhead and memory usage

### Phase 3: Partitioned source reads (Option C)
- Add `Readable.partition(n) → list[Readable]` protocol method
- CSV adapter: partition by byte offset
- SQL adapter: partition by LIMIT/OFFSET
- Workers read directly, zero IPC for row data

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Pickle overhead for large rows | Slower than expected | Batch rows, measure IPC vs compute ratio |
| Custom transforms not picklable | Worker crash | Named transform registry, resolve by name |
| Memory pressure (N chunks in flight) | OOM | Bounded submission queue, `max_tasks_per_child` |
| Part file ordering non-deterministic | Confusing for users | Document that part numbering matches submission order |
| Dead letter queue in workers | Lost error context | Workers return errors, main process writes DLQ |

---

## Not In Scope

- Distributed processing across machines (use Spark for that)
- GPU acceleration
- Rewriting mapper/builder in Rust/Cython (future consideration)
- Changes to the Sink protocol
