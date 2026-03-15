# ARC Archive

Portable, verifiable, semantic archives for AI agents.

ARC is a project to package agent context as a first-class artifact instead of rebuilding it from scratch on every run. The goal is to turn scattered sources like repositories, docs, ADRs, tickets, policies, indexes, and embeddings into a portable `.arc` package that can be versioned, diffed, signed, distributed, and loaded selectively.

This repo is set up for work inside Claude Code.

---

## Why this exists

Current agent stacks usually do one of these:

- keep short-lived runtime state
- stuff more tokens into prompts
- rely on retrieval over raw sources
- bolt on memory after the fact

That works until it does not.

The failure mode is always the same:

- too much context
- poor recall
- unstable behavior
- repeated rediscovery
- no portable source of truth
- weak provenance and trust

ARC attacks that directly.

---

## Core idea

Instead of:

```text
repo + docs + tickets + policies + embeddings
-> retrieval at runtime
-> best effort context assembly
```

Use:

```text
repo + docs + tickets + policies + embeddings
-> ARC builder
-> semantic layers + manifest + attestations
-> project.arc
-> agent loads only what it needs
```

ARC is closer to:

- OCI artifact for agent context
- Merkleized knowledge package
- policy-aware memory bundle
- portable context runtime

It is **not** just a zip file with markdown.

---

## Project goals

### Product goals

- define a practical `.arc` format
- support deterministic build / verify / load / diff flows
- make archives portable across runtimes and models
- preserve provenance and trust
- support selective loading instead of all-or-nothing context

### Technical goals

- content-addressed storage
- manifest-driven composition
- semantic claims + decisions + policies + indexes
- incremental updates and diffs
- signatures, attestations, rollback protection
- sandboxed executable policy/tool layers

### Research goals

- find the right balance between compression and fidelity
- evaluate graph vs plain claim structures
- define useful agent-facing loading policies
- identify how much can be standardized vs implementation-specific

---

## Non-goals for v0

- full universal agent runtime
- full model-agnostic execution layer for arbitrary tools
- perfect semantic merge for all domains
- replacing vector databases entirely
- replacing source repos or documentation systems

---

## Recommended first milestone

Build a thin vertical slice:

1. ingest markdown docs + ADRs + repo metadata
2. extract claims and decisions
3. write content-addressed blobs
4. emit root manifest
5. verify digest integrity
6. load only selected layers for a task
7. diff two archives

If that is not clean, nothing else matters.

---

## Initial repo map

```text
.
├── README.md
├── CLAUDE.md
├── MEMORY.md
├── INDEX.md
├── docs/
│   ├── architecture.md
│   ├── repo-structure.md
│   ├── roadmap.md
│   ├── evaluation-plan.md
│   ├── security-model.md
│   ├── provenance-signing.md
│   ├── builder-pipeline.md
│   ├── loader-runtime.md
│   ├── contributing.md
│   ├── adr/
│   ├── research/
│   └── spec/
├── .claude/
│   └── commands/
├── plans/
└── templates/
```

---

## Claude Code workflow

### Daily loop

1. start from `INDEX.md`
2. load `MEMORY.md` for current project state
3. read `CLAUDE.md` for operating rules
4. inspect the relevant spec doc in `docs/spec/`
5. update ADRs when architecture decisions change
6. update memory after each meaningful session

### Session hygiene

Before doing deep work, Claude should know:

- what ARC is
- what problem it solves
- what phase the project is in
- what is frozen vs still open
- what source of truth file to trust for each topic

That is why `MEMORY.md` and `INDEX.md` are separate.

---

## Suggested build phases

### Phase 1 — format skeleton

- manifest schema
- blob addressing
- local archive layout
- inspect / verify commands

### Phase 2 — semantic layer

- claims
- decisions
- evidence pointers
- provenance metadata

### Phase 3 — runtime layer

- selective mount
- task-aware load policy
- vector shard references
- policy loading

### Phase 4 — trust layer

- signatures
- attestations
- rollback protection
- policy enforcement

### Phase 5 — benchmark layer

- compression fidelity tests
- retrieval tests
- security tests
- diff / merge tests

---

## What success looks like

A developer can run something like:

```bash
arc build .
arc inspect project.arc
arc verify project.arc
arc load project.arc --task "review this auth change"
arc diff project-v1.arc project-v2.arc
```

And the agent gets:

- less junk
- better recall
- stronger trust
- cheaper context handling
- reusable project knowledge

---

## Rules for this repo

- keep docs brutally concrete
- do not hand-wave security
- do not pretend retrieval alone solves this
- separate stable concepts from speculative ideas
- write ADRs for architecture pivots
- treat provenance as product surface, not backend trivia

---

## Where to start

Read in this order:

1. `INDEX.md`
2. `CLAUDE.md`
3. `MEMORY.md`
4. `docs/architecture.md`
5. `docs/spec/arc-format.md`
6. `docs/security-model.md`
7. `docs/roadmap.md`

