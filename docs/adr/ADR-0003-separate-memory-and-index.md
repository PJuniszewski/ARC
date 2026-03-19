# ADR-0003: Separate MEMORY.md and INDEX.md

## Status
Accepted

## Context
Project memory and repo navigation serve different jobs.
Mixing them makes both worse.

## Decision
`MEMORY.md` and `INDEX.md` remain separate files.

- `MEMORY.md` stores current working state and open questions
- `INDEX.md` stores navigation and source-of-truth routing

## Consequences
Slight duplication risk, but much better usability in Claude Code sessions.

