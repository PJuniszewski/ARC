# CLI Contract

## Goal

The CLI should make ARC understandable and operable without making users reverse-engineer internals.

---

## Commands

### `arc build`
Build an archive from a source directory.

```bash
arc build <source_dir> --out <path> [--id ID] [--version VERSION] [--parent ARCHIVE]
```

### `arc inspect`
Show archive structure, layers, digests, and trust metadata.

```bash
arc inspect <archive> [--json]
```

### `arc verify`
Verify integrity and optionally signatures / attestations / freshness.

```bash
arc verify <archive> [--json]
```

### `arc load`
Resolve and mount archive content for a task or explicit layer set.

```bash
arc load <archive> [--task TASK] [--layer NAME] [--type TYPE] [--source SOURCE] [--raw] [--code] [--ext EXT]
```

Filter flags:
- `--type` — observation | decision | uncertainty | dependency | conflict
- `--source` — agent ID, "human", or "builder"
- `--task` — semantic search via embeddings
- Flags compose with AND logic: `--type decision --source agent-a` returns decisions from agent-a only

### `arc snapshot`
Create a lightweight subset of an archive for quick handoff.

```bash
arc snapshot <archive> --out <path> --last N [--type TYPE] [--source SOURCE]
```

The snapshot is a valid `.arc` — same format, same Merkle integrity, loadable by `arc load`.

### `arc merge`
Combine two archives from parallel agents.

```bash
arc merge <archive_a> <archive_b> --out <path>
```

Observations coexist. Conflicting decisions are flagged as `conflict` claims. Duplicates are deduplicated by text content.

### `arc diff`
Compare two archives and summarize content and semantic deltas.

```bash
arc diff <archive_a> <archive_b> [--json]
```

### `arc restore`
Reconstruct source files from archive (lossy — joins chunks with newlines).

```bash
arc restore <archive> --out <path>
```

---

## UX rules

- commands must be inspectable and script-friendly
- errors must name the offending digest, layer, or manifest field
- `inspect` should be readable by humans
- `verify` should support machine-readable output for CI
- filter flags compose naturally with AND logic

---

## Example flows

### Single-agent context extraction
```bash
arc build ./src --out project.arc
arc inspect project.arc
arc verify project.arc
arc load project.arc --task "review auth change"
```

### Agent-to-agent handoff
```bash
# Agent A produces a review
arc build ./src --out review.arc

# Quick handoff of last 10 claims
arc snapshot review.arc --out handoff.arc --last 10

# Agent B loads only decisions
arc load handoff.arc --type decision
```

### Parallel merge
```bash
# Two agents work independently
# Agent C: security.arc, Agent D: performance.arc

arc merge security.arc performance.arc --out combined.arc
arc load combined.arc --type conflict     # see disagreements
arc load combined.arc --source agent-c    # see only C's work
```
