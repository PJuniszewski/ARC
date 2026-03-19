# Repo Structure

## Purpose

This repo is document-heavy first, code-light initially.
The early goal is to get the conceptual architecture and spec right before shipping implementation complexity.

---

## Current structure

```text
.
├── README.md
├── CLAUDE.md
├── MEMORY.md
├── INDEX.md
├── docs/
├── .claude/
├── plans/
└── templates/
```

---

## Directory intent

### `docs/`
Main durable knowledge.

Use for:
- architecture
- specs
- security
- provenance
- roadmap
- evaluation
- ADRs
- research notes

### `docs/spec/`
Format and contract docs.

These are the closest thing to product law.

### `docs/adr/`
Accepted architecture decisions.

Anything here should be treated as settled until explicitly replaced.

### `docs/research/`
Inputs and exploration.

Useful, but not automatically source of truth.

### `.claude/commands/`
Reusable prompts / operating docs for Claude Code.

### `plans/`
Execution planning.

Use for task sequencing and near-term work, not canonical architecture.

### `templates/`
Reusable authoring templates.

---

## Suggested future code layout

When implementation begins, add something like:

```text
src/
  arc_builder/
  arc_loader/
  arc_manifest/
  arc_verify/
  arc_cli/

tests/
  fixtures/
  manifest/
  verify/
  load/
  diff/
```

But do not add code directories until the first implementation slice is real.

---

## Repo discipline

- architecture belongs in docs, not scattered chat fragments
- decisions belong in ADRs, not only in memory
- memory stays short and alive
- index stays navigational
- specs should be version-aware

