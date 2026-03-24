"""Model comparison benchmark — Qwen3 4B vs Granite4 3B vs Phi-4 Mini.

Compares three compact LLMs on synthetic education data generation quality
across five dimensions:

1. **JSON validity rate** — % of responses that parse as valid JSON.
2. **Value quality** — values that pass SHACL-derived format constraints.
3. **Diversity** — ratio of unique values to total (1.0 = all unique).
4. **Throughput** — tokens/second on the available GPU/CPU.
5. **VRAM usage** — peak GPU memory during generation.

Usage:
    python tests/benchmarks/bench_llm_models.py [--count 200] [--backend transformers|ollama]

Results are saved to ``ResearchFiles/LLM_MODEL_COMPARISON.md``.

Requirements:
    pip install ceds-jsonld[sdg]    # torch + transformers + huggingface-hub
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path

MODELS_TRANSFORMERS = [
    "Qwen/Qwen3-4B",
    "ibm-granite/granite-3.3-3b-instruct",
    "microsoft/Phi-4-mini-instruct",
]

MODELS_OLLAMA = [
    "qwen3:4b",
    "granite4-dense:3b",
    "phi4-mini",
]

# Properties to benchmark — representative of real usage
BENCH_PROPERTIES = [
    {
        "label": "First Name",
        "description": "The full legal first name given to a person at birth.",
        "data_type": "string",
        "max_length": 75,
        "parent_class": "Person Name",
    },
    {
        "label": "Birthdate",
        "description": "The year, month and day on which a person was born.",
        "data_type": "date (YYYY-MM-DD)",
        "parent_class": "Person",
    },
    {
        "label": "Telephone Number",
        "description": "The telephone number including the area code.",
        "data_type": "token",
        "max_length": 24,
        "parent_class": "Person Telephone",
    },
]


def _build_prompt(prop: dict, count: int) -> str:
    """Build a benchmark prompt from property metadata."""
    lines = [
        "You are a synthetic data generator for education data systems.",
        "",
        f"Generate exactly {count} realistic values for the following CEDS (Common Education Data Standards) property:",
        "",
        f"Property: {prop['label']}",
    ]
    if prop.get("description"):
        lines.append(f"Description: {prop['description']}")
    lines.append(f"Data Type: {prop['data_type']}")
    if prop.get("max_length"):
        lines.append(f"Max Length: {prop['max_length']}")
    lines.append(f"Parent Class: {prop['parent_class']}")
    lines.extend(
        [
            "",
            "Context: US K-12 and postsecondary education records.",
            "",
            "Requirements:",
            "- Values must be realistic and diverse",
            "- Values must conform to the data type and format constraints",
            "- Return ONLY the JSON object, no explanation",
            "",
            '{"values": ["val1", "val2", ...]}',
        ]
    )
    return "\n".join(lines)


def _parse_values(text: str) -> list[str] | None:
    """Parse JSON values from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[^{}]*\"values\"\s*:\s*\[.*?\]\s*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            vals = data.get("values")
            if isinstance(vals, list):
                return [str(v) for v in vals if v is not None and str(v).strip()]
        except json.JSONDecodeError:
            pass
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            vals = json.loads(match.group())
            if isinstance(vals, list):
                return [str(v) for v in vals if v is not None and str(v).strip()]
        except json.JSONDecodeError:
            pass
    return None


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PHONE_RE = re.compile(r"^[\d\s\-\(\)\+\.]+$")


def _check_format(prop: dict, values: list[str]) -> float:
    """Check what fraction of values match expected format constraints."""
    if not values:
        return 0.0
    valid = 0
    for v in values:
        if prop["data_type"].startswith("date"):
            if DATE_RE.match(v):
                valid += 1
        elif prop["data_type"] == "token" and "telephone" in prop["label"].lower():
            if PHONE_RE.match(v) and len(v) <= (prop.get("max_length") or 999):
                valid += 1
        elif prop["data_type"] == "string":
            maxlen = prop.get("max_length") or 999
            if 1 <= len(v) <= maxlen:
                valid += 1
        else:
            valid += 1
    return valid / len(values)


