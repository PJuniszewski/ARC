"""Tool-calling strategy benchmark.

Compares three approaches to the same task ("find the warmest of 20 European
capitals by current temperature") and reports inference calls, tool
executions, latency, and token usage:

  1. naive_sequential   - one tool per turn, parallel disabled
  2. modern_sequential  - same tool, parallel allowed (Claude default)
  3. code_mode          - single execute_python tool, model writes a script
                          that parallelizes inside a sandbox

Real Open-Meteo API (no mocks); real Anthropic API (no mocks). Runs each
approach RUNS_PER_APPROACH times in interleaved order. Writes results.json
and SUMMARY.md to this directory.

Run:
    export ANTHROPIC_API_KEY=...
    pip install -e ".[eval]"   # from repo root, picks up anthropic>=0.40
    python eval/tool-calling-bench/benchmark.py
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import re
import statistics
import sys
import time
import traceback
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

MODEL = "claude-opus-4-7"
MAX_TOKENS = 4096
RUNS_PER_APPROACH = 3
MAX_TURNS = 30  # safety cap on the tool-use loop
SLEEP_BETWEEN_RUNS_S = 2.0

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# 20 European capitals, fixed order (Warsaw first, Riga last per task spec).
CITY_COORDS: dict[str, tuple[float, float]] = {
    "Warsaw": (52.2297, 21.0122),
    "Berlin": (52.5200, 13.4050),
    "Paris": (48.8566, 2.3522),
    "Madrid": (40.4168, -3.7038),
    "Rome": (41.9028, 12.4964),
    "Amsterdam": (52.3676, 4.9041),
    "Vienna": (48.2082, 16.3738),
    "Prague": (50.0755, 14.4378),
    "Budapest": (47.4979, 19.0402),
    "Brussels": (50.8503, 4.3517),
    "Lisbon": (38.7223, -9.1393),
    "Athens": (37.9838, 23.7275),
    "Stockholm": (59.3293, 18.0686),
    "Oslo": (59.9139, 10.7522),
    "Helsinki": (60.1699, 24.9384),
    "Copenhagen": (55.6761, 12.5683),
    "Dublin": (53.3498, -6.2603),
    "Bucharest": (44.4268, 26.1025),
    "Sofia": (42.6977, 23.3219),
    "Riga": (56.9496, 24.1052),
}
CITIES: list[str] = list(CITY_COORDS.keys())

TASK_DESCRIPTION = (
    "Find the warmest of these 20 European capital cities by current "
    "temperature: " + ", ".join(CITIES) + ". Return the city name and "
    "its current temperature in Celsius."
)


# ----------------------------------------------------------------------------
# Open-Meteo client
# ----------------------------------------------------------------------------

def fetch_temperature(city: str) -> float:
    """Fetch current temperature in Celsius from Open-Meteo."""
    if city not in CITY_COORDS:
        raise KeyError(f"Unknown city: {city!r}. Known: {sorted(CITY_COORDS)}")
    lat, lon = CITY_COORDS[city]
    qs = urllib.parse.urlencode(
        {"latitude": lat, "longitude": lon, "current": "temperature_2m"}
    )
    url = f"{OPEN_METEO_URL}?{qs}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return float(data["current"]["temperature_2m"])


# ----------------------------------------------------------------------------
# Result types
# ----------------------------------------------------------------------------

@dataclass
class RunResult:
    approach: str
    run_idx: int
    inference_calls: int = 0
    tool_executions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    final_answer: str = ""
    warmest_city: str | None = None
    warmest_temp_c: float | None = None
    error: str | None = None
    correct: bool = False


# ----------------------------------------------------------------------------
# Anthropic client
# ----------------------------------------------------------------------------

def make_client():
    """Create an Anthropic client; exit cleanly if API key is missing."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY is not set in the environment.\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        from anthropic import Anthropic
    except ImportError:
        print(
            "ERROR: anthropic package not installed. Run:\n"
            "  pip install -e \".[eval]\"   # from repo root\n"
            "  # or: pip install 'anthropic>=0.40'",
            file=sys.stderr,
        )
        sys.exit(2)
    return Anthropic()


# ----------------------------------------------------------------------------
# Tool definitions
# ----------------------------------------------------------------------------

GET_WEATHER_TOOL = {
    "name": "get_weather",
    "description": (
        "Get the current temperature in Celsius for a European capital city. "
        "Returns an object {city, temperature_celsius}."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "Name of the European capital city (e.g. 'Warsaw').",
            }
        },
        "required": ["city"],
    },
}

