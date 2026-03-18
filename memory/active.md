# Active — Operational Index

> What matters right now. Updated every session.

---

## In Progress

| Task | Since | Why | Files involved |
|------|-------|-----|----------------|
| Signatures & attestations | — | Trust model spec exists but no implementation yet | `docs/provenance-signing.md`, `docs/security-model.md` |
| OCI artifact mapping | — | Archive is directory-based; OCI transport not implemented | `docs/spec/arc-format.md` |
| Multi-file diversity for security_config | 2026-03-18 | security_config recall 0.600 vs hybrid 0.700; root cause is multi-file evidence diversity loss, not reasoning | `src/arc/refinement.py` |

---

## Blocked

| Item | Waiting on | Since |
|------|-----------|-------|
| — | — | — |

---

## Recently Completed

| Item | When | Commit | Lesson |
|------|------|--------|--------|
| Reasoning boost for refinement | 2026-03-18 | — | Recall=0.660 (0.5% below hybrid, d=-0.014 negligible), 65.1% token reduction. decisions_constraints 0.400→0.500. Zero regressions. New module `src/arc/reasoning.py`. |
| ARC v2 passthrough + task-aware modes | 2026-03-18 | — | Recall=0.643 (3.0% below hybrid, d=-0.079 negligible), 65.6% token reduction, traceability=1.0, debuggability=0.866. Task-aware refinement modes + raw chunk passthrough lane. Surpasses hybrid on cross_file (0.810 vs 0.680) and implementation (0.600 vs 0.550). |
| ARC v2 post-retrieval refinement (hybrid_arc v1) | 2026-03-18 | — | Recall=0.568 (14.3% below hybrid), 73.4% token reduction, traceability=1.0, debuggability=0.817. Code/docs classifier + claim extraction + token budget. Failure: decisions_constraints category (reasoning not captured by claim regex). |
| Large-repo benchmark execution | 2026-03-17 | — | Full run: 30 tasks × 4 systems. ARC recall=0.388 vs hybrid=0.663 (Cohen's d=-1.06). ARC beats TF-IDF (+0.39). Root cause: 809 markdown claims dilute 45 Python code claims. Traceability=1.0 is unique ARC advantage. |
| Large-repo benchmark infrastructure (eval/, scripts/, Makefile, docs) | 2026-03-17 | — | 30 tasks, 4 retrieval systems (TF-IDF/vector/hybrid/ARC), lexical+RAGAS metrics, CI smoke job, Makefile targets |
| External corpus RAGAS eval, scorecard flip, multi-hop BFS fix | 2026-03-17 | `b6e18b7` | Hybrid OR gate (token overlap OR vector score) fixes sentence-transformers regression in BFS. Always compute both LLM and term-matching to keep scorecard honest. External corpora (aider/crewai) composite 0.68. |
| Track agent eval + fixtures + roundtrip tests | 2026-03-17 | `adbe2f5` | 30-task behavioral evaluation across 3 agent corpora (claude-code, aider, crewai) with IR metrics and effect sizes |
| Production quality gate + structured logging | 2026-03-16 | `d2ea8d6` | Sentence-transformers composite 0.91, production gate thresholds calibrated |
| Sentence-transformers as production embedder | 2026-03-16 | `3cc21be` | all-MiniLM-L6-v2 (384d) with TF-IDF fallback; embedder state serialized in archive for aligned restore |
| Section heading boost + hard cap | 2026-03-16 | `73c140e` | Heading context enrichment at extraction time is critical for retrieval — preserves topical vocabulary |
| LLM judge (Claude Haiku) for RAGAS metrics | 2026-03-16 | `ee98f37` | LLM precision 0.77 vs term-matching 0.94 — term-matching flatters; LLM is honest |
| Evaluation harness implementation | 2026-03-15 | — | BERTScore fidelity, RAGAS retrieval metrics, end-to-end harness, security evaluation |
| Initial zip upload with project scaffold | 2026-03-15 | `27c1c8a` | Document-first design — CLAUDE.md, MEMORY.md, INDEX.md as separate concerns (ADR-0003) |

---

## Decisions Resolved (by code)

| Question | Resolution | Where |
|----------|-----------|-------|
| Minimum viable semantic unit | Claim (with evidence pointers to source units) | `src/arc/models.py`, `src/arc/extractor.py` |
| Embeddings in archive | Full vector store serialized in archive (ids, vectors, texts, embedder state) | `src/arc/embeddings.py` VectorStore.to_dict() |
| Archive representation | Directory layout with CAS (`blobs/sha256/<digest>`, `manifest.json`, `refs/`, `meta/`) | `src/arc/cas.py` |
| Selective load policy | Hybrid vector + keyword runtime scoring with evidence graph expansion | `src/arc/loader.py` _filter_by_task() |
| ~~Semantic compression~~ | No lossy compression in builder (ADR-0004). Selective loading is loader's job. | ADR-0004 |

## Decisions Still Pending

| Question | Context | Options considered |
|----------|---------|-------------------|
| Trust boundary for builder | Who/what do we trust produced the archive? | Human-reviewed, builder-signed, multi-party attested |
| Single-file packaging | Should .arc support tarball/zip in addition to directory? | Directory only, tar.gz, OCI image, all three |
