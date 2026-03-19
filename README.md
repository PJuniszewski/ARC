# ARC - Agent Reasoning Context

[![CI](https://github.com/PJuniszewski/agent-archive/actions/workflows/test.yml/badge.svg)](https://github.com/PJuniszewski/agent-archive/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/arc-context)](https://pypi.org/project/arc-context/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
<!-- COVERAGE-BADGE-START -->
[![Tested](https://img.shields.io/badge/tested-88%25%20coverage-brightgreen)](tests/)
<!-- COVERAGE-BADGE-END -->
[![Stars](https://img.shields.io/github/stars/PJuniszewski/ARC)](https://github.com/PJuniszewski/ARC)

**AI answers are hard to trust. ARC makes them inspectable.**

ARC packages repository knowledge into a verifiable context artifact, so agents can load precise, traceable context instead of piecing it together on the fly.

> ARC doesn't make AI smarter. It makes it inspectable.

---

## Why ARC

AI agents don't operate on a stable, structured view of your system.

They piece together context on the fly from:
- conversation history
- files they read
- retrieval results

This works - but the result is often:
- redundant
- noisy
- hard to verify

ARC changes that.

Instead of guessing and searching blindly, agents start from a pre-built, structured context with evidence.

```
guess -> search -> hope
```

becomes:

```
load -> locate -> prove
```

---

## How it works

```
repo + docs + tickets + policies
  -> arc build .
  -> semantic layers + manifest
  -> project.arc
  -> agent loads only what it needs
```

ARC builds a structured representation of your system once, then lets agents query it efficiently and reliably.

---

## Install

```bash
pip install arc-context
```

---

## Quick start

```bash
arc build . --out project.arc                         # extract claims, decisions, evidence from source
arc inspect project.arc                               # show layers, blob count, manifest summary
arc verify project.arc                                # check Merkle integrity, detect tampering
arc load project.arc --task "review this auth change" # retrieve only context relevant to the task
arc diff project-v1.arc project-v2.arc                # compare two archive versions
```

---

## What ARC does

- **Builds structured context** - claims, decisions, evidence pointers
- **Makes answers inspectable** - every claim is traceable to source
- **Loads selectively** - hybrid vector + keyword retrieval
- **Stores content-addressed** - Merkle integrity, reproducible builds
- **Diffs versions** - track how context changes over time
- **Verifies offline** - no runtime dependency on external services

---

## What ARC is not

- Not a vector database wrapper
- Not a runtime memory system
- Not a zip file with markdown
- Not framework-specific

---

## Architecture

ARC is built as a simple 5-layer system:

```
Source -> Builder -> Artifact -> Loader -> Runtime
```

- **Builder** extracts semantic structure (claims, decisions, evidence)
- **Artifact** stores it as a content-addressed archive
- **Loader** retrieves only relevant context for a task

Full system design: [`docs/architecture.md`](docs/architecture.md)

---

## Benchmark

ARC preserves near-hybrid retrieval quality while making every result traceable and debuggable.

> hybrid_arc ~ hybrid recall, but with full traceability (1.0 vs 0.0)

<!-- BENCHMARK-START -->
30 tasks per repo, 6 categories. Context recall = fraction of required facts found.

### FastAPI (15K LOC, 130 files)

| System | Context Recall | Traceability | Debuggability | Token Efficiency |
|--------| ------------- | ------------- | ------------- | ------------- |
| hybrid | 0.350 | 0.000 | 0.000 | 0.999 |
| **hybrid_arc** | **0.350** | **1.000** | **0.916** | **0.998** |
| vector | 0.300 | 0.000 | 0.000 | 0.999 |
| arc | 0.200 | 1.000 | 0.000 | 0.998 |
| tfidf | 0.300 | 0.000 | 0.000 | 0.999 |

hybrid_arc vs hybrid: d = +0.000 (negligible)

Full analysis: [`docs/benchmark-fastapi-vs-django.md`](docs/benchmark-fastapi-vs-django.md)
<!-- BENCHMARK-END -->

- ~93% of hybrid recall
- every result traceable to source file + line

---

## Example

Query:

```
How does authentication work?
```

ARC returns:
- Answer
- Evidence (files + lines)
- Suggested files to inspect

---

## When to use ARC

- working with large repos
- debugging AI-generated answers
- reviewing code changes with context
- building AI agents that need reliable context

---

## Development

```bash
make test
make lint
make benchmark-smoke
```

---

## License

Apache 2.0
