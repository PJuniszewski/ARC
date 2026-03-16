# ADR-0004: No Lossy Compression in Builder

## Status
Accepted

## Context
The builder pipeline had a `compression_budget` parameter (default 0.5) that used TF-IDF ranking to permanently discard claims at build time. This was architecturally misplaced for several reasons:

1. **ARC is a portable archive.** The builder's job is to extract and preserve all agent-relevant knowledge from source documents. Discarding claims at build time permanently destroys information that downstream consumers might need.

2. **The loader already does selective retrieval.** The loader's `_filter_by_task()` provides task-aware claim selection using TF-IDF + keyword scoring, evidence graph expansion, and always-include rules for requirements. This is the correct layer for token budget optimization.

3. **Agent archives are small.** A typical ARC archive is ~200KB. Disk and storage savings from claim-level compression are negligible. The relevant resource to optimize is context window tokens at load time, not bytes on disk at build time.

4. **TF-IDF scoring at build time is crude.** Without knowing the downstream task, any ranking-based selection is guessing at relevance. A claim deemed "low importance" by TF-IDF against the full corpus may be exactly what a specific task needs.

5. **Full fidelity enables better evaluation.** With all claims preserved, retrieval quality metrics (precision, recall, RAGAS) measure the loader's actual filtering ability rather than a combination of build-time lossy compression and load-time filtering.

## Decision
The ARC builder preserves full fidelity. Build-time claim processing is limited to:

- **Deduplication:** Remove claims with identical normalized text (exact/near-duplicate detection)
- **Contested exclusion:** Exclude claims flagged as `status: "contested"` (injection-flagged content)

The `compression_budget` parameter is removed from `build_archive()` and the CLI.

Selective loading (token budget optimization) remains the loader's responsibility via task-based filtering, layer selection, and evidence graph traversal.

## Consequences

### Positive
- Archives contain complete extracted knowledge — no information loss
- Loader metrics cleanly measure retrieval quality
- Simpler builder pipeline (8 stages, dedup replaces lossy compression)
- Deterministic builds: same source always produces same claims
- Downstream consumers can apply their own relevance criteria

### Negative
- Archives contain more claims (all unique non-contested claims vs. budget-selected subset)
- Full archive load without task filtering returns more tokens
- Tests that relied on compression ratios needed reworking

### Mitigated by
- Loader's selective loading already handles token reduction per task
- Agent archives remain small (~200KB) regardless
- Platform-level token budgets can further limit what gets mounted into context
