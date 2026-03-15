# Active — Operational Index

> What matters right now. Updated every session.

---

## In Progress

| Task | Since | Why | Files involved |
|------|-------|-----|----------------|
| Memory architecture setup | 2026-03-15 | Build structured knowledge persistence for Claude Code sessions | memory/*, CLAUDE.md, .claude/commands/ |
| Repo bootstrap from zip scaffold | 2026-03-15 | Extract and organize project files from agent-arc-project.zip | All root-level files, docs/, plans/, templates/ |

---

## Blocked

| Item | Waiting on | Since |
|------|-----------|-------|
| — | — | — |

---

## Recently Completed

| Item | When | Commit | Lesson |
|------|------|--------|--------|
| Initial zip upload with project scaffold | 2026-03-15 | `27c1c8a` | Project structure was designed document-first before any code — CLAUDE.md, MEMORY.md, INDEX.md as separate concerns (ADR-0003) |
| Deep research document upload | 2026-03-15 | `b6e4be1` | Comprehensive Polish-language research doc covers architecture, data models, security, ML compression — serves as reference artifact |

---

## Decisions Pending

| Question | Context | Options considered |
|----------|---------|-------------------|
| Minimum viable semantic unit | Core to format design — what's the smallest meaningful piece? | Raw chunk, claim, claim+evidence, decision object |
| Embeddings in archive | How much vector data belongs inside .arc? | Full shards, references only, optional external index contract |
| Archive representation | Single file vs directory vs OCI vs all three | Each has tradeoffs for portability vs tooling |
| Selective load policy | How does the agent choose what to mount? | Task labels, dependency graph, manifest hints, runtime scoring |
| Trust boundary for builder | Who/what do we trust produced the archive? | Human-reviewed, builder-signed, multi-party attested |
| Semantic compression aggressiveness | How much can we compress before trust collapses? | Needs evaluation harness to determine empirically |
