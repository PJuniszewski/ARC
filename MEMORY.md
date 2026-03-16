# MEMORY.md

This is the live working memory for the ARC project.
It is intentionally short, practical, and updated often.

---

## Project snapshot

**Project name:** ARC Archive  
**Purpose:** portable semantic archive format for AI agent context  
**Current stage:** concept / spec formation / repo bootstrap  
**Primary environment:** Claude Code  

---

## Core thesis

Agents keep wasting tokens and reliability because they reconstruct context at runtime from messy sources.

ARC proposes a better model:

- build once from trusted inputs
- package context into a verifiable artifact
- load only task-relevant layers
- preserve provenance and diffability

---

## What ARC currently means

ARC is expected to include some combination of:

- manifest
- content-addressed blobs
- claims / facts
- decisions / ADR-derived rationale
- evidence pointers to source units
- policies
- embedding shard metadata
- attestations and signatures

It may later include sandboxed executable layers, but that is not assumed for v0.

---

## Current design direction

### Strong preferences

- local-first archive layout that can map to OCI later
- immutable blobs with digests
- manifest as the entry point
- semantic units above raw chunks
- provenance by default
- separate stable memory from navigational index

### Working assumption

The best v0 is probably:

- not full RDF everywhere
- not full graph runtime everywhere
- not full executable archive everywhere

Instead:

- manifest + CAS
- claims + decisions + evidence
- basic vector shard references
- trust metadata

---

## Open questions

1. What is the minimum viable semantic unit?
   - raw chunk?
   - claim?
   - claim + evidence?
   - decision object?

2. How much of embeddings should be in the archive?
   - full shards
   - references only
   - optional external index contract?

3. Should `.arc` be:
   - single-file package
   - directory layout
   - OCI artifact mapping
   - all three with canonical semantics?

4. How should selective load policy work?
   - task label based?
   - dependency graph based?
   - manifest hints?
   - runtime scoring?

5. What is the trust boundary for builder output?
   - human-reviewed only?
   - builder-signed?
   - multi-party attested?

6. ~~How aggressive can semantic compression be before trust collapses?~~ Resolved: no lossy compression in builder (ADR-0004). Selective loading is the loader's job.

---

## Risks to watch

- turning ARC into vague “agent memory” branding
- over-designing format before proving developer value
- inventing a graph monster that nobody can maintain
- ignoring prompt injection in source material
- pretending provenance is optional
- coupling too hard to one agent runtime

---

## Near-term priorities

### Priority 1

Define a clean format skeleton:

- archive layout
- manifest structure
- blob model
- inspect/verify flow

### Priority 2

Define semantic payloads:

- source unit
- claim
- decision
- evidence pointer

### Priority 3

Define trust model:

- signatures
- attestations
- stale / rollback handling

### Priority 4

Define evaluation harness:

- extraction fidelity
- retrieval quality
- security regression

---

## Current decisions-in-spirit

These are directionally accepted, but not all fully frozen:

- `MEMORY.md` and `INDEX.md` stay separate
- ARC is artifact-first, not chatbot-memory-first
- verification is a feature, not a nice-to-have
- diffability matters as much as storage
- builder and loader should be separable components

---

## What to update after each session

Update this file when any of these change:

- project phase
- accepted design direction
- top open questions
- key risks
- next concrete tasks

