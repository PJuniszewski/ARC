# CrewAI Content Pipeline

## Overview

This project uses CrewAI to automate technical content creation with a three-agent pipeline: research, write, and review.

## Architecture

The pipeline defines three agents that work sequentially:

1. **Researcher** — gathers and validates information from multiple sources
2. **Writer** — transforms research into structured technical content
3. **Reviewer** — ensures quality, accuracy, and style compliance

## Configuration

Agent definitions are in `agents.yaml`. Task definitions and dependencies are in `tasks.yaml`.

## Running

```bash
crewai run --config agents.yaml --tasks tasks.yaml --topic "your topic here"
```

## Conventions

- All agents must cite sources for factual claims.
- The reviewer has veto power — content should not be published without passing review.
- Research must include at least 3 independent sources.
- Code examples must be tested before inclusion.

## Decision: Sequential Pipeline

We chose a sequential pipeline (research → write → review) over a parallel approach because:
- Each stage depends on the output of the previous stage
- Sequential execution is simpler to debug and audit
- The quality gate (reviewer) requires seeing the complete article

## Consequences

- Total pipeline runtime is the sum of all stages (no parallelism)
- If the reviewer rejects, the entire pipeline must re-run
- Adding new agents requires updating the dependency chain
