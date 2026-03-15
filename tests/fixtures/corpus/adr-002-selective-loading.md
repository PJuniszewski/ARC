# ADR-002: Selective Loading Strategy

## Context

Agents should not be forced to load entire archives for every task. We need a mechanism to mount only relevant content based on the current task.

## Decision

We will implement task-aware selective loading using embedding similarity. When a task description is provided, the loader embeds the query and retrieves the most relevant claims and decisions using cosine similarity against the archive's embedding index.

## Consequences

- Reduced context pollution for focused tasks
- Lower token usage by excluding irrelevant content
- Requires maintaining an embedding index in the archive
- Task descriptions must be meaningful enough for similarity matching
- Requirements and critical policies are always included regardless of task
