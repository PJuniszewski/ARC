# MEMORY.md

This is the live working memory for the ARC project.
It is intentionally short, practical, and updated often.

---

## Project snapshot

**Project name:** ARC Archive
**Purpose:** portable semantic archive format for AI agent context
**Current stage:** working implementation with 181 tests, evaluation harness, production quality gate
**Primary environment:** Claude Code
**Test status:** 233 pass, 7 skip (LLM-dependent without API key)

---

## Core thesis

Agents keep wasting tokens and reliability because they reconstruct context at runtime from messy sources.

ARC proposes a better model:

- build once from trusted inputs
- package context into a verifiable artifact
- load only task-relevant layers
- preserve provenance and diffability

---

## What ARC currently is (implemented)

### Archive format (directory-based CAS)
- `manifest.json` — root entry point with `root_digest` integrity seal
- `blobs/sha256/<digest>` — content-addressed blob storage
- `refs/provenance.json` — build provenance
- 7 layers: source-units, claims, decisions, embeddings + 3 optional operational (tools, policy, workflow)

### Builder (8-stage pipeline)
- Ingest → Normalize → Chunk → Extract → Deduplicate → Index → Assemble → Validate
- Rule-based claim extraction with section heading enrichment
- Injection detection (5 regex patterns → confidence penalty + contested status)
- Dual embedder: sentence-transformers (all-MiniLM-L6-v2, 384d) with TF-IDF fallback (256d)
- Embedder state serialized in archive for aligned restore at load time

### Loader (selective loading)
- Manifest validation, rollback protection, blob integrity verification
- Hybrid vector + keyword scoring: `score = cosine_sim + 0.3 * kw_boost + heading_boost`
- Evidence graph expansion gated by hybrid score ≥ 0.10
- Multi-hop BFS with hybrid OR gate (token overlap OR vector relevance)
- Hard caps: 12 for task filtering, 30 for BFS

### Semantic model
- **TextUnit**: addressable chunk with (resource_id, span, content_digest)
- **Claim**: atomic assertion with kind (fact/requirement/definition/assertion), evidence pointers, confidence, status
- **Decision**: ADR-style structured record (title, context, options, consequences)
- **EvidencePointer**: link from claim/decision to source unit

### Operational model (ADR-0005)
- **ToolDeclaration**: agent capability with name, parameters, constraints, status (active/deprecated/experimental)
- **PolicyRule**: constraint with scope, effect (allow/deny/require_approval), priority
- **WorkflowStep**: agent, task, or config step with dependencies, tool refs, agent refs

### Evaluation
- RAGAS metrics: context precision, recall (1-hop + multi-hop), faithfulness, answer relevancy, composite
- LLM judge (Claude Haiku) for honest precision/relevancy scoring
- Security: tamper detection, rollback detection, evidence traceability, injection containment, poisoned claim confidence
- Behavioral eval: 30 tasks × 3 agents (claude-code, aider, crewai) with IR metrics + Cohen's d effect sizes
- External corpus eval: aider + crewai fixtures with RAGAS, composite 0.68
- Production quality gate: sentence-transformers composite > 0.85

### Current numbers (sentence-transformers)
- Composite RAGAS: 0.91 (internal), 0.68 (external)
- Context precision: 0.94 (term-matching) / 0.77 (LLM)
- Context recall: 0.91 (1-hop), 0.83 (multi-hop)
- Faithfulness: 1.00
- Tamper detection: 100%, Rollback detection: 100%
- Evidence traceability: 100%, Injection containment: 100%

### Large-repo benchmark (FastAPI 0.115.0, 30 tasks)
- ARC context recall: 0.388 — beats TF-IDF (0.282, d=+0.39) but loses to hybrid (0.663, d=-1.06) and vector (0.597, d=-0.77)
- ARC evidence traceability: 1.000 (unique advantage, all baselines = 0.000)
- Root cause of recall gap: 809 markdown doc claims dilute 45 Python code claims
- On tied tasks, ARC uses 5-20× fewer tokens than hybrid

