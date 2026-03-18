# Demo Script: Large-Repo Benchmark

5-step reproduction for a skeptical engineer.

## Prerequisites

```bash
# Python 3.10+, git
pip install -e ".[dev]"
# Optional for RAGAS: pip install -e ".[eval]"
```

## Step 1: Clone FastAPI Snapshot

```bash
python scripts/setup_fastapi_snapshot.py
```

Expected output:
```
Cloning https://github.com/fastapi/fastapi.git at tag 0.115.0...
Excluding: tests/
Excluding: docs_src/
Snapshot ready: eval/large_repo_data/fastapi
  Python files: ~80
  Markdown files: ~150
  Total Python LOC: ~15000
```

## Step 2: Run Smoke Test (5 tasks, ~30 seconds)

```bash
python scripts/run_large_repo_benchmark.py --mode=smoke
```

Expected output:
```
Smoke mode: 5 tasks
Building retrieval indices...
  [A] TF-IDF chunks...
  [B] Vector chunks...
  [C] Hybrid chunks...
  [D] Full ARC...
  Index build time: 15.2s
Evaluating 5 tasks x 4 systems...
```

## Step 3: Inspect Results

```bash
cat reports/large-repo-summary.md
```

Look for:
- ARC token efficiency > baseline token efficiency
- ARC evidence traceability = 1.000, baselines = 0.000
- Context recall: compare ARC vs hybrid (the critical ablation)

## Step 4: Full Benchmark (30 tasks, ~2-5 minutes)

```bash
python scripts/run_large_repo_benchmark.py --mode=full
```

Check:
- Per-category breakdown (cross-file tasks should favor ARC)
- Effect sizes (Cohen's d > 0.5 is meaningful)
- Token efficiency (ARC should load fewer tokens)

## Step 5: RAGAS Evaluation (optional, requires API key)

```bash
ANTHROPIC_API_KEY=sk-... python scripts/run_large_repo_benchmark.py --mode=ragas
```

Adds LLM-judged metrics:
- Context Precision: are retrieved items relevant?
- Context Recall: does retrieved context cover the answer?
- Faithfulness: are responses grounded in context?

## Interpreting Results

### ARC wins if:

- Token efficiency >= 40% better than best baseline
- Cohen's d > 0.5 on cross-file tasks
- Evidence traceability = 100% (baselines = 0%)

### ARC loses if:

- Hybrid chunks (System C) matches or beats ARC on recall
- Claim extraction adds noise (lower precision than raw chunks)
- Evidence graph doesn't help on cross-file questions

### Either way:

The honest finding is documented in `reports/large-repo-summary.md`.
