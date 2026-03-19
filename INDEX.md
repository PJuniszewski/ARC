# INDEX.md

This file is the navigation map for the repo.
It answers one question fast:

**Where should I look right now?**

---

## Top-level files

### `README.md`
Use for:
- project overview
- onboarding
- goals and scope

### `CLAUDE.md`
Use for:
- Claude Code operating rules
- repo-specific behavior
- design guardrails

### `MEMORY.md`
Use for:
- current state
- open questions
- recent assumptions
- active priorities

### `INDEX.md`
Use for:
- navigation only
- file discovery
- finding the right source of truth quickly

### `LICENSE`
Apache-2.0 license.

### `CONTRIBUTING.md`
Contribution rules (mirrors `docs/contributing.md`).

---

## Core docs

### `docs/architecture.md`
Read when you need:
- system overview
- major components
- data flow
- build vs load split

### `docs/repo-structure.md`
Read when you need:
- directory purpose
- where future code should live
- organizational rules

### `docs/roadmap.md`
Read when you need:
- milestone planning
- sequencing
- what comes now vs later

### `docs/evaluation-plan.md`
Read when you need:
- benchmarks
- test strategy
- fidelity and security evaluation

### `docs/security-model.md`
Read when you need:
- threat model
- trust boundaries
- prompt injection and poisoning considerations

### `docs/provenance-signing.md`
Read when you need:
- signatures
- attestations
- update trust model

### `docs/builder-pipeline.md`
Read when you need:
- ingestion
- extraction
- deduplication
- archive build stages

### `docs/loader-runtime.md`
Read when you need:
- load flow
- selective mount
- runtime behavior

### `docs/contributing.md`
Read when you need:
- contribution rules
- documentation discipline
- ADR expectations

---

## Specs

### `docs/spec/arc-format.md`
Primary source for:
- what an `.arc` is
- package layout
- required sections
- compatibility principles

### `docs/spec/manifest-schema.md`
Primary source for:
- manifest fields
- versioning
- layer references
- mount rules

### `docs/spec/semantic-model.md`
Primary source for:
- source units
- claims
- decisions
- evidence model

### `docs/spec/cli-contract.md`
Primary source for:
- command surface
- expected inputs and outputs
- UX contract for tool users

---

## ADRs

### `docs/adr/ADR-0001-project-scope.md`
Defines initial scope and anti-scope.

### `docs/adr/ADR-0002-artifact-first-design.md`
Defines why ARC is artifact-first rather than runtime-memory-first.

### `docs/adr/ADR-0003-separate-memory-and-index.md`
Defines why `MEMORY.md` and `INDEX.md` are separate.

### `docs/adr/ADR-0004-no-lossy-compression.md`
Defines why the builder preserves full fidelity (no lossy compression). Selective loading is the loader's job.

### `docs/adr/ADR-0005-operational-layers.md`
Defines scope expansion: 3 optional operational layer types (tools, policy, workflow) for packaging agent capabilities alongside knowledge.

Use ADRs when something is accepted and should stop being debated casually.

---

## Research docs

### `docs/research/market-landscape.md`
Use for:
- related tools
- what exists vs what is missing

### `docs/research/source-notes.md`
Use for:
- distilled notes from papers, docs, and standards
- not final product truth

### `docs/research/open-questions.md`
Use for:
- unresolved research threads
- investigation backlog

---

## Memory system (cross-session knowledge)

### `memory/MEMORY.md`
Entry point — routing table to all knowledge topic files.
Read this first at session start.

### `memory/active.md`
Operational index — current WIP, blockers, recent completions, pending decisions.

### `memory/scratchpad.md`
Temporary working memory — intermediate results, cleared after work.

### `memory/architecture.md`
Architecture patterns and decisions with trajectory (when, why, impact).

### `memory/spec-knowledge.md`
Format and technical facts about .arc — manifest, blobs, CAS, semantic model.

### `memory/gotchas.md`
Known pitfalls and workarounds — problem, reason, fix, first-hit date.

### `memory/research.md`
Research findings and prior art with trajectory.

---

## Claude command docs

### `.claude/commands/start-session.md`
Use to bootstrap a productive Claude session with memory loading.

### `.claude/commands/update-memory.md`
Use to persist knowledge for future sessions after work.

### `.claude/commands/end-session.md`
Use for session closeout — update active state, clear scratchpad.

### `.claude/commands/write-adr.md`
Use to create ADRs consistently.

---

## Planning docs

### `plans/mvp-plan.md`
Use for:
- immediate execution plan
- MVP milestones

### `plans/backlog.md`
Use for:
- unscheduled work
- future ideas
- tasks not yet promoted into roadmap

---

## Templates

### `templates/adr-template.md`
Template for new ADRs.

### `templates/claim-template.md`
Template for semantic claim objects.

### `templates/decision-template.md`
Template for decision objects.

---

## Source code

### `src/arc/builder.py`
8-stage build pipeline: ingest → normalize → chunk → extract → deduplicate → index → assemble → validate.

