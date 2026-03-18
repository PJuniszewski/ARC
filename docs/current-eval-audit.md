# Current Evaluation Audit

## What Exists

### Test Suite (222 tests)

The current test suite validates ARC's pipeline across:

- **Builder pipeline**: ingest, chunk, extract, deduplicate, index, assemble, validate
- **Loader**: selective loading, task-based filtering, evidence graph traversal
- **Models**: serialization, deserialization, round-trip integrity
- **CAS**: content-addressed storage, blob verification
- **Embeddings**: TF-IDF, sentence-transformers, vector search
- **Security**: tamper detection, rollback protection, injection containment
- **Agents**: multi-agent scenarios (Claude Code, Aider, CrewAI)

### RAGAS Evaluation (self-referential)

- **Corpus**: ARC's own 9 documentation files (~3K tokens)
- **Ground truth**: 15 single-hop questions about ARC itself
- **Metrics**: Context Precision 0.939, Context Recall 0.909, Faithfulness 1.000
- **Composite**: 0.910

### Agent Evaluation (30 tasks)

- **Agents**: claude-code, aider, crewai (10 tasks each)
- **Conditions**: Native file search vs ARC selective loading
- **Metrics**: P@k, R@k, NDCG@k, MRR, F1, token efficiency, evidence grounding

## What's Missing

### The self-referential problem

All evaluation uses ARC's own documentation as the corpus. This means:

1. **Tiny corpus**: 9 files, ~3K tokens — too small for selective loading to matter
2. **Author bias**: questions and answers written by the same system that built the archive
3. **No baseline comparison**: RAGAS scores reported without comparing against simpler retrieval
4. **No real-world signal**: unknown whether ARC provides value on actual codebases

### Specific gaps

| Gap | Why it matters |
|-----|---------------|
| No external codebase benchmark | Can't claim ARC beats raw retrieval |
| No ablation study | Don't know if claim extraction helps or hurts |
| No token efficiency comparison | Don't know if ARC actually saves tokens vs chunks |
| No difficulty gradient | All tasks may be trivially easy on a 9-file corpus |
| No cross-file questions | Evidence graph never tested on multi-hop chains |

## What the Large-Repo Benchmark Adds

The large-repo benchmark (`eval/large_repo_tasks/`, `scripts/run_large_repo_benchmark.py`) addresses these gaps:

1. **External corpus**: FastAPI ~15K LOC — not written by ARC authors
2. **4-system comparison**: TF-IDF chunks, vector chunks, hybrid chunks, full ARC
3. **Critical ablation**: System C (hybrid) uses same scoring formula without semantic layer
4. **30 tasks across 6 categories**: easy to hard, single-file to cross-file
5. **Token efficiency measured**: loaded_tokens / total_tokens across all systems
6. **Effect sizes**: Cohen's d between ARC and each baseline
7. **Honest reporting**: if ARC loses, that's a valid finding
