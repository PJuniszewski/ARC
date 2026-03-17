# ADR-0005: Operational Layers

## Status
Accepted

## Context
ARC currently archives **what an agent knows** (source units, claims, decisions, embeddings) but not **what an agent can do** (tools, permissions, policies, workflows). A complete agent package requires both knowledge and operational context. Without operational layers, the archive cannot represent a full agent — only its knowledge base.

This is a scope expansion from ADR-0001, which initially excluded agent runtime concerns. The expansion is justified because:
- Operational declarations are **data**, not runtime code — they fit the artifact-first model
- Agent configs (CrewAI YAML, Aider conventions, etc.) are a primary source of agent context
- Downstream consumers need to know what tools, constraints, and workflows an agent uses

## Decision
Add three optional, declarative operational layer types to the archive format:

| Layer | Type | Answers | Covers |
|-------|------|---------|--------|
| **Tools** | `operational.tools` | "What can this agent do?" | Tool contracts, action boundaries, capabilities |
| **Policy** | `operational.policy` | "What is it allowed to do?" | Permissions, constraints, model limits, deny rules |
| **Workflow** | `operational.workflow` | "How is work organized?" | Agent roles, task graphs, runtime config, sequencing |

Design constraints:
- All three layers are **optional** (`required=False`) — not every archive has operational content
- Layers are **declarative, not executable** in v0 — the archive describes what exists; the runtime decides what to do
- Extraction targets **structured config files** (YAML/JSON) as the primary path, with markdown as a fallback
- Models follow the same pattern as `Claim` and `Decision` (status validation, deterministic IDs, `to_dict`/`from_dict`)
- Operational items are indexed in the vector store alongside knowledge items

## Consequences
- Archive now represents a **complete agent package**: knowledge + capabilities + constraints + workflow
- Three new data models: `ToolDeclaration`, `PolicyRule`, `WorkflowStep`
- Builder pipeline gains extraction logic for YAML/JSON agent configs
- Loader dispatches three new layer types
- Diff engine can compare operational layers across archive versions
- No breaking changes: archives without operational layers continue to work unchanged
- Future v1 could add execution semantics on top of these declarations
