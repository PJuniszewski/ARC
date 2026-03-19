# Loader and Runtime

## Purpose

Loader is the gateway between archive storage and actual agent use.

It should answer:

- is this archive valid?
- can I trust it enough for this task?
- what should I mount?
- what should remain unloaded?

---

## Core responsibilities

### Verification
- digest checks
- schema checks
- signature checks if enabled
- provenance / freshness policy checks if enabled

### Resolution
- find required blobs
- resolve layer dependencies
- surface missing references clearly

### Selective mount
- mount only layers needed for a task
- avoid overloading agent with irrelevant context

### Safe exposure
- expose content as typed data
- preserve source provenance
- avoid treating data as instructions

---

## Selective load model

At minimum loader should support:

- `--layer claims`
- `--layer decisions`
- `--layer policies`
- `--layer indexes`
- `--task <task label>`

Longer term it can support smarter policies, but v0 should remain understandable.

---

## Runtime contract

Runtime should receive:

- typed mounted objects
- explicit provenance handles
- policy handles
- index handles if needed
- archive id / version metadata

Runtime should not need to reverse-engineer archive internals.

---

## Failure behavior

Loader should fail loudly when:

- manifest is invalid
- referenced blob is missing
- digest mismatch exists
- archive is stale under active policy
- incompatible version is loaded

Silent fallback equals silent corruption.

