# Gotchas — Pitfalls & Workarounds

> Known traps encountered in this project. Structured to prevent repeat mistakes.

---

## Project Gotchas

### MEMORY.md and INDEX.md must stay separate
- **Problem**: Temptation to merge them into one file for simplicity
- **Reason**: MEMORY.md is mutable state (updated often), INDEX.md is stable structure (updated rarely). Merging creates update conflicts and confuses navigation with state tracking.
- **Workaround**: Respect ADR-0003. Always keep them separate.
- **First hit**: Project design phase

### Don't turn ARC into "agent memory" branding
- **Problem**: Easy to drift into vague "memory" framing
- **Reason**: ARC is specifically about portable, verifiable, semantic archives — not a chatbot memory layer or generic state persistence
- **Workaround**: Check CLAUDE.md guardrails. Focus on artifact, not runtime.
- **First hit**: Risk identified in MEMORY.md

### No code exists yet — document-first approach
- **Problem**: Expecting to find implementation code
- **Reason**: Project is intentionally in concept/spec formation phase. Code comes after format skeleton is solid.
- **Workaround**: Work within docs/, spec/, and ADR framework. Don't jump to implementation.
- **First hit**: 2026-03-15

### Zip file contains the canonical project scaffold
- **Problem**: Project files live inside `agent-arc-project.zip`, not directly in repo
- **Reason**: Files were uploaded via GitHub web UI as a zip
- **Workaround**: Extract zip to repo root before working. Keep zip as reference artifact.
- **First hit**: 2026-03-15

### Context pollution from flat instruction files
- **Problem**: Single large instruction file causes model to pull irrelevant context, hit lost-in-the-middle, get conflicting instructions
- **Reason**: Models can't effectively navigate 500+ line files — important info gets buried
- **Workaround**: Use progressive disclosure: routing table (<150 lines) → topic files → external sources. Max 2 hops.
- **First hit**: Memory architecture design (2026-03-15)

---

## Risks to Watch

| Risk | Severity | Mitigation |
|------|----------|------------|
| Over-designing format before proving developer value | High | Start with thin vertical slice (MVP plan) |
| Inventing a graph monster nobody can maintain | High | Prefer boring, composable building blocks |
| Ignoring prompt injection in source material | High | Security-model.md covers threat model |
| Pretending provenance is optional | Medium | Provenance by default is an architecture principle |
| Coupling too hard to one agent runtime | Medium | Five-layer split keeps format portable |
