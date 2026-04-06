# ARC - Agent Reasoning Context

[![CI](https://github.com/PJuniszewski/agent-archive/actions/workflows/test.yml/badge.svg)](https://github.com/PJuniszewski/agent-archive/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/arc-context)](https://pypi.org/project/arc-context/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
<!-- COVERAGE-BADGE-START -->
[![Tested](https://img.shields.io/badge/tested-88%25%20coverage-brightgreen)](tests/)
<!-- COVERAGE-BADGE-END -->
[![Stars](https://img.shields.io/github/stars/PJuniszewski/ARC)](https://github.com/PJuniszewski/ARC)

**A context passing protocol for AI agents.** ARC packages knowledge into verifiable, typed artifacts that agents can produce, consume, merge, and trace.

> MCP solved tool calling between agents. ARC solves context handoff.

---

## The problem

When agent A hands off work to agent B, context is lost:

```
Agent A: "I reviewed the auth module. Found 3 issues, decided to migrate to JWT."
Agent B: *starts from scratch, re-reads everything, reaches different conclusions*
```

Either A dumps raw text into B's prompt (noisy, unverifiable) or B rebuilds context from scratch (wasteful, inconsistent).

---

## How ARC solves it

ARC turns agent context into structured, verifiable artifacts:

```
Agent A ──produces──> review.arc ──arc load --type decision──> Agent B
                                                                  │
Agent B ──produces──> fixes.arc ──traceable back to──> review.arc
```

Every claim in an ARC artifact has a **type**, **source**, **evidence**, and **confidence**. Nothing is opaque text.

---

## Claim types

ARC distinguishes what kind of knowledge is being passed:

| Type | Purpose | Example |
|------|---------|---------|
| `observation` | Factual, grounded in source | "auth/views.py uses session-based auth" |
| `decision` | Judgment by agent or human | "we should migrate to JWT" |
| `uncertainty` | Open question | "unclear if rate limiting applies to /admin" |
| `dependency` | Blocker or prerequisite | "requires updating middleware config" |
| `conflict` | Merge disagreement | Auto-generated when agents disagree |

---

## Install

```bash
pip install arc-context
```

---

## Quick start

### Build context from a codebase

```bash
arc init                                               # detect project, build first .arc
arc init --json                                        # structured output for agents
```

### Build and inspect

```bash
arc build ./src --out project.arc                      # produces single-file SQLite .arc
arc inspect project.arc
arc verify project.arc
```

### Query by type and source

```bash
arc load project.arc --task "auth migration"           # semantic search
arc load project.arc --type decision                   # only decisions
arc load project.arc --source agent-a                  # only from agent A
arc load project.arc --type decision --source agent-a  # compose filters
```

### Hand off context between agents

```bash
arc snapshot full.arc --out handoff.arc --last 10      # lightweight subset
arc merge security.arc performance.arc --out combined.arc  # parallel work
arc diff review.arc fixes.arc                          # compare artifacts
```

---

## Agent-to-agent workflow

### Sequential handoff

```
Agent A (Reviewer)                    Agent B (Implementer)
       │                                      │
       ├── review codebase                    │
       ├── observations + decisions           │
       ╰──> review.arc                        │
                 │                             │
                 ╰── arc load --type decision ─╯
                                               │
                                   act on decisions
                                   produce fixes.arc
                                               │
              review.arc <── references ── fixes.arc
```

### Parallel merge

```
Agent C (Security)     Agent D (Performance)
       │                        │
  security.arc            performance.arc
       │                        │
       ╰────── arc merge ───────╯
                    │
              combined.arc
                    │
         observations coexist
         conflicts flagged
                    │
              Agent E loads
         arc load --type conflict
            resolves disputes
```

---

## Full pipeline

```
                        ┌─── Build ───────────────────────┐
                        │                                  │
  Source files ──> Ingest ──> Chunk ──> Extract claims     │
                        │         ──> Deduplicate          │
                        │         ──> Embed + Index        │
                        │         ──> Assemble ──> .arc    │
                        └──────────────────────────────────┘
                                                  │
                ┌─── Consume ─────────────────────┤
                │                                  │
           arc verify                        arc snapshot
                │                                  │
           arc load                          handoff.arc
                │                                  │
     filter by type/source/task            arc merge a.arc b.arc
                │                                  │
          Agent runtime                    combined.arc
                                                   │
                                        conflicts? ──> resolve
```

---

## Python API

```python
from arc import create_archive, load, merge, snapshot
from arc.models import Claim

# Agent produces claims
claims = [
    Claim(text="auth uses session tokens", claim_type="observation",
          source="review-agent", confidence=0.95),
    Claim(text="should migrate to JWT", claim_type="decision",
          source="review-agent", confidence=0.8),
]
create_archive("review.arc", claims, archive_id="arc://review")

# Next agent loads and filters
loaded = load("review.arc", claim_type="decision")
for claim in loaded.claims:
    print(f"[{claim.claim_type}] {claim.text} (by {claim.source})")

# Merge parallel work
result, manifest = merge("security.arc", "perf.arc", "combined.arc")
print(f"Conflicts: {result.conflicts_detected}")
```

---

## Architecture

```
Source -> Builder -> Artifact -> Loader -> Runtime
                        |
                    snapshot / merge
                        |
                  Agent-to-Agent handoff
```

- **Builder**: extracts typed claims from source (8-stage pipeline)
- **Artifact**: single-file SQLite `.arc` with Merkle integrity
- **Loader**: selective loading with type/source/task filtering
- **Snapshot**: lightweight subset for quick handoffs
- **Merge**: combine parallel agent outputs, flag conflicts

Full design: [`docs/architecture.md`](docs/architecture.md) | Protocol: [`docs/protocol.md`](docs/protocol.md)

---

## CLI reference

| Command | Purpose |
|---------|---------|
| `arc init [dir]` | Detect project, generate config, build first `.arc` |
| `arc init --json` | Structured output for agent consumption |
| `arc build <dir> --out <path>` | Build single-file `.arc` from source |
| `arc snapshot <arc> --out <path> --last N` | Lightweight subset for handoff |
| `arc merge <a> <b> --out <path>` | Merge two archives, flag conflicts |
| `arc load <arc> [--type T] [--source S] [--task Q]` | Load and query |
| `arc inspect <arc>` | Show metadata and layers |
| `arc verify <arc>` | Check Merkle integrity |
| `arc diff <a> <b>` | Compare two archives |
| `arc restore <arc> --out <dir>` | Reconstruct source files |

---

## Benchmark

ARC preserves near-hybrid retrieval quality while making every result traceable:

<!-- BENCHMARK-START -->
30 tasks per repo, 6 categories. Context recall = fraction of required facts found.

Full analysis: [`docs/benchmark-fastapi-vs-django.md`](docs/benchmark-fastapi-vs-django.md)
<!-- BENCHMARK-END -->

**What are these systems?**
- **hybrid_arc** — ARC: typed claims, evidence pointers, semantic filtering. The product.
- **hybrid** — best baseline: vector embeddings + keyword matching on raw code chunks. What you'd get searching the repo with a good RAG setup, no ARC. No traceability.
- **vector** — embedding search only (sentence-transformers cosine similarity)
- **tfidf** — keyword search only (TF-IDF term matching)
- **arc** — ARC claim extraction without the hybrid scoring refinement layer

**What do the columns mean?**
- **Context Recall** — fraction of ground-truth facts the system found (higher = found more relevant code)
- **Traceability** — can each result be traced to an exact source file and line range? (1.0 = yes, 0.0 = no)
- **Debuggability** — are results structured enough to inspect and debug? (claims vs raw text)
- **Token Efficiency** — how much prompt space is saved vs dumping everything

**Takeaway:** hybrid_arc matches the best raw retrieval (hybrid) on recall, while adding full traceability — every result links back to source code. The baselines find the same facts but can't tell you where they came from.

---

## What ARC is not

- Not a vector database wrapper
- Not a runtime memory system
- Not a zip file with markdown
- Not framework-specific

---

## Benchmark

<!-- BENCHMARK-START -->
30 tasks per repo, 6 categories. Context recall = fraction of required facts found.

### FastAPI (15K LOC, 130 files)

| System | Context Recall | Traceability | Debuggability | Token Efficiency |
|--------| ------------- | ------------- | ------------- | ------------- |
| hybrid | 0.450 | 0.000 | 0.000 | 0.999 |
| **hybrid_arc** | **0.450** | **1.000** | **0.940** | **0.997** |
| vector | 0.450 | 0.000 | 0.000 | 0.999 |
| arc | 0.250 | 1.000 | 0.000 | 0.998 |
| tfidf | 0.450 | 0.000 | 0.000 | 0.999 |

hybrid_arc vs hybrid: d = +0.000 (negligible)

Full analysis: [`docs/benchmark-fastapi-vs-django.md`](docs/benchmark-fastapi-vs-django.md)
<!-- BENCHMARK-END -->

- ~93% of hybrid recall with full evidence traceability (1.0 vs 0.0)
- 65%+ token reduction vs raw hybrid retrieval

---

## Docs

| Document | Purpose |
|----------|---------|
| [`docs/protocol.md`](docs/protocol.md) | Context passing protocol for integrators |
| [`docs/claim-schema.md`](docs/claim-schema.md) | Typed claim schema design |
| [`docs/architecture.md`](docs/architecture.md) | 5-layer system model |
| [`docs/spec/arc-format.md`](docs/spec/arc-format.md) | Archive format specification |
| [`docs/spec/semantic-model.md`](docs/spec/semantic-model.md) | Claim, Decision, Evidence models |
| [`docs/spec/cli-contract.md`](docs/spec/cli-contract.md) | CLI command contracts |

---

## Development

```bash
make test              # run test suite
make lint              # ruff check
make benchmark-smoke   # quick benchmark on FastAPI snapshot
```

---

## License

Apache 2.0
