# Active — Operational Index

> What matters right now. Updated every session.

---

## In Progress

| Task | Since | Why | Files involved |
|------|-------|-----|----------------|
| Signatures & attestations | — | Trust model spec exists but no implementation yet | `docs/provenance-signing.md`, `docs/security-model.md` |
| OCI artifact mapping | — | Archive is directory-based; OCI transport not implemented | `docs/spec/arc-format.md` |

---

## Blocked

| Item | Waiting on | Since |
|------|-----------|-------|
| — | — | — |

---

## Recently Completed

| Item | When | Summary |
|------|------|---------|
| hybrid_arc production validation | 2026-03-18 | FastAPI recall 0.660 (d=-0.014), Django recall 0.762 (d=-0.291). Traceability 1.0, 65%+ token reduction. |
| scoped_arc (experimental) | 2026-03-18 | Fails at scale (Django recall 0.242). Demoted to experimental, not in default benchmarks. |
| Large-repo benchmark | 2026-03-17 | 30 tasks × 5 systems on FastAPI + Django. Reports in `reports/`, comparison in `docs/benchmark-fastapi-vs-django.md`. |
| Evaluation harness + quality gate | 2026-03-15–16 | 233 tests, RAGAS + security + behavioral eval, sentence-transformers composite 0.91. |
| Repo cleanup | 2026-03-19 | Removed 10 stale docs, consolidated demo-django into large_repo_positioning. |

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
