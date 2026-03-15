# Memory — Routing Table

> Entry point for cross-session knowledge. Read this first, then navigate to the right topic file.
> **Rule: two hops maximum to any piece of information.**

---

## Navigation

| File | When to consult | Keywords |
|------|----------------|----------|
| `active.md` | Starting a session, picking up WIP, checking what's blocked | wip, current, blocked, recent, progress |
| `scratchpad.md` | Mid-task intermediate results, temporary notes | temp, scratch, working, intermediate |
| `architecture.md` | Architecture decisions, patterns applied, design rationale | pattern, decision, adr, layer, design, split |
| `spec-knowledge.md` | Format details, manifest, blobs, CAS, semantic model | arc, format, manifest, blob, cas, claim, spec |
| `gotchas.md` | Unexpected failures, known traps, workarounds | error, bug, workaround, trap, quirk, fail |
| `research.md` | Research findings, market landscape, related work | research, paper, landscape, comparison, prior-art |

---

## Project Truth (root-level files)

| File | Purpose |
|------|---------|
| `MEMORY.md` (root) | Live project state, open questions, priorities |
| `INDEX.md` | Navigation map for all repo files |
| `CLAUDE.md` | Operating rules and design guardrails |
| `docs/architecture.md` | System model (5 layers) |
| `docs/spec/` | Format specifications |
| `docs/adr/` | Accepted architecture decisions |

---

## How to use this system

1. **Session start**: Read this file → read `active.md` for current state
2. **During work**: Consult topic files matching your task keywords
3. **Topic files** reference external sources (docs/, specs, source code) — that's hop 2
4. **Session end**: Update `active.md` with progress, update data files if new learnings
5. **Scratchpad**: Use for intermediate results, clear when work completes

---

## Principles

- **Progressive disclosure**: Don't load everything — navigate to what's relevant
- **Layer isolation**: Each topic file owns one domain, no cross-contamination
- **Trajectory over state**: Record when, why, and impact — not just facts
