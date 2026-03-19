# Research — Findings & Prior Art

> Distilled research insights with trajectory. Links to source material for deeper dives.

---

## Key Findings

### Agent context reconstruction is the core problem
- **Source**: Project thesis
- **When**: Project inception
- **Finding**: Agents waste tokens and reliability because they reconstruct context at runtime from messy sources. More data (connecting Slack, Gmail, Jira, GitHub) makes models drown — they pull irrelevant context and produce worse results than giving them nothing.
- **Impact**: This isn't a tooling problem — it's an information architecture problem. The model needs the right data, structured so it can use it.

### Build-once-load-selectively beats runtime retrieval
- **Source**: Architecture analysis
- **When**: Design phase
- **Finding**: Building context into a verifiable artifact once, then loading task-relevant layers, outperforms runtime RAG in reliability and cost. Deterministic build → selective load > best-effort retrieval.
- **Impact**: Core justification for artifact-first approach

### Content-addressed storage is proven at scale
- **Source**: Git, OCI, IPFS precedents (docs/research/market-landscape.md)
- **When**: Research phase
- **Finding**: CAS with manifest-driven composition is battle-tested in containers (OCI), source control (Git), and distributed systems (IPFS). ARC can reuse these patterns rather than inventing new ones.
- **Impact**: Validates the boring-composable-blocks approach over novel formats

### Semantic compression must preserve traceability
- **Source**: Architecture research
- **When**: Research phase
- **Finding**: Aggressive compression improves context efficiency but can destroy provenance chains. The trust boundary for compression aggressiveness needs empirical evaluation.
- **Impact**: Evaluation harness (Phase 5) is critical — can't ship compression without fidelity benchmarks

### Progressive disclosure fixes model navigation
- **Source**: Memory architecture research
- **When**: 2026-03-15
- **Finding**: Three specific failure modes of flat files: context pollution, conflicting instructions, lost-in-the-middle. Splitting into layers with on-demand loading fixes all three. Structured boundaries immediately improve model behavior.
- **Impact**: Applied to memory/ directory design — routing table + topic files + external refs

---

## Related Tools & Gaps

| Tool/Approach | What it does | What's missing (ARC fills) |
|---------------|-------------|---------------------------|
| RAG / vector DB | Runtime retrieval over embeddings | No artifact boundary, no provenance, no selective load, no verification |
| Agent memory (ChatGPT, etc.) | Key-value or summary persistence | No semantic structure, no versioning, no portability, no trust |
| OCI artifacts | Content-addressed packaging | No semantic layer, no claim/decision model, no agent-facing loading |
| Git repos | Versioned source of truth | No semantic compression, no agent-optimized format, no policy layer |

Source: docs/research/market-landscape.md

---

## Source Documents

| Document | Location | Contains |
|----------|----------|----------|
| Market landscape | `docs/research/market-landscape.md` | Related tools and gaps analysis |
| Source notes | `docs/research/source-notes.md` | Distilled notes from papers and standards |
| Open questions | `docs/research/open-questions.md` | Unresolved research threads |