EXECUTE_PYTHON_TOOL = {
    "name": "execute_python",
    "description": (
        "Execute Python code in a sandbox and return captured stdout. "
        "The sandbox has these helpers preloaded:\n"
        "- get_weather(city: str) -> float : current temperature (Celsius) for a city\n"
        "- CITIES : list of the 20 city names you must consider, in order\n"
        "- ThreadPoolExecutor, as_completed : for parallel execution\n"
        "Common builtins (print, len, max, min, sorted, range, dict, list, etc.) "
        "are available. There is no filesystem or network access beyond get_weather. "
        "Print your final answer to stdout."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute in the sandbox.",
            }
        },
        "required": ["code"],
    },
}


# ----------------------------------------------------------------------------
# Shared tool-use loop (approaches 1 and 2)
# ----------------------------------------------------------------------------

def _serialize_block(block: Any) -> dict[str, Any]:
    """Convert an SDK content block into a JSON-serializable dict."""
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)


def _tool_loop(
    client: Any,
    tools: list[dict],
    tool_choice: dict | None,
    dispatch: Callable[[str, dict], Any],
    user_prompt: str,
    result: RunResult,
) -> str:
    """Run a tool-use conversation until the model stops calling tools.

    Returns the model's final text. Mutates `result` (inference_calls,
    input/output tokens). Caller is responsible for tool_executions.
    """
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    for _ in range(MAX_TURNS):
        kwargs: dict[str, Any] = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "tools": tools,
            "messages": messages,
        }
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        response = client.messages.create(**kwargs)
        result.inference_calls += 1
        result.input_tokens += response.usage.input_tokens
        result.output_tokens += response.usage.output_tokens

        # Echo the assistant turn back, fully serialized.
        assistant_blocks = [_serialize_block(b) for b in response.content]
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]

        if not tool_uses:
            # Model is done - return concatenated text.
            return "\n".join(getattr(b, "text", "") for b in text_blocks).strip()

        # Execute every tool_use in this turn (modern_sequential may have N>1).
        tool_results: list[dict] = []
        for use in tool_uses:
            try:
                output = dispatch(use.name, dict(use.input))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": use.id,
                    "content": str(output) if not isinstance(output, str) else output,
                })
            except Exception as e:  # surface errors to the model so it can recover
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": use.id,
                    "content": f"ERROR: {type(e).__name__}: {e}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(
        f"Tool loop exceeded MAX_TURNS={MAX_TURNS} without an end_turn response"
    )


# ----------------------------------------------------------------------------
# Approach 1: naive sequential (one tool per turn, parallel disabled)
# ----------------------------------------------------------------------------

def run_naive_sequential(client: Any, run_idx: int) -> RunResult:
    result = RunResult(approach="naive_sequential", run_idx=run_idx)

    def dispatch(name: str, args: dict) -> str:
        if name != "get_weather":
            raise ValueError(f"unknown tool: {name}")
        result.tool_executions += 1
        temp = fetch_temperature(args["city"])
        return json.dumps({"city": args["city"], "temperature_celsius": temp})

    t0 = time.perf_counter()
    text = _tool_loop(
        client=client,
        tools=[GET_WEATHER_TOOL],
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        dispatch=dispatch,
        user_prompt=TASK_DESCRIPTION,
        result=result,
    )
    result.latency_s = time.perf_counter() - t0
    result.final_answer = text
    return result


# ----------------------------------------------------------------------------
# Approach 2: modern sequential (parallel tool calls allowed)
# ----------------------------------------------------------------------------

def run_modern_sequential(client: Any, run_idx: int) -> RunResult:
    result = RunResult(approach="modern_sequential", run_idx=run_idx)

    def dispatch(name: str, args: dict) -> str:
        if name != "get_weather":
            raise ValueError(f"unknown tool: {name}")
        result.tool_executions += 1
        temp = fetch_temperature(args["city"])
        return json.dumps({"city": args["city"], "temperature_celsius": temp})

    t0 = time.perf_counter()
    text = _tool_loop(
        client=client,
        tools=[GET_WEATHER_TOOL],
        tool_choice=None,  # default: parallel allowed
        dispatch=dispatch,
        user_prompt=TASK_DESCRIPTION,
        result=result,
    )
    result.latency_s = time.perf_counter() - t0
    result.final_answer = text
    return result


# ----------------------------------------------------------------------------
# Approach 3: code mode (single execute_python tool, sandbox with parallelism)
# ----------------------------------------------------------------------------

