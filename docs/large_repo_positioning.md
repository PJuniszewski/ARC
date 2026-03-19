# Large Repo Positioning: Honest Assessment

## Why naive ARC won't work at 300K LOC

Full-corpus ARC retrieval fails at scale for measurable reasons:

1. **Claim explosion**: At 15K LOC, the builder extracts ~850 claims. At 300K LOC, expect ~15,000+. Vector search precision degrades as the index grows — more noise neighbors, lower signal-to-noise in top-k results.

2. **Markdown dilution is structural**: In FastAPI, 809 markdown claims outnumber 45 Python code claims 18:1. This ratio is characteristic of well-documented repos. At scale, the problem compounds — more docs, more dilution.

3. **Token budget is finite**: The refinement pipeline targets ~3700 tokens. At 15K LOC this covers a meaningful fraction of the codebase. At 300K LOC, the same budget covers 0.1% — any retrieval noise wastes irreplaceable budget.

4. **BFS evidence graph explodes**: Multi-hop graph traversal with 30-node cap is manageable at 400 chunks. At 4000+ chunks, BFS visits many irrelevant nodes that happen to share keywords.

## Why scoped ARC should work

Scope reduction eliminates noise *before* retrieval, not after:

1. **Query signals are informative**: Developer queries almost always reference specific files, functions, directories, or domain concepts. "How does dependency injection work?" gives us "dependency" → `dependencies/` → 5 files, not 400.

2. **Code clusters by directory**: Most repos organize related code by directory. Scope inference exploits this for free — no ML needed.

3. **Phase 1 is O(n) and deterministic**: String matching against paths/symbols/directories completes in microseconds. No embedding computation, no model loading.

4. **Existing hybrid scoring works within scope**: The same scoring formula that achieves 0.660 recall on FastAPI should work equally well (or better) when operating on a pre-filtered, relevant subset.

5. **refine() is unchanged**: No modifications to the post-retrieval pipeline that provides traceability and token reduction.

## Assumptions that must hold

1. **Query gives enough signal for scope heuristics**: The query must contain path fragments, symbol names, directory keywords, or domain terms that map to repo structure. Pure conceptual queries ("what is the overall philosophy?") provide weak scope signal.

2. **Relevant code clusters by directory**: If important code is scattered uniformly across 100 directories with no structural grouping, scope inference provides no benefit. Most real codebases are not like this.

3. **Scope fallback is safe**: When heuristics find <5 files, we fall back to full corpus. This must not introduce false confidence — the fallback is an admission that scope failed.

## Where it can still fail

1. **Highly distributed concerns**: Cross-cutting features (logging, error handling, auth middleware) touch many files across many directories. No single scope captures them.

2. **Queries with no path/symbol hints**: "Why is the app slow?" gives no structural signal. Scope inference degenerates to keyword matching against directory names, which may not help.

3. **Monorepos with flat structure**: If all 200 files live in a single `src/` directory with no subdirectories, directory-based scope is useless.

4. **Non-Python symbol extraction**: Current symbol extraction scans for `def ` / `class ` patterns. Go, Rust, Java have different syntax. Extensible via chunker `kind` tag but not implemented for v0.

5. **False scope confidence**: Scope might match the *name* of a module without matching the *intent*. "security" matches `security/` but the answer might live in `middleware/auth.py`.

## Django Benchmark Results (155K LOC)

scoped_arc was tested on Django (155K LOC, 879 Python files, 30 tasks):

| System | Context Recall | Notes |
|--------|---------------|-------|
| hybrid | 0.820 | Best overall recall |
| hybrid_arc | 0.762 | 7% gap, full traceability |
| scoped_arc | 0.242 | **Fails at scale** |

### Why scoped_arc fails on Django

1. **Deep directory structure**: Django's code lives 4-5 levels deep (`django/db/models/sql/compiler.py`). Heuristic directory matching produces too many false positives or misses entirely.
2. **Cross-cutting concerns dominate**: 25/30 tasks require cross-file reasoning. Scope inference can't capture middleware chains, ORM → SQL → DB backend flows.
3. **Keyword → directory mapping is ambiguous**: "auth" matches `django/contrib/auth/`, but relevant code also lives in `django/middleware/`, `django/core/handlers/`, etc.

### Decision: scoped_arc is EXPERIMENTAL

- Not included in default benchmark runs
- Available via `--systems scoped_arc` for research
- Use hybrid_arc (HybridRefinedRetriever) for production

### hybrid_arc at scale

hybrid_arc works on Django without scope inference. The recall gap vs hybrid (7%, d=-0.291) is a small effect size, acceptable given the traceability and debuggability advantages. Cross-file recall is the main area for improvement, addressed by expanded token budget and neighboring-file boosting in the refinement pipeline.

### Metric interpretation guide

| Metric | What it measures | Good threshold |
|--------|-----------------|----------------|
| context_recall | Fraction of required facts found | ≥0.700 |
| token_efficiency | 1 - (loaded/total tokens) | ≥0.995 |
| evidence_traceability | All items have source pointers | 1.000 |
| debuggability | File diversity + span specificity | ≥0.900 |

**Where hybrid_arc wins on Django:**
- Traceability: 1.000 vs 0.000 — every output item traceable to source file + line
- Debuggability: ~0.937 vs 0.000 — inspect evidence chains when agent gets wrong answer
- Token reduction: loads ~3K tokens vs hybrid's ~5.3K

**Where hybrid_arc loses on Django:**
- Cross-file recall: some tasks need 5K-16K tokens spanning 3-5 files; the token budget can't fit everything
- Overall recall gap: ~7% below hybrid (d = -0.291, small effect size)

For tasks where you need every detail from every file, use hybrid. For tasks where you need to know *where* the information came from, use hybrid_arc.

## What we're not claiming

- This is NOT a general-purpose code search engine
- This does NOT replace language-server-grade symbol resolution
- This does NOT guarantee recall improvement (scope can be wrong)
- scoped_arc is NOT production-ready (fails at 155K LOC, experimental only)
- This does NOT solve the fundamental limits of regex-based claim extraction
