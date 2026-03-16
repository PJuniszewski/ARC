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

### `src/arc/models.py`
Data models: Resource, TextUnit, Claim, Decision, EvidencePointer, Layer, Manifest.

### `src/arc/cas.py`
Content-addressed storage: SHA-256 blob store with Merkle verification.

### `src/arc/compressor.py`
Claim deduplication and contested claim exclusion.

---

## Test suite (evaluation)

### `tests/test_bertscore_fidelity.py`
BERTScore-based fidelity (ML extras), n-gram overlap fallback,
factual entailment, contradiction detection, selective loading efficiency.

### `tests/test_ragas_retrieval.py`
RAGAS-style evaluation: context precision, context recall (1-hop + multi-hop),
faithfulness, answer relevancy, composite harmonic-mean, embedder comparison.

### `tests/test_external_ragas.py`
RAGAS evaluation over external corpora (aider, crewai). Parametrized by embedder.
Proves generalization beyond internal corpus.

### `tests/test_comprehensive_scorecard.py`
Unified scorecard: all RAGAS + security metrics in one report. Dual LLM/term-matching
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