def bench_transformers(models: list[str], count: int) -> list[dict]:
    """Benchmark models via in-process transformers."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    results = []
    for model_id in models:
        print(f"\n{'=' * 60}")
        print(f"Model: {model_id}")
        print(f"{'=' * 60}")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device == "cuda" else torch.float32

        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=dtype,
            device_map="auto",
        )

        if device == "cuda":
            torch.cuda.reset_peak_memory_stats()

        model_results = {"model": model_id, "device": device, "properties": []}

        for prop in BENCH_PROPERTIES:
            prompt = _build_prompt(prop, count)
            messages = [{"role": "user", "content": prompt}]

            template_kwargs = {"return_tensors": "pt", "add_generation_prompt": True}
            try:
                inputs = tokenizer.apply_chat_template(
                    messages,
                    enable_thinking=False,
                    **template_kwargs,
                )
            except TypeError:
                inputs = tokenizer.apply_chat_template(messages, **template_kwargs)
            inputs = inputs.to(device)

            start = time.perf_counter()
            with torch.no_grad():
                output = model.generate(
                    inputs,
                    max_new_tokens=4096,
                    temperature=0.8,
                    top_p=0.95,
                    repetition_penalty=1.1,
                    do_sample=True,
                )
            elapsed = time.perf_counter() - start
            new_tokens = output.shape[1] - inputs.shape[1]
            tps = new_tokens / elapsed if elapsed > 0 else 0

            raw = tokenizer.decode(output[0][inputs.shape[1] :], skip_special_tokens=True)
            values = _parse_values(raw)

            prop_result = {
                "property": prop["label"],
                "json_valid": values is not None,
                "value_count": len(values) if values else 0,
                "format_rate": _check_format(prop, values) if values else 0.0,
                "diversity": (len(set(values)) / len(values)) if values else 0.0,
                "tokens_per_sec": round(tps, 1),
                "elapsed_sec": round(elapsed, 2),
            }
            model_results["properties"].append(prop_result)
            print(
                f"  {prop['label']:20s} | "
                f"valid={prop_result['json_valid']} | "
                f"count={prop_result['value_count']:3d} | "
                f"format={prop_result['format_rate']:.0%} | "
                f"diversity={prop_result['diversity']:.0%} | "
                f"{tps:.1f} tok/s"
            )

        if device == "cuda":
            peak_mb = torch.cuda.max_memory_allocated() / 1024 / 1024
            model_results["peak_vram_mb"] = round(peak_mb)
            print(f"  Peak VRAM: {peak_mb:.0f} MB")

        # Cleanup
        del model, tokenizer
        if device == "cuda":
            torch.cuda.empty_cache()

        results.append(model_results)

    return results


def bench_ollama(models: list[str], count: int) -> list[dict]:
    """Benchmark models via Ollama API."""
    import ollama as ollama_lib

    client = ollama_lib.Client(host="http://localhost:11434")
    results = []

    for model_tag in models:
        print(f"\n{'=' * 60}")
        print(f"Model: {model_tag}")
        print(f"{'=' * 60}")

        model_results = {"model": model_tag, "device": "ollama", "properties": []}

        for prop in BENCH_PROPERTIES:
            prompt = _build_prompt(prop, count)

            start = time.perf_counter()
            response = client.chat(
                model=model_tag,
                messages=[{"role": "user", "content": prompt}],
                format={
                    "type": "object",
                    "properties": {
                        "values": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["values"],
                },
            )
            elapsed = time.perf_counter() - start
            raw = response["message"]["content"]
            values = _parse_values(raw)

            # Estimate tokens from response
            est_tokens = len(raw.split())
            tps = est_tokens / elapsed if elapsed > 0 else 0

            prop_result = {
                "property": prop["label"],
                "json_valid": values is not None,
                "value_count": len(values) if values else 0,
                "format_rate": _check_format(prop, values) if values else 0.0,
                "diversity": (len(set(values)) / len(values)) if values else 0.0,
                "tokens_per_sec": round(tps, 1),
                "elapsed_sec": round(elapsed, 2),
            }
            model_results["properties"].append(prop_result)
            print(
                f"  {prop['label']:20s} | "
                f"valid={prop_result['json_valid']} | "
                f"count={prop_result['value_count']:3d} | "
                f"format={prop_result['format_rate']:.0%} | "
                f"diversity={prop_result['diversity']:.0%} | "
                f"~{tps:.1f} tok/s"
            )

        results.append(model_results)

    return results


def _write_report(results: list[dict], output: Path, count: int) -> None:
    """Write a markdown comparison report."""
    lines = [
        "# LLM Model Comparison — Synthetic Data Generation",
        "",
        f"**Generated:** {time.strftime('%Y-%m-%d %H:%M')}",
        f"**Pool size:** {count} values per property",
        f"**Properties tested:** {len(BENCH_PROPERTIES)}",
        "",
        "## Summary",
        "",
        "| Model | JSON Valid | Avg Format | Avg Diversity | Avg tok/s | VRAM (MB) |",
        "|-------|-----------|-----------|--------------|----------|----------|",
    ]

    for r in results:
        props = r["properties"]
        valid = sum(1 for p in props if p["json_valid"])
        fmt = statistics.mean(p["format_rate"] for p in props)
        div = statistics.mean(p["diversity"] for p in props)
        tps = statistics.mean(p["tokens_per_sec"] for p in props)
        vram = r.get("peak_vram_mb", "N/A")
        lines.append(f"| {r['model']} | {valid}/{len(props)} | {fmt:.0%} | {div:.0%} | {tps:.1f} | {vram} |")

    lines.extend(["", "## Detailed Results", ""])

    for r in results:
        lines.extend([f"### {r['model']}", ""])
        lines.append("| Property | Valid JSON | Count | Format Rate | Diversity | tok/s | Time (s) |")
        lines.append("|----------|----------|-------|------------|----------|------|---------|")
        for p in r["properties"]:
            lines.append(
                f"| {p['property']} | {p['json_valid']} | {p['value_count']} | "
                f"{p['format_rate']:.0%} | {p['diversity']:.0%} | "
                f"{p['tokens_per_sec']} | {p['elapsed_sec']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Methodology",
            "",
            "- Each model generates a pool of values for 3 representative properties.",
            '- **JSON validity**: whether the raw output parses as `{"values": [...]}` or a bare array.',
            "- **Format rate**: fraction of values matching expected type constraints "
            "(date → ISO 8601, string → max length, token → digits/symbols).",
            "- **Diversity**: unique values / total values (1.0 = all unique).",
            "- **Throughput**: new tokens per second (transformers) or estimated (Ollama).",
            "- **VRAM**: peak GPU memory allocated (transformers only).",
            "",
            "## Recommendation",
            "",
            "See ROADMAP.md Task 1.20 for the chosen default model.",
        ]
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark LLM models for SDG")
    parser.add_argument("--count", type=int, default=200, help="Values per property")
    parser.add_argument(
        "--backend",
        choices=["transformers", "ollama"],
        default="transformers",
        help="Which backend to benchmark",
    )
    args = parser.parse_args()

    output = Path(__file__).parent.parent.parent / "ResearchFiles" / "LLM_MODEL_COMPARISON.md"

    if args.backend == "ollama":
        results = bench_ollama(MODELS_OLLAMA, args.count)
    else:
        results = bench_transformers(MODELS_TRANSFORMERS, args.count)

    _write_report(results, output, args.count)


if __name__ == "__main__":
    main()
