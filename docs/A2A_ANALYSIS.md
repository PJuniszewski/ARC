# ARC vs A2A — Gap Analysis

**Date:** 2026-05-02
**ARC version analyzed:** v1.3.0 (commit 274faf6)
**A2A version analyzed:** v1.0 (Linux Foundation, originated by Google, April 2025)
**Author:** Analysis prepared on branch `claude/arc-vs-a2a-analysis-M6bUd`

---

## 1. Current ARC state (as of 2026-05-02)

### Core abstractions (implemented, tested)

Source-of-truth files: `src/arc/models.py`, `docs/spec/semantic-model.md`, `docs/protocol.md`.

- **Typed claim** (`src/arc/models.py:109-157`) — atomic assertion with:
  - `claim_type` ∈ {`observation`, `decision`, `uncertainty`, `dependency`, `conflict`}
  - `source` (agent ID / `human` / `builder` / `arc-merge`)
  - `timestamp` (ISO8601)
  - `evidence: list[EvidencePointer]` — each `(source_unit_id, span, weight)`
  - `confidence: float` (0–1)
  - `status` ∈ {`observed`, `derived`, `verified`, `deprecated`, `contested`}
  - `references: list[str]` — IDs of related claims (used by conflict claims)
- **Decision** (`models.py:163-205`) — ADR-style structured record (title, context, options, decision, consequences, evidence, status).
- **EvidencePointer** (`models.py:24-45`) — link to a source unit with optional line span.
- **TextUnit** (`models.py:67-102`) — addressable source chunk, content-hashed, deterministic ID.
- **Resource** (`models.py:48-64`) — file/document/ticket source object.
- **Operational triad** (ADR-0005, `models.py:211-325`):
  - `ToolDeclaration` — name, parameters, returns, constraints, status
  - `PolicyRule` — scope, effect (`allow`/`deny`/`require_approval`), conditions, priority
  - `WorkflowStep` — task graph node with deps, tools, agent refs
- **Manifest** (`models.py:348-393`) — `schema_version`, `archive_id`, `archive_version`, `root_digest` (Merkle), `layers[]`, `provenance`, `compatibility`, `parent_archive`.

### Artifact format

Source: `src/arc/cas.py`, `docs/single-file-format.md`, `docs/spec/arc-format.md`.

- Single-file SQLite (canonical) with `blobs(digest, data, size)` + `meta(key, value)` tables.
- Content-addressed (SHA-256), random access by indexed digest lookup.
- Merkle-sealed root_digest, offline-verifiable.
- Legacy directory layout still supported via `open_cas()` auto-detect.

### Operations (CLI + Python API + MCP server)

CLI surface (`docs/spec/cli-contract.md`, `src/arc/cli.py`):

| Command | Purpose |
|---|---|
| `arc init` | Detect project, build first archive |
| `arc build` | Build .arc from a source dir |
| `arc load --type --source --task --full` | Selective load (filters compose AND) |
| `arc snapshot --last N --type --source` | Lightweight subset for handoff |
| `arc merge a b --out` | Two-way merge with conflict detection |
| `arc diff a b` | Structural + semantic delta |
| `arc verify` | Integrity check |
| `arc inspect` | Metadata view |
| `arc restore` | Reconstruct sources |

MCP server (`src/arc/mcp_server.py`, added Apr–May 2026 — last 5 commits): 7 tools mirroring CLI (`arc_build`, `arc_load`, `arc_snapshot`, `arc_merge`, `arc_verify`, `arc_diff`, `arc_inspect`). The MCP multi-agent benchmark (`eval/mcp_benchmark.py`, `eval/mcp_benchmark_results.md`) covers handoff / parallel merge / conflict / 3-hop chain / performance — 43/43 checks pass.

### What works pre-pause

- Sequential handoff (A → snapshot → B), parallel merge (C+D), conflict detection — all green.
- Retrieval recall: hybrid_arc 0.660 on FastAPI (d=-0.014 vs hybrid baseline), 0.762 on Django.
- Traceability 1.0 vs 0.0 for all baselines (the consistently differentiating metric).
- Tamper / rollback / injection containment 100%.
- 442 tests pass.

### Outstanding issues / known limitations