### `src/arc/loader.py`
Selective loading with hybrid vector + keyword scoring, evidence graph expansion, multi-hop BFS.

### `src/arc/embeddings.py`
Dual embedder: sentence-transformers (all-MiniLM-L6-v2) with TF-IDF fallback. VectorStore with cosine search.

### `src/arc/extractor.py`
Rule-based claim/decision extraction with section heading enrichment and injection detection.
Operational extraction: tools, policies, workflows from YAML/JSON agent configs.

### `src/arc/models.py`
Data models: Resource, TextUnit, Claim, Decision, EvidencePointer, ToolDeclaration, PolicyRule, WorkflowStep, Layer, Manifest.

### `src/arc/cas.py`
Content-addressed storage: SHA-256 blob store with Merkle verification.

### `src/arc/compressor.py`
Claim deduplication and contested claim exclusion.

### `src/arc/reasoning.py`
Reasoning detection: causal connectives, decision verbs, contrastive markers, ADR heading patterns. Used by refinement to boost reasoning-bearing chunks.

### `src/arc/refinement.py`
Post-retrieval refinement: task-aware mode detection, raw chunk passthrough lane, code/docs classification, claim extraction on docs, reasoning boost, code minimum guarantee, token budgeting, evidence map.

### `src/arc/scope.py`
Scope reduction for large repos: heuristic path/symbol/directory matching. `build_repo_metadata()` and `infer_scope()` — no ML, no embeddings.

### `src/arc/retrieval_pipeline.py`
Two-phase scoped retrieval: scope reduction → hybrid scoring on scoped chunks → ARC refine. `ScopedRetrievalPipeline` orchestrator for 100k+ LOC repos.

### `src/arc/cache.py`
File-system cache for chunking and embedding artifacts. Content-addressed by source directory hash. Off by default.

### `src/arc/config.py`
Named constants: stop words, builder defaults, loader thresholds, scoped retrieval limits.

### `src/arc/diff.py`
Structural and semantic diff between two archives.

### `src/arc/cli.py`
CLI entry point: `arc build`, `arc inspect`, `arc verify`, `arc diff`, `arc restore`.

### `src/arc/py.typed`
PEP 561 marker — indicates the package ships inline type annotations.

---

## Large-Repo Benchmark

### `eval/large_repo_tasks/fastapi/REPO_CONFIG.json`
FastAPI snapshot config: repo URL, pinned SHA, exclude patterns.

### `eval/large_repo_tasks/fastapi/tasks.json`
30 FastAPI benchmark tasks (6 categories x 5) with ground truth answers, keywords, required facts.

### `eval/large_repo_tasks/fastapi/README.md`
FastAPI task design rationale, category definitions, authoring methodology.

### `eval/large_repo_tasks/django/REPO_CONFIG.json`
Django snapshot config: repo URL, tag 5.1, exclude patterns (~300K LOC).

### `eval/large_repo_tasks/django/tasks.json`
30 Django benchmark tasks (6 categories x 5) — ORM, middleware, templates, auth, admin, security.

### `eval/baselines/__init__.py`
Package exports for baseline retrieval systems.

### `eval/baselines/common.py`
Shared infrastructure: `RetrievalResult` dataclass, `chunk_snapshot()`, keyword utilities.

### `eval/baselines/tfidf_baseline.py`
Baseline A: TF-IDF chunk retrieval — no semantic layer, no graph.

### `eval/baselines/vector_baseline.py`
Baseline B: Vector chunk retrieval — sentence-transformers, no semantic layer.

### `eval/baselines/hybrid_baseline.py`
Baseline C (critical ablation): Hybrid chunk retrieval — vector + keyword + heading boost, no claim extraction or evidence graph.

### `eval/baselines/hybrid_refined.py`
Baseline E: Hybrid + ARC post-retrieval refinement — fetches 30 chunks via hybrid scoring, refines with code/docs classification, claim extraction, token budgeting.

### `eval/baselines/scoped_refined.py`
Baseline F (EXPERIMENTAL): Scoped + ARC refinement — two-phase retrieval with scope reduction. Works on small repos (<30K LOC), fails at scale (Django recall 0.242). Use HybridRefinedRetriever instead.

### `scripts/setup_fastapi_snapshot.py`
Clones and freezes a repository at pinned version for benchmarking. Accepts `--config` for repo-agnostic setup (default: FastAPI). Works for any repo via config.

### `scripts/run_large_repo_benchmark.py`
Main runner: ARC vs 5 baselines (+ scoped_arc) on tasks. Accepts `--repo` (fastapi, django). Modes: smoke/full/ragas.

### `docs/current-eval-audit.md`
Audit of existing evaluation: what exists and what the large-repo benchmark adds.

### `docs/benchmark-large-repo-plan.md`
Full methodology for large-repo benchmark.

### `docs/benchmark-repo-choice.md`
Why FastAPI was chosen over Django, LangChain, nanoclaw.

### `docs/benchmark-limitations.md`
Honest limitations: single repo, regex extraction, small task set, English only.

### `docs/demo-script.md`
5-step reproduction script for skeptical engineers.

