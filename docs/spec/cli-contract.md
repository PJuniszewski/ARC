# CLI Contract

## Goal

The CLI should make ARC understandable and operable without making users reverse-engineer internals.

---

## Proposed commands

### `arc init`
Initialize project scaffolding.

### `arc build`
Build an archive from configured sources.

### `arc inspect`
Show archive structure, layers, digests, and trust metadata.

### `arc verify`
Verify integrity and optionally signatures / attestations / freshness.

### `arc load`
Resolve and mount archive content for a task or explicit layer set.

### `arc diff`
Compare two archives and summarize content and semantic deltas.

### `arc extract`
Export one or more layers or semantic object groups.

---

## UX rules

- commands must be inspectable and script-friendly
- errors must name the offending digest, layer, or manifest field
- `inspect` should be readable by humans
- `verify` should support machine-readable output for CI

---

## Example flow

```bash
arc init
arc build --sources ./docs ./adr
arc inspect ./dist/project.arc
arc verify ./dist/project.arc --strict
arc load ./dist/project.arc --task review-auth-change
arc diff ./dist/project-v1.arc ./dist/project-v2.arc
```

