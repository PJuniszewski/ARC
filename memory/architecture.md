# Architecture — Patterns & Decisions

> Design patterns applied in this project with trajectory: what, when, why.

---

## Accepted Patterns

### Artifact-first design
- **Applied to**: Entire ARC project philosophy
- **When**: Project inception (ADR-0002)
- **Why**: Runtime-memory-first approaches (chatbot memory, RAG-only) fail at scale — they lack portability, verifiability, and diffability. Building the artifact format first ensures the core is durable even as builders and runtimes evolve.
- **Impact**: All design decisions flow from "what makes a good artifact" not "what makes a good runtime"

### Separate MEMORY.md and INDEX.md
- **Applied to**: Root-level project files
- **When**: Project inception (ADR-0003)
- **Why**: MEMORY.md tracks mutable project state (open questions, priorities). INDEX.md tracks stable navigation structure. Merging them creates update conflicts and confuses "what's happening" with "where things are."
- **Impact**: Clear separation of concerns — state vs structure

### Five-layer system model
- **Applied to**: Overall architecture (docs/architecture.md)
- **When**: Initial architecture design
- **Why**: Fusing build, format, and runtime creates framework sludge. Five clear layers (Source → Builder → Artifact → Loader → Runtime) with explicit boundaries keep the format portable.
- **Impact**: Each layer can evolve independently; format stays durable

### Content-addressed storage (CAS)
- **Applied to**: Blob model in .arc format
- **When**: Format design phase
- **Why**: Immutable blobs with digest-based addressing enable offline verification, deduplication, and tamper detection without a central authority.
- **Impact**: Foundation for trust model, diff capability, and incremental updates

### Three-layer memory architecture
- **Applied to**: Claude Code knowledge persistence (memory/ directory)
- **When**: 2026-03-15 (this session)
- **Why**: Single flat instruction files cause context pollution, conflicting instructions, and lost-in-the-middle problems. Progressive disclosure with routing table → operational state → domain data fixes all three.
- **Impact**: Agents navigate to relevant knowledge in ≤2 hops instead of scanning everything

---

## Design Biases (from CLAUDE.md)

| Prefer | Over |
|--------|------|
| Claim + evidence | Raw summary only |
| Immutable blobs | Mutable hidden stores |
| Explicit manifests | Implicit discovery |
| Attachable attestations | Trust-me metadata |
| Local-first layouts | OCI-only workflows |
| Narrow v0 scope | Bloated universal ambitions |