### `docs/arc_v2_failures.md`
Failure analysis for ARC v2 post-retrieval refinement (v1): per-task recall losses, root causes, token compression by category.

### `docs/hybrid_arc_recall_failure_analysis.md`
Detailed per-task failure matrix with 7 failure modes, root cause analysis by category, prescribed fixes (passthrough lane, task-aware modes, code guarantee).

### `docs/reasoning_fix_report.md`
Reasoning boost fix: before/after metrics, per-task deltas, token impact, assessment.

### `docs/positioning_arc_v2.md`
Honest positioning memo: what ARC is/isn't, where it wins/loses vs hybrid, benchmark evidence, recommended use cases.

### `docs/demo_arc_v2.md`
Side-by-side demo of hybrid vs hybrid_arc output on 3 representative tasks.

### `docs/large_repo_scaling_plan.md`
Scaling plan for 100k+ LOC repos: scoped two-phase retrieval architecture, candidate repos, success criteria, failure modes.

### `docs/large_repo_positioning.md`
Honest assessment of where scoped ARC will and won't work at scale. Includes Django benchmark results showing scoped_arc failure. Assumptions, failure modes, non-claims.

### `docs/benchmark-fastapi-vs-django.md`
Polished comparison report: hybrid_arc across FastAPI (15K LOC) and Django (155K LOC). System tables, per-category analysis, cross-file bottleneck diagnosis, scoped_arc assessment, product recommendation.

### `docs/demo-django.md`
5-step reproduction for Django benchmark. Setup, smoke test, full run, interpretation guide. Approximate timings and expected outputs.

### `reports/large-repo-summary-{repo}.md`
Full benchmark results with analysis: system comparison, per-category breakdown, effect sizes, root cause diagnosis. Per-repo (fastapi, django).

### `reports/large-repo-results-{repo}.json`
Per-task detail with individual scores. Per-repo (fastapi, django).

### `Makefile`
Targets: test, lint, benchmark-setup, benchmark-setup-django, benchmark-smoke, benchmark-smoke-django, benchmark-full, benchmark-full-django, benchmark-ragas, clean.

---

## CI / GitHub

### `.github/workflows/test.yml`
GitHub Actions CI: Python 3.10-3.13 matrix, ruff lint, pytest (non-ML/LLM). Optional benchmark-smoke on PRs.

---

## Test suite (evaluation)

### `tests/test_fidelity_metrics.py`
Fidelity metrics: real BERTScore (ML extras, excluded from CI), n-gram overlap fallback,
factual entailment, contradiction detection, selective loading efficiency.

### `tests/test_ragas_eval.py`
**Primary evaluation.** Real RAGAS metrics using Claude as LLM judge.
Context precision, recall, faithfulness, response relevancy — all semantically evaluated.
Requires `pip install arc-context[eval]` + `ANTHROPIC_API_KEY`.

### `tests/test_retrieval_metrics.py`
CI smoke tests: keyword-based context precision, recall, faithfulness, term coverage.
Zero-dependency lexical proxies that run without an LLM. Not a substitute for RAGAS.

### `tests/test_external_retrieval.py`
Lexical retrieval metrics over external corpora (aider, crewai). Parametrized by embedder.
Small fixture dirs (~3 files each) — basic generalization check, not comprehensive.

### `tests/test_comprehensive_scorecard.py`
Unified scorecard: all retrieval + security metrics in one report. Dual LLM/term-matching
reporting. Production quality gate for sentence-transformers.

### `tests/test_agent_eval.py`
Behavioral evaluation: 30 tasks × 3 agents (claude-code, aider, crewai).
IR metrics (Precision@k, Recall@k, NDCG, MRR, F1), effect sizes (Cohen's d).

### `tests/test_evaluation_harness.py`
End-to-end MVP harness (7 steps from evaluation-plan.md), build/load timing,
real-world agent scenarios (code understanding, security audit, debugging),
incremental update, multi-session continuity.

### `tests/test_security_evaluation.py`
Exhaustive tamper detection rate, manifest tamper, rollback detection,
poisoned-source containment, prompt injection tracing, security scorecard.

### `tests/test_operational_extraction.py`
Operational extraction: tools, policies, workflows from crewai/aider fixtures.
Builder, loader, diff integration for operational layers.

### `tests/test_roundtrip.py`
Archive roundtrip: build → verify → load → restore sources → diff.

---

## Fast paths

### I want to understand the whole project
Read:
1. `README.md`
2. `MEMORY.md`
3. `docs/architecture.md`
4. `docs/spec/arc-format.md`

### I want to make a format change
Read:
1. `docs/spec/arc-format.md`
2. `docs/spec/manifest-schema.md`
3. relevant ADRs
4. `docs/security-model.md`

### I want to change trust / signing
Read:
1. `docs/provenance-signing.md`
2. `docs/security-model.md`
3. relevant ADRs

### I want to update project state
Read and update:
1. `MEMORY.md`
2. maybe `plans/backlog.md`
3. maybe ADRs if decision became durable

