# Large-Repo Benchmark Plan

## Core Question

Does ARC provide measurable advantage over raw chunk retrieval for coding-agent questions on a real ~15K LOC repository?

## Methodology

### Repo Under Test

FastAPI 0.115.0 (~15K LOC Python). Pinned to specific commit SHA. Clone via `scripts/setup_fastapi_snapshot.py`. Excludes `tests/` and `docs_src/`.

See [benchmark-repo-choice.md](benchmark-repo-choice.md) for selection rationale.

### Retrieval Systems (4)

All systems start from identical chunks produced by ARC's chunkers (`_chunk_markdown`, `_chunk_python`, `_chunk_generic`).

| System | Embedding | Scoring | Semantic Layer | Graph |
|--------|-----------|---------|---------------|-------|
| A: TF-IDF chunks | TfidfEmbedder(256) | Top-k cosine | None | None |
| B: Vector chunks | all-MiniLM-L6-v2(384) | Top-k cosine | None | None |
| C: Hybrid chunks | all-MiniLM-L6-v2 | Vector + keyword + heading | None | None |
| D: Full ARC | Same as C | Same as C | Claim extraction + dedup | Evidence graph BFS |

**System C is the critical ablation.** It uses the same hybrid scoring formula as ARC's loader (vector + 0.3 * keyword + heading boost) but on raw chunks, no claim extraction, no evidence graph. If ARC beats C, the advantage comes from the semantic layer.

### Tasks (30)

6 categories x 5 tasks. See `eval/large_repo_tasks/tasks.json`.

- Architecture (5): system design, lifecycle, dependency injection
- Feature behavior (5): runtime behavior of specific features
- Implementation location (5): where specific logic lives
- Cross-file reasoning (5): multi-hop chains spanning 3+ files
- Decisions/constraints (5): design rationale
- Security/config (5): security and configuration patterns

Constraints: 19 require cross-file reasoning, 14 are hard difficulty, 5 marked for CI smoke.

### Metrics

**Tier 1 — Lexical (CI, zero cost):**

- Context precision: fraction of top-k containing relevant facts
- Context recall: fraction of required facts found in top-k
- Keyword precision/recall: keyword overlap metrics
- Token efficiency: `1 - loaded_tokens / total_tokens`
- Evidence traceability: `1.0` if ARC (has provenance), `0.0` for baselines

**Tier 2 — RAGAS (local, ~$3-10):**

- Context Precision (Claude LLM-judged)
- Context Recall (Claude LLM-judged)
- Faithfulness (Claude LLM-judged)
- Response Relevancy (Claude + embeddings)

**Statistical:**

- Cohen's d effect size: ARC vs each baseline
- Per-category and per-difficulty breakdowns

## Execution

```bash
# Setup (~30s, one-time)
python scripts/setup_fastapi_snapshot.py

# CI smoke (5 tasks, ~30s)
python scripts/run_large_repo_benchmark.py --mode=smoke

# Full lexical (30 tasks, ~2-5 min)
python scripts/run_large_repo_benchmark.py --mode=full

# RAGAS (30 tasks + Claude judge, ~$3-10)
ANTHROPIC_API_KEY=... python scripts/run_large_repo_benchmark.py --mode=ragas
```

## Success Criteria

| Outcome | Threshold |
|---------|-----------|
| Token efficiency win | >= 40% reduction, recall >= best baseline |
| Cross-file win | Cohen's d > 0.5 on cross-file category |
| Traceability win | 100% for ARC, 0% for baselines |
| Failure | ARC doesn't beat hybrid chunks — report honestly |

## Limitations

See [benchmark-limitations.md](benchmark-limitations.md).