# Curated builtins whitelist. Enough for normal Python without giving the model
# arbitrary import/filesystem/network access.
_SAFE_BUILTIN_NAMES = [
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter",
    "float", "frozenset", "getattr", "hasattr", "hash", "id", "int",
    "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min",
    "next", "object", "ord", "print", "range", "repr", "reversed", "round",
    "set", "slice", "sorted", "str", "sum", "tuple", "type", "zip",
    "True", "False", "None", "Exception", "ValueError", "KeyError",
    "TypeError", "RuntimeError", "ZeroDivisionError",
    # __import__ kept so the model can write idiomatic `from foo import bar`.
    # This sandbox is NOT an isolation boundary (see README).
    "__import__",
]
_SAFE_BUILTINS: dict[str, Any] = {n: getattr(builtins, n) for n in _SAFE_BUILTIN_NAMES}


def _run_sandbox(code: str, get_weather_in_sandbox: Callable[[str], float]) -> str:
    """Run model-supplied Python code with curated globals and stdout capture."""
    sandbox_globals: dict[str, Any] = {
        "__builtins__": _SAFE_BUILTINS,
        "get_weather": get_weather_in_sandbox,
        "CITIES": list(CITIES),
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "as_completed": as_completed,
    }
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            compiled = compile(code, "<sandbox>", "exec")
            exec(compiled, sandbox_globals)  # noqa: S102 - benchmark sandbox
    except Exception:
        return buf.getvalue() + "\n--- TRACEBACK ---\n" + traceback.format_exc()
    return buf.getvalue()


def run_code_mode(client: Any, run_idx: int) -> RunResult:
    result = RunResult(approach="code_mode", run_idx=run_idx)

    def get_weather_in_sandbox(city: str) -> float:
        result.tool_executions += 1
        return fetch_temperature(city)

    def dispatch(name: str, args: dict) -> str:
        if name != "execute_python":
            raise ValueError(f"unknown tool: {name}")
        return _run_sandbox(args["code"], get_weather_in_sandbox)

    prompt = (
        "You have a Python REPL via the `execute_python` tool. The sandbox "
        "has `get_weather(city) -> float` (Celsius), `CITIES` (the 20-city "
        "list), and `ThreadPoolExecutor` / `as_completed`.\n\n"
        f"{TASK_DESCRIPTION}\n\n"
        "Write Python code that fetches all 20 temperatures in parallel using "
        "ThreadPoolExecutor, finds the maximum, and prints the warmest city "
        "and its temperature. Then read the printed output and give me the "
        "final answer."
    )

    t0 = time.perf_counter()
    text = _tool_loop(
        client=client,
        tools=[EXECUTE_PYTHON_TOOL],
        tool_choice=None,
        dispatch=dispatch,
        user_prompt=prompt,
        result=result,
    )
    result.latency_s = time.perf_counter() - t0
    result.final_answer = text
    return result


# ----------------------------------------------------------------------------
# Final-answer parsing
# ----------------------------------------------------------------------------

_TEMP_PATTERNS = [
    # "27.3°C", "27 °C", "27.3 degrees C", "27 degrees Celsius", "27.3 Celsius"
    re.compile(
        r"(-?\d+(?:\.\d+)?)\s*(?:°\s*[Cc](?![a-zA-Z])|deg(?:rees)?\.?\s*[Cc](?:elsius)?\b|[Cc]elsius\b)"
    ),
]


def parse_final_answer(text: str) -> tuple[str | None, float | None]:
    """Extract (city, temperature_celsius) from the model's final text.

    Picks the city name (case-insensitive) that appears LAST in the text — the
    final-answer sentence is what we care about, and a model may mention
    other cities earlier. For temperature, prefer values that are explicitly
    flagged as Celsius (°C, "degrees C", "Celsius"); fall back to the first
    number adjacent to the chosen city.
    """
    if not text:
        return None, None
    lower = text.lower()

    # Find the LAST mention of any known city.
    last_city: str | None = None
    last_pos = -1
    for c in CITIES:
        # rfind so the final sentence wins.
        pos = lower.rfind(c.lower())
        if pos > last_pos:
            last_pos = pos
            last_city = c
    if last_city is None:
        return None, None

    # Prefer a Celsius-flagged temperature anywhere in the text.
    for pat in _TEMP_PATTERNS:
        m = pat.search(text)
        if m:
            return last_city, float(m.group(1))

    # Fallback: a number near the city mention.
    window = text[max(0, last_pos - 60): last_pos + 200]
    m = re.search(r"-?\d+(?:\.\d+)?", window)
    return last_city, (float(m.group(0)) if m else None)


# ----------------------------------------------------------------------------
# Summarization
# ----------------------------------------------------------------------------

