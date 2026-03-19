# ARC — Agent Reasoning Context

[![Tests](https://github.com/PJuniszewski/agent-archive/actions/workflows/test.yml/badge.svg)](https://github.com/PJuniszewski/agent-archive/actions/workflows/test.yml)
[![Metrics](https://github.com/PJuniszewski/agent-archive/actions/workflows/metrics.yml/badge.svg)](https://github.com/PJuniszewski/agent-archive/actions/workflows/metrics.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

Portable, verifiable context packaging for AI agents.

ARC turns scattered sources — repos, docs, ADRs, tickets, policies, embeddings — into a single `.arc` package that can be versioned, diffed, signed, and selectively loaded. Instead of rebuilding context from scratch every run, agents load what they need from a pre-built reasoning artifact.

```
repo + docs + tickets + policies
  → arc build .
  → semantic layers + manifest + attestations
  → project.arc
  → agent loads only what it needs
```

---

## Install

```bash
pip install arc-context
```

## Quick start

```bash
arc build . --out project.arc
arc inspect project.arc
arc verify project.arc
arc load project.arc --task "review this auth change"
arc diff project-v1.arc project-v2.arc
```

## What ARC does

- **Builds** structured context from source — claims, decisions, evidence pointers, policies
- **Stores** everything content-addressed with Merkle integrity
- **Loads** selectively — vector + keyword hybrid retrieval, not all-or-nothing
- **Diffs** archives across versions
- **Verifies** offline — no auth server, no runtime dependency

## What ARC is not

- Not a vector database wrapper
- Not a runtime memory system
- Not a zip file with markdown
- Not framework-specific

## Architecture

5-layer model: **Source → Builder → Artifact → Loader → Runtime**

The builder pipeline extracts semantic structure (claims, decisions, evidence) from raw sources, deduplicates, indexes with embeddings, and packages everything into a manifest-driven archive. The loader verifies integrity, then uses hybrid vector+keyword scoring to surface only the context relevant to the agent's current task.

See [`docs/architecture.md`](docs/architecture.md) for the full system model.

## Development

```bash
# Run tests
make test

# Lint
make lint

# Benchmark (requires repo snapshot setup)
make benchmark-smoke
```

## License

Apache 2.0