- **Signatures and attestations not implemented** (`docs/provenance-signing.md` is design-only; Priority 9, "when someone asks"). `source` field is self-reported.
- **No transport / network layer at all.** ARC is a file format. Handoff is "agent A writes a file, agent B reads a file." There is no peer discovery, no message routing, no streaming, no auth.
- **Merge is two-way only.** No three-way / recursive.
- **Operational layers are declarative-only.** No execution semantics in v0.
- **Doc-claim dilution at scale.** On large repos with heavy markdown, code claims are swamped (mitigated but not eliminated by hybrid_arc refinement).
- **Trust boundary for "who built this" is unresolved** (Open Question #1, `MEMORY.md:124`).

---

## 2. Capability mapping

Legend for "Gap status":
- **Covered** — A2A defines this; ARC duplicates it.
- **Gap** — A2A explicitly does not define this; ARC fills the gap.
- **Extension-slot** — A2A leaves room for a URI-identified extension; ARC could plug in here.
- **Adjacent** — different problem; not in scope of either.

| ARC capability | A2A coverage | Gap status | Notes |
|---|---|---|---|
| Transport (agent-to-agent message delivery) | JSON-RPC / gRPC / HTTP+JSON | Covered | ARC has none. Pure file. |
| Agent discovery | Agent Card | Covered | ARC has none. |
| Task lifecycle (submitted/working/completed/failed/canceled/input-required/auth-required) | `Task` state machine | Covered | ARC has no task concept. |
| Multi-turn session correlation | `contextId` + `taskId` | Covered | ARC's `parent_archive` is for archive lineage, not conversation. |
| Auth (OAuth2, mTLS, Bearer, API key) | Agent Card security schemes | Covered | ARC has none. |
| Streaming / push notifications | `SubscribeToTask`, push channels | Covered | ARC has none. |
| Generic message envelope (`Message`, `Part`) | Defined | Covered | ARC has none. |
| Generic artifact envelope (`Artifact`) | Defined as opaque container | Covered (envelope) | A2A `Artifact` is just "labeled container of Parts" — semantics-free. |
| **Typed claims (observation/decision/uncertainty/dependency/conflict) with confidence + status** | Not defined | **Gap (extension-slot)** | A2A `Part.data` is "arbitrary structured JSON" [A2A §5.5 / §4.4.4]. This is the ARC core. |
| **Evidence pointers (source_unit_id + span + weight)** | Not defined | **Gap (extension-slot)** | No A2A primitive for "this claim is grounded at file X lines Y–Z." |
| **Source attribution per content unit** (`source` agent ID + timestamp on each claim) | Not defined; A2A only attributes whole `Message`s to a sender | **Gap (extension-slot)** | A2A knows "agent B sent this message," not "this specific claim came from agent A and was verified by agent B." |
| **Conflict claim type + auto-detection on merge** | Not defined | **Gap (extension-slot)** | A2A's `input-required` / `auth-required` are workflow states, not semantic conflicts between claims. |
| **Content-addressed storage with Merkle integrity** | Not defined; transport-level TLS only | **Gap** | A2A trusts the transport. Tampering after-the-fact is undetectable. |
| **Offline verifiability** | Not defined | **Gap** | A2A is online-by-design. |
| **Selective loading by type / source / semantic query** | Not defined | **Gap** | A2A returns whole Messages/Artifacts. No filter-by-claim-type. |
| **Lightweight snapshot of subset** | Not defined | **Gap** | No equivalent. |
| **Two-way semantic merge with conflict surfacing** | Not defined | **Gap** | A2A coordinates parallel tasks at the lifecycle level, not at the claim/decision level. |
| **Rule-based + LLM-assisted claim extraction from source** | Not defined | **Gap** | A2A is purely runtime-handoff; no notion of build-from-source. |
| **Decision lineage (ADR-style: context, options, consequences)** | Not defined | **Gap (extension-slot)** | Could be one extension type. |
| **Operational layers (tools, policy, workflow)** | `AgentCard.skills` + `AgentCard.capabilities`; policy not defined | Partial overlap | A2A Agent Card declares skills + auth, not deny-rules or workflow graphs. ARC's `PolicyRule` and `WorkflowStep` are not covered. |
| Tool declarations (name, params, returns) | A2A leans on MCP for tool exposure [A2A Appendix B] | Adjacent | ARC's `ToolDeclaration` overlaps with MCP, not A2A. Extracting tool decls from CrewAI/aider configs is still uncovered. |
| Provenance metadata (builder ID, source inventory, build params) | Not defined | **Gap** | A2A has no build-time concept. |
| Signatures / attestations on artifacts | Not defined | **Gap** | A2A trusts transport-layer auth, not artifact signatures. |
| Update lineage (`parent_archive`, version bumps, rollback detection) | Not defined | **Gap** | A2A tasks don't have persistent versioned state. |
| Diff between artifact versions | Not defined | **Gap** | A2A has no notion of comparable artifacts. |

### Summary of mapping

- 7 capabilities covered by A2A (all transport / lifecycle / discovery / auth) — ARC has 0 of these.
- 13 capabilities are clear gaps (semantic content + verifiability + build-time concerns) — ARC has all of these.
- 1 partial overlap (operational declarations — A2A covers skills via Agent Card, ARC adds policy/workflow).

---

## 3. Specific findings

### 3.1 Where A2A overlaps with ARC

**There is essentially no functional overlap.** ARC has no transport, no discovery, no task lifecycle, no auth, no streaming. A2A has no claim taxonomy, no evidence pointers, no content-addressed storage, no Merkle integrity, no merge.

The one place observers might claim overlap is **"agent-to-agent context passing,"** which both projects describe in their docs. But:

- A2A's "context passing" is a `Message` containing `Part`s [A2A §5.5]. The semantics of the parts are unspecified; `Part.data` is described as "arbitrary structured JSON" and the spec's "Opaque Execution" principle [A2A §3] explicitly says agents collaborate **without** sharing internal thoughts, plans, or tool implementations.
- ARC's "context passing" is a typed-claim artifact with provenance (`docs/protocol.md`, `docs/claim-schema.md`). The semantics of every unit are specified.

These are complementary, not competing. A2A says "here is a way to deliver bytes between agents." ARC says "here is a way to structure bytes that are about reasoning."

### 3.2 Where A2A leaves gaps that ARC fills

Three gaps are spec-confirmed by the task brief:

1. **No semantics for inter-agent content** [A2A §4.4.4, §4.6, §5.5]. `Part.data` is "arbitrary structured JSON." This is the entire surface area where ARC's typed claims protocol sits.
2. **Opaque Execution principle** [A2A §3]. Agents collaborate without exposing internal reasoning. ARC takes the opposite stance: reasoning **is** the artifact (claims with evidence and confidence). This isn't a contradiction — A2A says "you don't have to share reasoning"; ARC says "if you want to, here's how."
3. **No persistent verifiable artifact**. A2A `Artifact` is an in-flight payload [A2A §6.7], not a content-addressed, Merkle-sealed, offline-verifiable, diffable, mergeable, snapshottable file. Even with A2A, you still need somewhere to persist what happened, and that somewhere is undefined.

### 3.3 Where ARC has unique value

Cited from the codebase:

- **Typed claim taxonomy with confidence and status** — `src/arc/models.py:105-157`. Five `claim_type` values, five `status` values; semantics codified in `docs/spec/semantic-model.md` and `docs/claim-schema.md`. No A2A equivalent.
- **Evidence pointers down to file:line** — `src/arc/models.py:24-45`. Traceability 1.0 in the FastAPI/Django benchmarks, vs 0.0 for every retrieval baseline.
- **Conflict auto-detection on merge** — `src/arc/merge.py:101-132` (cosine similarity ≥ 0.45 between decisions from different sources → synthesized `conflict` claim referencing both sides).
- **Content-addressed + Merkle-sealed artifact** — `src/arc/cas.py`, root_digest in `Manifest.compute_root_digest()` (`models.py:388-393`). 100% tamper detection, 100% rollback detection (`tests/test_security_evaluation.py`).
- **Selective loading composing type/source/semantic-query** — `src/arc/loader.py`, CLI surface in `docs/spec/cli-contract.md:50-57`. Not a feature of A2A.
- **Build-from-source pipeline** — `src/arc/builder.py` (8 stages, rule-based default + LLM-assisted opt-in). A2A has no build-time concept; it presumes content already exists.
- **Lightweight snapshot for handoff** — `src/arc/snapshot.py:16-105`. Last-N filter, parent_archive lineage, Merkle integrity preserved, ~40KB for 10 claims (`eval/mcp_benchmark_results.md:51`).

### 3.4 Where ARC is redundant with A2A

If ARC were claiming to do transport, discovery, lifecycle, or auth — it would be redundant. **It does not.** ARC's MCP server exists to surface ARC operations to agents inside one agent's stack; it is not a transport between agents.

ARC's framing of "agent-to-agent context passing" in `README.md`, `docs/protocol.md`, and `docs/architecture.md` (lines 59–87) leans on language that **sounds like** A2A's domain. This framing is what likely triggered the original "A2A killed ARC" reaction. But the actual implementation is artifact production + artifact consumption — not message exchange. The framing is misleading; the substance is not redundant.

---

## 4. Repositioning analysis: ARC as an A2A Extension

### 4.1 What an A2A Extension is (per task brief, [A2A §4.4.4, §4.6])

A URI-identified, optionally-required capability declared in an agent's Agent Card. Extensions can scope to specific message types, parts, or task semantics. They are the architectural slot for layered semantic protocols on top of A2A's transport.

### 4.2 What changes in the ARC codebase

**New surface area (additions):**

- **Extension URI**, e.g. `https://arc-context.io/a2a/extensions/typed-claims/v1`. Conformance doc that maps:
  - ARC's `Claim` JSON → an A2A `Part` of `kind="data"` with `data: {arc_claim: {...}}`
  - ARC's `Manifest` → an A2A `Artifact` referencing one or more typed-claim parts
  - ARC's `arc snapshot` → A2A `SendMessage` with the typed-claim extension Part
  - ARC's `arc merge` → either a client-side operation on received artifacts, or a server-side capability advertised in the Agent Card
- **A2A binding module** (`src/arc/a2a_binding.py`, new):
  - Pack/unpack ARC archives ↔ A2A `Message` / `Artifact` payloads
  - Build an Agent Card snippet (`extensions: [{uri: "...", required: false, params: {schema_version: "1.1.0"}}]`)
  - Optional: a thin server harness that listens for A2A `SendMessage` calls and persists the typed-claim Parts into a local `.arc`
- **Conformance doc** (`docs/a2a-extension.md`, new):
  - Required vs optional Part fields
  - Mapping table claim_type ↔ part metadata
  - Verification semantics across A2A's transport boundary (TLS) plus ARC's artifact boundary (Merkle)
- **Optional A2A reference adapter** for one popular A2A SDK (Python, given the partner ecosystem).

**No changes required to:**

- Core models (`models.py`) — typed claims are already pure data.
- Builder, loader, snapshot, merge, diff, verify, cas — they remain unchanged.
- CLI — unchanged.
- MCP server — unchanged. (MCP and A2A are orthogonal per [A2A Appendix B]; ARC ends up offered via both.)
- Archive format — unchanged. The .arc file is the persistence format; A2A is one of several transports.
- Test suite — unchanged for core; new tests for binding only.

**Removed:**

- Nothing. ARC's "agent-to-agent context passing" framing in README/protocol docs gets rewritten to clarify "ARC is the content semantics; A2A is the transport." This is a docs change, not a code change.

### 4.3 Effort estimate (rough)

Assuming current codebase quality (442 tests, clear separation of concerns):

- Spec + URI + conformance doc: **2–3 days**
- A2A binding module + Agent Card builder + tests: **3–5 days**
- Reference adapter for one A2A SDK: **2–4 days**
- README/protocol/architecture rewrite to position ARC explicitly as the semantic layer atop A2A transport: **1–2 days**
- Submit extension proposal to the A2A community + iterate on feedback: **open-ended (weeks–months external)**

**Engineering total: ~2 weeks of focused work.** Community uptake / standardization: indeterminate.

### 4.4 Risks

1. **Naming / mindshare risk.** The A2A community may already be drafting a "typed content" extension. If so, ARC should aim to contribute rather than compete. This requires investigation, not implementation.
2. **Conformance drift.** A2A is v1.0 but evolving under Linux Foundation governance. ARC bindings must track spec changes.
3. **"Opaque Execution" friction.** [A2A §3] explicitly endorses agents *not* sharing reasoning. An ARC extension is an opt-in counter-stance. Some A2A users may consider it philosophically off-axis. The framing should be: "for handoffs that need provenance and audit, here's a typed structure; for handoffs that don't, A2A's defaults still apply."
4. **Adoption bootstrap.** Extensions need conformance from at least two implementations. Without partner agents wanting this, the URI sits unused.
5. **Scope creep.** Once "ARC is an A2A extension" is on the table, the temptation is to extend further (push notifications for snapshot updates? streaming claim deltas? multi-party merge as a server method?). These should be explicitly out-of-scope for v1 of the extension.

---

## 5. Recommendation

### Choice: **(A) Revive as A2A Extension**

### Top 3 reasons

1. **The "A2A killed ARC" reaction was wrong on the merits.** The capability mapping shows zero functional overlap. A2A explicitly does not define inter-agent content semantics [A2A §3, §4.4.4, §5.5]. ARC's typed-claim protocol fits the A2A Extensions slot precisely. The original decision conflated similar-sounding goals ("agent context passing") with similar substance.
2. **Repositioning is mostly a docs + thin-binding job, not a rewrite.** The codebase is artifact-first; transport was always someone else's problem. Adding A2A as the standard transport layer is additive, not destructive. Estimated ~2 weeks of engineering. Core models, builder, loader, merge, format, tests all stay.
3. **A2A's ecosystem solves ARC's distribution problem.** Standalone, ARC has no path to interop. As an A2A Extension declared in Agent Cards, ARC gets discovery, auth, streaming, lifecycle for free, and inherits a 150-partner ecosystem looking for layered semantic protocols. ARC contributes the missing piece (verifiable typed reasoning) instead of trying to reinvent transport.

### First concrete step

Investigate whether a "typed content" / "verifiable claims" extension is already proposed in the A2A community (mailing lists, GitHub org, Linux Foundation working groups). Before writing one line of binding code:
- Read the A2A Extensions registry, if one exists.
- Search GitHub `topic:a2a-extension`.
- Check the Linux Foundation A2A SIG for existing proposals.
- If nothing exists: draft the extension URI, schema, and a one-page conformance doc and post it for community review **before** building bindings. This avoids wasted bindings against a moving target and avoids competing with a parallel proposal.

### Honest assessment of the original decision

The "A2A killed ARC" call was emotional, not analytical. The trigger appears to have been word-overlap (both talk about agents passing context) plus the prestige of A2A's governance (Linux Foundation, Google origin, 150 partners). On the substance:

- A2A defines the **envelope and channel**.
- ARC defines the **payload semantics and persistence**.
- These do not collide; they compose.

The pause was costly to the extent that ARC was still developing strong differentiators (typed claims, evidence traceability 1.0 vs 0.0 in benchmarks, Merkle-sealed artifacts) that A2A was never going to address. The pause was beneficial to the extent that it forced clarity: ARC's "agent-to-agent" framing in README/protocol/architecture docs is the source of the conflation. Rewriting that framing to clearly say "ARC is the semantic layer; transport is delegated" is overdue and is the cheapest, highest-leverage change to make first.

A weaker but defensible case exists for **(B) standalone but interoperable** if the A2A community is hostile to a non-Google-affiliated semantic extension or already has a competing draft. (B) gets ARC moving without waiting on standards politics, but it forfeits the distribution lever in (3) above. Default to (A); fall back to (B) only on contact with reality.

(C) is wrong on the gap analysis. (D) is premature: nothing in the current scope is broken enough to throw out.

---

## 5b. Second-pass code review (pressure-test)

After the initial analysis, the unread source files (`builder.py`, `loader.py`, `cas.py`, `assembly.py`, `create.py`, `manifest.py`, `provenance.py`, `cli.py`, remainder of `mcp_server.py`) were read in full to pressure-test the recommendation. The recommendation **holds**, with three small adjustments below.

### 5b.1 What the code-level read confirmed

- **`assemble_archive` is the natural binding entry point** (`src/arc/assembly.py:13-127`). It takes plain Python objects (claims, decisions, resources, source units, tools, policies, workflow), writes blobs to a CAS, and emits a manifest. Snapshot, merge, and `create_archive` all funnel through it. An A2A binding wraps this — no new core code path required.
- **`create_archive`** (`src/arc/create.py:12-80`) is already the "agent produces an artifact directly from claims" API the recommendation assumed exists. It even has the right ergonomic for A2A: pass `source="agent-X"` and any unstamped claims get attributed to that sender (`create.py:51-62`).
- **The 8-stage builder is only invoked when building from a source directory** (`src/arc/builder.py:54-350`). The agent-to-agent path (`create_archive` → snapshot → handoff → load) does not touch `_ingest`, `_chunk`, or `extract_*`. An A2A extension does not need to engage with the build pipeline at all — only the `assemble_archive` / `load` / `merge` surface.
- **`load()` returns pure dataclasses with no transport coupling** (`src/arc/loader.py:164-333`). After it reads the SQLite file, everything is in memory. A receiver can mount, filter, and traverse without further I/O.
- **Merkle integrity is enforced at load time, per layer, with re-hashing** (`src/arc/loader.py:251-256`). This isn't aspirational — every blob's SHA-256 is recomputed before deserialization and a mismatch rejects the archive. This validates the "offline-verifiable" claim concretely.
- **Rollback protection is real and parameterized** (`src/arc/loader.py:218-227`, `_version_lt` at lines 594-624). An A2A receiver can pass `expected_min_version` to refuse downgraded artifacts. Useful in adversarial multi-agent settings.
- **`BuildProvenance.builder_id`** (`src/arc/provenance.py:22`) is a self-reported string — confirms the open question about trust boundary. An A2A binding could populate this from the transport-authenticated sender, mapping A2A's auth into ARC's provenance. This is a clean integration point, not a redesign.
- **Source attribution is per-claim, not per-message** (`src/arc/models.py:117`). A2A's `Message` carries one sender. ARC's `Claim` carries `source` per-unit. A single A2A `Message` containing a typed-claim Part can therefore carry claims attributed to *multiple* upstream agents (e.g. an aggregating agent forwarding a merged archive). This is a real semantic gain over plain A2A `Message` semantics — and it works today, no new code needed.

### 5b.2 Adjustments to the recommendation

1. **Locality assumption is shallow but real.** All entry points (`open_cas`, `load`, `verify`, `merge`, `snapshot`) take filesystem paths (`src/arc/cas.py:415-422`). To put ARC behind an A2A endpoint, the binding must materialize received bytes into either a temp file or an in-memory SQLite (the `:memory:` form works in `sqlite3` but `open_cas()` requires `path.is_file()`). Cleanest fix: extend `open_cas()` and `SqliteCAS.__init__` to accept a `bytes` payload or a file-like object. Small surface (~30-60 LOC + tests). **Effort estimate adjustment: +1 day.** Total still ~2 weeks.
2. **No streaming format.** `assemble_archive` writes the manifest atomically at the end (`src/arc/assembly.py:115-126`). A2A supports streaming task responses [A2A §6 — SubscribeToTask], but the v1 ARC extension should explicitly **scope to non-streaming `Artifact` payloads only**. Streaming claim deltas would require designing an event subprotocol and is well outside v1 scope. Already flagged in §4.4 risk #5; reinforced by code.
3. **Claim IDs are random UUIDs by default.** `Claim.id = field(default_factory=_generate_id)` (`src/arc/models.py:113`) seeds with random UUID unless caller passes a seed. Merge dedups by `(text, source)` not by ID (`src/arc/merge.py:77`), so this works fine intra-merge. But if A2A messages are going to *reference* specific upstream claims by ID across an arbitrary number of hops (`Claim.references[]`), agents need a way to produce **stable** IDs from content. The infrastructure already supports this — `_generate_id(seed=...)` returns SHA-256[:16] of the seed (`src/arc/models.py:13-17`), used by tools/policies/workflow. The A2A extension conformance doc should specify a canonical seeding scheme (e.g. `_generate_id(f"claim:{source}:{text_normalized}")`) so cross-agent references resolve deterministically. No code change needed; doc-level decision.

### 5b.3 Things that could have invalidated the recommendation but didn't

- **No hidden runtime coupling.** I expected to find load-time hooks that assume "this archive is being consumed live by a single agent process" — none. The whole stack is read-and-return.
- **No assumption that source units must exist.** `assembly.py:50-54` makes the source-units layer optional. A claims-only artifact (no evidence-traceable provenance) is a valid `.arc`. This is what an A2A extension v1 would actually send most of the time — pure typed claims without bundling source code.
- **No assumption that the producer and consumer share an embedder.** `VectorStore.embedder_state` is serialized into the archive (`src/arc/builder.py:151-157`, restored at `src/arc/loader.py:359-367`). Receivers run filtering with the producer's vocabulary. Means an A2A handoff doesn't require shared retrieval infrastructure between sender and receiver.
- **No dependency on the directory CAS variant.** `SqliteCAS` is the default and is fully self-contained. Single-file = single A2A `Artifact`. Maps cleanly.
- **No I/O during merge other than `load()` of both inputs.** `src/arc/merge.py:46-53` — the merge logic operates purely on in-memory `LoadedArchive` objects. An A2A "merge endpoint" agent could take two inbound Artifacts, load them, merge, and emit a third Artifact, all without exotic plumbing.

### 5b.4 One subtle inconsistency worth flagging

`builder.py:181-186` always emits a `resources` layer with `required=True` for full builds. `assembly.py:44-47` only emits `resources` if non-empty. So a `create_archive`-produced artifact may legitimately lack the resources layer, while a `build_archive`-produced artifact always has it. For A2A binding, the `assemble_archive` path is the right one (claims-only artifacts are normal). But `arc verify` and `arc inspect` should be checked to ensure they don't assume `resources` is present — quick sanity check, not blocker. Not in scope of this analysis to fix.

### 5b.5 Net adjustment to the recommendation

- **Choice unchanged: (A) Revive as A2A Extension.**
- Effort: 2 weeks → **2 weeks + 1 day** (the bytes→archive opening surface).
- Confidence: **higher** than first pass. The implementation is more cleanly separable than the docs alone suggested; transport was always abstracted away by accident-of-design even though it was never named as such.

---

## 6. Open questions

Things this analysis could not resolve from the codebase + task brief alone:

1. **Is there already an A2A extension for verifiable / typed content?** Not visible from the repo. Needs external investigation in the A2A community channels before writing a binding.
2. **What is the actual A2A extension governance / registration process?** The brief cites [A2A §4.4.4, §4.6] but doesn't include the procedural details (who approves a URI, what conformance test suite is required, whether there is a registry).
3. **Does any of ARC's 150-partner-relevant peer (Atlassian, MongoDB, ServiceNow) have an existing requirement for typed-claim handoffs?** Adoption-side question. Not answerable from this repo.
4. **MCP and ARC's `ToolDeclaration`** — current ARC extracts tool decls from CrewAI / aider configs (`tests/test_operational_extraction.py`). With MCP increasingly the standard for tool exposure [A2A Appendix B], should `ToolDeclaration` be deprecated in favor of "ARC archives MCP server descriptors"? Not in scope here, but flagged.
5. **Trust boundary for `source` attribution** — ARC's `source` field is self-reported (`MEMORY.md:124`, "Open question 1"). A2A's authentication can attribute the *transport-level* sender; mapping that into ARC's `source` field is a binding-design question. If we go (A), this needs to be answered in the conformance doc.
6. **Whether ARC's archive format itself should also have an A2A-aware variant** — e.g., should `Manifest.provenance` include the originating Agent Card URL, signed by transport-level identity? This is an interesting design point and the natural next ADR if (A) is pursued.
7. **Scoped-arc demotion** (`docs/large_repo_positioning.md`) — orthogonal to A2A but flagged because it remains an open scaling weakness. Not relevant to the A2A decision.
8. **Bytes-in-memory CAS variant** — a `SqliteCAS` constructor that accepts `bytes` (or `BytesIO`) and uses a `:memory:` SQLite connection seeded from the bytes. Not currently supported (`src/arc/cas.py:207-213`). Worth deciding whether to add this for the A2A binding, or to use the temp-file pattern. Trade-off: temp file is simpler; in-memory avoids touching disk for ephemeral handoffs.
9. **Stable claim ID seeding for cross-agent references** — covered in §5b.2(3). Conformance-doc question, not a code question.
10. **`resources` layer optionality** — covered in §5b.4. Verify/inspect paths should be sanity-checked to confirm they tolerate its absence, since A2A-binding artifacts will often lack it.

---