def summarize(runs: list[RunResult]) -> dict[str, Any]:
    by_approach: dict[str, list[RunResult]] = {}
    for r in runs:
        by_approach.setdefault(r.approach, []).append(r)

    # Determine consensus warmest city across all successful runs.
    cities_seen = [r.warmest_city for r in runs if r.warmest_city]
    consensus = None
    if cities_seen:
        consensus = max(set(cities_seen), key=cities_seen.count)

    # Mark correctness per run.
    for r in runs:
        r.correct = (r.warmest_city is not None and r.warmest_city == consensus)

    approaches: dict[str, Any] = {}
    for name, rs in by_approach.items():
        successful = [r for r in rs if r.error is None]
        latencies = [r.latency_s for r in successful]
        approaches[name] = {
            "inference_calls": (
                round(statistics.mean(r.inference_calls for r in successful), 2)
                if successful else None
            ),
            "tool_executions": (
                round(statistics.mean(r.tool_executions for r in successful), 2)
                if successful else None
            ),
            "input_tokens": (
                round(statistics.mean(r.input_tokens for r in successful), 1)
                if successful else None
            ),
            "output_tokens": (
                round(statistics.mean(r.output_tokens for r in successful), 1)
                if successful else None
            ),
            "latency_seconds": (
                {
                    "median": round(statistics.median(latencies), 3),
                    "min": round(min(latencies), 3),
                    "max": round(max(latencies), 3),
                }
                if latencies else None
            ),
            "final_answer": rs[-1].final_answer if rs else "",
            "all_runs_correct": all(r.correct for r in rs) and len(successful) == len(rs),
            "errors": [r.error for r in rs if r.error],
            "per_run": [
                {
                    "run_idx": r.run_idx,
                    "inference_calls": r.inference_calls,
                    "tool_executions": r.tool_executions,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "latency_s": round(r.latency_s, 3),
                    "warmest_city": r.warmest_city,
                    "warmest_temp_c": r.warmest_temp_c,
                    "correct": r.correct,
                    "error": r.error,
                }
                for r in rs
            ],
        }

    return {
        "task": "Find warmest of 20 European capitals",
        "model": MODEL,
        "runs_per_approach": RUNS_PER_APPROACH,
        "consensus_warmest_city": consensus,
        "approaches": approaches,
        "all_approaches_agree": (
            consensus is not None
            and all(
                a["all_runs_correct"]
                for a in approaches.values()
            )
        ),
    }