### ARC v2: Post-retrieval refinement (hybrid_arc)
- Context recall: 0.660 — 0.5% below hybrid (0.663), Cohen's d = -0.014 (negligible, essentially tied)
- Token reduction: 65.1% vs hybrid (1,863 avg tokens vs 5,350)
- Evidence traceability: 1.000, debuggability: 0.874 (all baselines: 0.000)
- Task-aware refinement modes: implementation/decision/cross_file/feature/security/balanced
- Reasoning boost: reasoning-bearing chunks get confidence boost in decision/security/cross_file modes
- Raw chunk passthrough lane preserves top-k hybrid chunks verbatim for recall
- Surpasses hybrid on cross_file_reasoning (0.810 vs 0.680) and implementation_location (0.600 vs 0.550)
- Pipeline: hybrid fetch 30 → detect mode → passthrough top-k → classify code/docs → extract claims → reasoning boost → code guarantee → token budget cap
- Full results: `reports/large-repo-summary.md`, reasoning fix: `docs/reasoning_fix_report.md`

---

## What is not yet implemented

- Signatures and attestations (spec exists at `docs/provenance-signing.md`)
- OCI artifact mapping (designed for local-first → OCI later)
- Single-file packaging (currently directory only)
- CLI beyond basic build/load/verify (`src/arc/cli.py` exists but minimal)
- Incremental archive updates (parent_archive plumbing exists but untested at scale)
- Sandboxed executable layers (explicitly deferred from v0; operational layers are declarative-only)

---

## Open questions

1. **Trust boundary for builder**: Who/what do we trust produced the archive?
   - human-reviewed only?
   - builder-signed?
   - multi-party attested?

2. **Single-file packaging**: Should `.arc` support tarball/zip alongside directory?
   - directory only for dev, tar.gz for distribution, OCI for registry?

3. **Incremental update semantics**: How do diffs between archive versions work at scale?
   - parent_archive reference exists but merge/diff model not defined

---

## Risks to watch

- turning ARC into vague "agent memory" branding
- over-designing format before proving developer value
- inventing a graph monster that nobody can maintain
- ignoring prompt injection in source material — **mitigated: injection detection + contested claim exclusion**
- pretending provenance is optional
- coupling too hard to one agent runtime
- **documentation claim dilution on large repos** — markdown-heavy repos swamp code claims in the vector index (demonstrated in FastAPI benchmark)
- **claim extraction misses reasoning** — mitigated by reasoning boost in refinement (decisions_constraints improved 0.400→0.500); security_config still at 0.600 vs hybrid 0.700 (root cause: multi-file diversity, not reasoning)

---

## Near-term priorities

### Priority 1 (done)
~~Define a clean format skeleton~~ — implemented in `src/arc/`

### Priority 2 (done)
~~Define semantic payloads~~ — TextUnit, Claim, Decision, EvidencePointer in `src/arc/models.py`

### Priority 3 (partially done)
Define trust model — threat model documented, CAS integrity implemented, **signatures/attestations not yet implemented**

### Priority 4 (done)
~~Define evaluation harness~~ — 211 tests, RAGAS + security + behavioral eval + operational extraction

### Priority 5 (next)
Signatures and attestations — implement the trust chain from `docs/provenance-signing.md`

### Priority 6
CLI polish — make `arc build`, `arc load`, `arc verify`, `arc inspect` production-ready

### Priority 7
Distribution — OCI mapping, single-file packaging, registry integration

---

## Current decisions-in-spirit

These are directionally accepted:

- `MEMORY.md` and `INDEX.md` stay separate (ADR-0003)
- ARC is artifact-first, not chatbot-memory-first (ADR-0002)
- No lossy compression in builder (ADR-0004)
- Operational layers are optional, declarative, not executable in v0 (ADR-0005)
- verification is a feature, not a nice-to-have
- diffability matters as much as storage
- builder and loader are separable components
- hybrid scoring (vector + keyword) is the retrieval strategy
- sentence-transformers is production embedder, TF-IDF is zero-dep fallback
- LLM judge is the honest metric; term-matching is labeled fallback

---

## What to update after each session

Update this file when any of these change:

- project phase
- accepted design direction
- top open questions
- key risks
- next concrete tasks
- evaluation numbers

