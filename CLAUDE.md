# CLAUDE.md

This file tells Claude Code how to operate in this repository.

## Mission

Help design and document ARC: a portable archive format and toolchain for agent context.

ARC is not a generic “memory” project. It is specifically about packaging agent-relevant context into a verifiable artifact that supports:

- semantic compression
- selective loading
- provenance
- signatures and attestations
- incremental updates
- policy-aware execution

## Your job

When working in this repo, optimize for:

1. clarity over hype
2. concrete design over vague ideation
3. trust and verification over convenience theater
4. modular architecture over giant magical abstractions
5. artifact boundaries over runtime spaghetti

## Important constraints

- Do not collapse `MEMORY.md` and `INDEX.md` into one file.
- Treat `.arc` as a real artifact format, not just a folder of notes.
- Separate stable design choices from open questions.
- Do not invent benchmark results.
- Do not claim standardization where none exists.
- Prefer boring, composable building blocks over clever novelty.

## Knowledge system

This repo uses a three-layer memory architecture for cross-session knowledge persistence.

### Session start protocol

1. Read `memory/MEMORY.md` — routing table for accumulated knowledge
2. Read `memory/active.md` — current WIP, blockers, recent completions
3. Read `CLAUDE.md` (this file) — operating rules
4. Navigate to relevant topic files based on task keywords

### Navigation (progressive disclosure)

- **Hop 0**: `memory/MEMORY.md` auto-loaded → routing table with keywords per topic
- **Hop 1**: Navigate to matching topic file in `memory/` based on task
- **Hop 2**: Topic file references external sources (docs/, specs, source code)
- **Two hops maximum to any piece of information.**

### Session end protocol

1. Update `memory/active.md` — move completed items, add new WIP
2. Update relevant `memory/` data files if new learnings emerged
3. Clear `memory/scratchpad.md` if used during session
4. Update root `MEMORY.md` if project state changed

## Repo navigation rules

Use these files as source of truth:

- `INDEX.md` -> where things live
- `MEMORY.md` -> current project state, assumptions, open questions
- `memory/MEMORY.md` -> cross-session knowledge routing table
- `memory/active.md` -> current work state and session continuity
- `docs/architecture.md` -> overall system model
- `docs/spec/arc-format.md` -> format and layout
- `docs/spec/manifest-schema.md` -> manifest details
- `docs/security-model.md` -> threat model and controls
- `docs/provenance-signing.md` -> trust chain design
- `docs/adr/` -> accepted decisions

## Working style

When asked to implement or propose something:

### 1. Re-anchor

Quickly identify:

- which layer is affected
- whether this is format, builder, loader, trust, or evaluation work
- whether an ADR should be updated

### 2. Minimize ambiguity

If the repo already contains an answer, use it.
Do not fork concepts casually.

### 3. Push toward concrete outputs

Prefer producing one of these:

- schema
- manifest example
- CLI contract
- ADR
- benchmark plan
- repo structure change
- security control list

### 4. Preserve project coherence

If you introduce a new concept, update:

- `INDEX.md` if discoverability changes
- `MEMORY.md` if project state changes
- relevant spec docs if architecture changes

## Architecture guardrails

### ARC should remain:

- content-addressed
- manifest-driven
- incrementally updatable
- verifiable offline where possible
- selective-load capable
- security-first

### ARC should not become:

- a vague memory scrapbook
- a hidden vector DB wrapper
- a black-box agent state dump with no semantics
- a framework-specific lock-in artifact

## Preferred design bias

When there are tradeoffs, generally prefer:

- claim + evidence over raw summary only
- immutable blobs over mutable hidden stores
- explicit manifests over implicit discovery
- attachable attestations over trust-me metadata
- local-first layouts that can later map to OCI
- narrow v0 scope over bloated universal ambitions

## Output expectations

When drafting docs or code-related proposals:

- be explicit about assumptions
- include examples
- include failure modes
- include migration implications if relevant
- call out what is v0 vs later

## ADR trigger points

Create or update an ADR when changing:

- archive layout
- manifest semantics
- trust model
- execution model
- index/storage strategy
- merge/diff model
- transport or distribution strategy

## Session closeout

At the end of meaningful work, propose updates to:

- `MEMORY.md` current status
- open questions
- next tasks
- changed assumptions