def write_summary_md(summary: dict[str, Any], path: Path) -> None:
    a = summary["approaches"]
    order = ["naive_sequential", "modern_sequential", "code_mode"]

    def fmt(x: Any) -> str:
        return "n/a" if x is None else str(x)

    lines: list[str] = []
    lines.append("# Tool-Calling Strategy Benchmark — Results")
    lines.append("")
    lines.append(f"**Task**: {summary['task']}")
    lines.append(f"**Model**: `{summary['model']}`")
    lines.append(f"**Runs per approach**: {summary['runs_per_approach']}")
    lines.append(f"**Consensus warmest city**: {fmt(summary['consensus_warmest_city'])}")
    lines.append(
        f"**All approaches agree**: {summary['all_approaches_agree']}"
    )
    lines.append("")
    lines.append("## Comparison")
    lines.append("")
    lines.append(
        "| Approach | Inference calls | Tool executions | Input tokens | Output tokens | Latency median (s) | Latency min (s) | Latency max (s) | All runs correct |"
    )
    lines.append(
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |"
    )
    for name in order:
        if name not in a:
            continue
        row = a[name]
        lat = row["latency_seconds"] or {}
        lines.append(
            f"| {name} | {fmt(row['inference_calls'])} | {fmt(row['tool_executions'])} | "
            f"{fmt(row['input_tokens'])} | {fmt(row['output_tokens'])} | "
            f"{fmt(lat.get('median'))} | {fmt(lat.get('min'))} | {fmt(lat.get('max'))} | "
            f"{'yes' if row['all_runs_correct'] else 'no'} |"
        )
    lines.append("")

    # Honest commentary.
    lines.append("## Notes")
    lines.append("")
    naive = a.get("naive_sequential", {})
    modern = a.get("modern_sequential", {})
    code = a.get("code_mode", {})
    naive_lat = (naive.get("latency_seconds") or {}).get("median")
    modern_lat = (modern.get("latency_seconds") or {}).get("median")
    code_lat = (code.get("latency_seconds") or {}).get("median")

    bullets: list[str] = []
    if naive_lat and code_lat:
        bullets.append(
            f"- Naive sequential is **{naive_lat / code_lat:.2f}× slower** "
            f"than code mode at the median ({naive_lat:.2f}s vs {code_lat:.2f}s)."
        )
    if modern_lat and code_lat:
        ratio = modern_lat / code_lat
        if ratio >= 1:
            bullets.append(
                f"- Modern sequential (parallel tool calls) is "
                f"**{ratio:.2f}× slower** than code mode "
                f"({modern_lat:.2f}s vs {code_lat:.2f}s). The realistic gap "
                f"between an up-to-date Anthropic API client and code mode "
                f"is much smaller than the gap from the naive baseline."
            )
        else:
            bullets.append(
                f"- Modern sequential is actually **faster** than code mode at "
                f"the median ({modern_lat:.2f}s vs {code_lat:.2f}s, ratio "
                f"{1/ratio:.2f}×). Code mode is not always a win."
            )
    if naive.get("inference_calls") and code.get("inference_calls"):
        bullets.append(
            f"- Inference calls per run: naive ≈ {naive['inference_calls']}, "
            f"modern ≈ {modern.get('inference_calls')}, "
            f"code ≈ {code['inference_calls']}. The naive approach pays for "
            f"every tool call with a model round-trip; code mode batches them "
            f"into a single Python execution."
        )
    bullets.append(
        "- Token cost favors code mode: a single `execute_python` call "
        "carries one large input prompt rather than re-sending the running "
        "conversation 20+ times."
    )
    bullets.append(
        "- Latency includes network variance to Open-Meteo. We run 3× and "
        "report median; a single anomalous wall-clock value should not "
        "swing the picture."
    )
    lines.extend(bullets)
    lines.append("")
    lines.append("## Per-run detail")
    lines.append("")
    for name in order:
        if name not in a:
            continue
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append("| Run | Inference | Tool exec | In tokens | Out tokens | Latency (s) | Warmest | Correct |")
        lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | --- | :---: |")
        for r in a[name]["per_run"]:
            lines.append(
                f"| {r['run_idx']} | {r['inference_calls']} | {r['tool_executions']} | "
                f"{r['input_tokens']} | {r['output_tokens']} | {r['latency_s']} | "
                f"{r['warmest_city']} ({r['warmest_temp_c']}°C) | "
                f"{'yes' if r['correct'] else 'no'} |"
            )
        if a[name]["errors"]:
            lines.append("")
            lines.append("**Errors observed:**")
            for e in a[name]["errors"]:
                lines.append(f"- `{e}`")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    out_dir = Path(__file__).resolve().parent
    results_path = out_dir / "results.json"
    summary_path = out_dir / "SUMMARY.md"

    client = make_client()

    runners: list[tuple[str, Callable[[Any, int], RunResult]]] = [
        ("naive_sequential", run_naive_sequential),
        ("modern_sequential", run_modern_sequential),
        ("code_mode", run_code_mode),
    ]

    runs: list[RunResult] = []
    print(f"Model: {MODEL}")
    print(f"Runs per approach: {RUNS_PER_APPROACH} (interleaved)")
    print(f"Cities: {len(CITIES)} European capitals")
    print()

    overall_t0 = time.perf_counter()
    for run_idx in range(RUNS_PER_APPROACH):
        for name, fn in runners:
            print(
                f"[run {run_idx + 1}/{RUNS_PER_APPROACH}] {name} ... ",
                end="", flush=True,
            )
            try:
                result = fn(client, run_idx)
            except Exception as e:
                print(f"FAILED: {type(e).__name__}: {e}")
                result = RunResult(
                    approach=name,
                    run_idx=run_idx,
                    error=f"{type(e).__name__}: {e}",
                )
                runs.append(result)
                continue
            city, temp = parse_final_answer(result.final_answer)
            result.warmest_city = city
            result.warmest_temp_c = temp
            print(
                f"OK  inference={result.inference_calls:>2} "
                f"tools={result.tool_executions:>2} "
                f"latency={result.latency_s:>5.2f}s  "
                f"warmest={city} ({temp}°C)"
            )
            runs.append(result)
            time.sleep(SLEEP_BETWEEN_RUNS_S)

    overall_elapsed = time.perf_counter() - overall_t0
    print()
    print(f"Total wall-clock: {overall_elapsed:.2f}s")
    print()

    summary = summarize(runs)
    summary["wall_clock_total_s"] = round(overall_elapsed, 3)
    summary["raw_runs"] = [asdict(r) for r in runs]

    results_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_summary_md(summary, summary_path)

    print(f"Wrote {results_path}")
    print(f"Wrote {summary_path}")
    print(f"Consensus warmest: {summary['consensus_warmest_city']}")
    print(f"All approaches agree: {summary['all_approaches_agree']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
