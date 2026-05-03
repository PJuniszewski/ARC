# Tool-Calling Strategy Benchmark

A single-file, reproducible benchmark that compares three approaches to the
same multi-tool-call task:

1. **`naive_sequential`** — one tool per turn, parallel tool use disabled
2. **`modern_sequential`** — same tool, parallel tool use allowed (Claude
   default)
3. **`code_mode`** — single `execute_python` tool; the model writes a Python
   script that fans out the API calls inside a sandbox

The task: **find the warmest of 20 European capital cities by current
temperature** (Warsaw, Berlin, Paris, Madrid, Rome, Amsterdam, Vienna, Prague,
Budapest, Brussels, Lisbon, Athens, Stockholm, Oslo, Helsinki, Copenhagen,
Dublin, Bucharest, Sofia, Riga). Real Anthropic API + real Open-Meteo API,
no mocks.

## What is measured

For each approach, per run:

| Metric | Source |
| --- | --- |
| `inference_calls` | one increment per `client.messages.create` return |
| `tool_executions` | one increment per real Open-Meteo HTTP fetch |
| `input_tokens` | sum of `response.usage.input_tokens` across all turns |
| `output_tokens` | sum of `response.usage.output_tokens` across all turns |
| `latency_seconds` | `time.perf_counter()` from start to final text |
| `final_answer` | the model's stated warmest city + temperature |

Each approach runs `RUNS_PER_APPROACH = 3` times in **interleaved order**
(`1a, 2a, 3a, 1b, 2b, 3b, 1c, 2c, 3c`) so transient API/network slowdowns
don't bias one approach's median. The reported summary uses median/min/max
for latency and mean for the deterministic-ish counts.

## Requirements

- Python 3.10+
- The `anthropic` SDK (`>=0.40`). Already declared in this repo's
  `[project.optional-dependencies] eval` extra.
- An `ANTHROPIC_API_KEY` environment variable.
- Outbound HTTPS access to `api.anthropic.com` and `api.open-meteo.com`.

## Running

From the repository root:

```bash
pip install -e ".[eval]"           # picks up anthropic>=0.40
export ANTHROPIC_API_KEY=sk-ant-...
python eval/tool-calling-bench/benchmark.py
```

Expected runtime: **~3–5 minutes** end-to-end. Naive sequential dominates
the wall clock (one inference call per city ≈ 20 round-trips × 3 runs).

The script writes:

- `eval/tool-calling-bench/results.json` — full structured output (matches the
  schema in the task description plus `wall_clock_total_s` and `raw_runs`)
- `eval/tool-calling-bench/SUMMARY.md` — human-readable Markdown table plus
  a few bullet observations comparing the approaches

Progress is printed as the benchmark runs, e.g.:

```
[run 1/3] naive_sequential ... OK  inference=21 tools=20 latency=33.40s  warmest=Madrid (27.3°C)
```

## Implementation notes

- **Model**: `claude-opus-4-7` (configurable at the top of `benchmark.py`).
- **Tool definitions**:
  - Approaches 1 & 2 share `get_weather(city: str)` — one tool, two
    `tool_choice` configurations.
  - Approach 3 exposes `execute_python(code: str)`; the sandbox preloads
    `get_weather`, the `CITIES` list, and `ThreadPoolExecutor` /
    `as_completed`.
- **Termination**: the tool loop exits when the model's response has no
  `tool_use` blocks (i.e. `stop_reason == "end_turn"` plus an empty
  tool-use list). A `MAX_TURNS = 30` safety cap prevents an unbounded run.
- **Multi-block parallel responses**: when approach 2 returns N `tool_use`
  blocks in a single turn, all N are executed and a single user message with
  N `tool_result` blocks is sent back, each keyed by the matching
  `tool_use_id`.
- **Token counting**: uses `response.usage.input_tokens` /
  `output_tokens`. Cache-read tokens are not separately tracked in v1.
- **Open-Meteo client**: stdlib `urllib.request`, no caching across runs
  (caching would distort the latency picture).

## Sandbox: what it is and is not

The code-mode sandbox uses Python `exec()` with:

- A curated `__builtins__` dict (no `open`, `eval`, `exec`, etc.)
- A pre-injected globals dict containing `get_weather`, `CITIES`,
  `ThreadPoolExecutor`, and `as_completed`
- `contextlib.redirect_stdout` to capture print output

This is **not** a security boundary. The `__import__` builtin is exposed so
the model can write idiomatic `from concurrent.futures import ...` and
similar; a determined prompt could escape via `().__class__.__mro__`. This
is acceptable because we run our own prompts against a model we trust — per
the task spec, the goal is a benchmark, not a production sandbox. Do not
reuse this sandbox for adversarial input.

## Reading the output honestly

The benchmark is designed to be honest about close calls:

- If `modern_sequential` ends up within ~1.5× of `code_mode`, `SUMMARY.md`
  says so explicitly. The realistic gap between an up-to-date Anthropic API
  client and code mode is much smaller than the gap from the naive baseline.
- Per-run breakdowns are always written to `SUMMARY.md` so you can spot
  anomalies (e.g. one slow run dragging the mean).
- All errors are surfaced — a failed run sets `error` on its `RunResult`
  and is excluded from the medians but still listed in `per_run`.

## Files in this directory

| File | Origin |
| --- | --- |
| `benchmark.py` | Source; runs the benchmark. |
| `README.md` | This file. |
| `results.json` | **Generated by `benchmark.py`.** |
| `SUMMARY.md` | **Generated by `benchmark.py`.** |
