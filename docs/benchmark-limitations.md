# Benchmark Limitations

Honest accounting of what this benchmark does and does not prove.

## Known Limitations

### Single repository

Results are from FastAPI only. Different codebases (larger, multi-language, less documented) may produce different results. FastAPI was chosen for tractability, not representativeness.

### Regex-based extraction

ARC's claim extraction uses regex patterns, not an LLM. Extracted claims may miss nuanced relationships that an LLM extractor would capture. This is a known v0 limitation.

### Small task set

30 tasks across 6 categories. Statistical power is limited — effect sizes below Cohen's d = 0.3 may not be detectable. Each category has only 5 tasks.

### Self-authored tasks

Tasks were written by reviewing FastAPI source code, not by surveying real developer questions. Task difficulty and relevance may not reflect actual developer needs.

### English only

All tasks, ground truth, and evaluation are in English. No assessment of multilingual code or documentation.

### Ground truth quality

Ground truth answers were written from source code reading, not verified by FastAPI maintainers. Some answers may be incomplete or contain inaccuracies about internal behavior.

### Embedding model dependency

Results depend on the specific embedding model (all-MiniLM-L6-v2) and TF-IDF configuration (256 dims). Different models may change relative performance.

### No runtime cost comparison

The benchmark measures retrieval quality but not latency or memory usage. ARC's claim extraction and evidence graph add build-time cost that baselines avoid.

### RAGAS LLM judge limitations

RAGAS metrics use Claude as a judge. LLM judges have known biases (verbosity preference, position bias). The RAGAS scores are suggestive, not definitive.

## What This Benchmark Does NOT Prove

- That ARC is production-ready
- That ARC generalizes to all codebases
- That ARC's semantic layer is the best possible design
- That the chosen metrics capture what matters to real developers
- That the task difficulty distribution matches real-world needs

## What This Benchmark CAN Show

- Whether ARC provides measurable token efficiency vs raw chunk retrieval
- Whether the evidence graph helps on cross-file questions
- Whether claim extraction adds value or noise compared to hybrid chunk scoring
- Whether ARC's provenance tracking is a differentiator
- Relative performance of 4 retrieval strategies on one real codebase

## Mitigation

- Results are always reported with confidence intervals and effect sizes
- If ARC loses to baselines, this is reported as a valid and important finding
- The benchmark is reproducible: pinned repo version, deterministic chunking, open tasks
- Additional repos can be added in future iterations
