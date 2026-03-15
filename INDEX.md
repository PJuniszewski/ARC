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
- semantic compression
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

## Test suite (evaluation)

### `tests/test_bertscore_fidelity.py`
BERTScore-based compression fidelity (ML extras), n-gram overlap fallback,
factual entailment, contradiction detection, cost/quality tradeoff.

### `tests/test_ragas_retrieval.py`
RAGAS-style evaluation: context precision, context recall, faithfulness,
answer relevancy, composite harmonic-mean score.

### `tests/test_evaluation_harness.py`
End-to-end MVP harness (7 steps from evaluation-plan.md), build/load timing,
real-world agent scenarios (code understanding, security audit, debugging),
incremental update, multi-session continuity.

### `tests/test_security_evaluation.py`
Exhaustive tamper detection rate, manifest tamper, rollback detection,
poisoned-source containment, prompt injection tracing, security scorecard.

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

