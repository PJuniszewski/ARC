# Spec Knowledge — Format & Technical Facts

> Learnings about the .arc format, manifest, blob model, and semantic units.
> Trajectory format: what we know, when we learned it, why it matters.

---

## Format Facts

| Fact | Detail | When learned | Why it matters |
|------|--------|-------------|----------------|
| Archive has three classes | Minimal, Standard, Extended — graduated complexity | Initial spec design | Allows simple use cases without full overhead |
| Local layout structure | `manifest.json` + `blobs/sha256/` + `refs/` + `meta/` | Format spec (docs/spec/arc-format.md) | Canonical directory layout that can later map to OCI |
| Manifest is JSON-based | Root manifest describes archive contents and how parts fit together | docs/spec/manifest-schema.md | Entry point for all archive operations — verify, inspect, load |
| Four semantic payload types | SourceUnit, Claim, Decision, EvidencePointer | docs/spec/semantic-model.md | These are the core objects the builder produces and loader consumes |
| Content addressing uses SHA-256 | Blobs stored under `blobs/sha256/<digest>` | Architecture design | Enables offline verification, deduplication, tamper detection |

---

## CLI Contract

| Command | Purpose | Source |
|---------|---------|--------|
| `arc build .` | Ingest sources → produce .arc archive | docs/spec/cli-contract.md |
| `arc inspect <archive>` | Show archive contents and metadata | docs/spec/cli-contract.md |
| `arc verify <archive>` | Check digest integrity and signatures | docs/spec/cli-contract.md |
| `arc load <archive> --task "..."` | Mount task-relevant layers for agent | docs/spec/cli-contract.md |
| `arc diff <a> <b>` | Compare two archives | docs/spec/cli-contract.md |

---

## Semantic Model

| Object | Role | Key property |
|--------|------|-------------|
| SourceUnit | Chunk from original input | Stable identity + provenance |
| Claim | Atomic assertion from source(s) | Traceable to evidence |
| Decision | Structured rationale record | Options, chosen path, context |
| EvidencePointer | Link claim/decision → source | Bidirectional traceability |
| PolicyBundle | Runtime behavior constraints | Rules/data for enforcement |
| IndexShard | Retrieval structure | Embeddings or lexical indexes |

---

## v0 Scope Boundaries

| In v0 | Deferred |
|-------|----------|
| Local-first archive layout | Full OCI-native-only workflow |
| Immutable blobs + manifest | Graph-native execution engine |
| Claim + decision objects | Advanced semantic merge |
| Optional vector metadata | General-purpose plugin marketplace |
| Verify / inspect / diff CLI | Full model-agnostic execution layer |
