# ARC v2 Post-Retrieval Refinement — Failure Analysis

## Summary

hybrid_arc (post-retrieval refinement) achieves **0.568 recall** vs hybrid's **0.663** — a 14.3% gap, outside the 5-10% target. However, it delivers 73.4% token reduction, 1.0 traceability, and 0.817 debuggability (unique among all systems).

---

## Tasks Where Refinement Hurt Recall

14 of 30 tasks showed recall loss. 4 showed recall gain. 12 tied.

### Worst losses (≥0.50 drop)

| Task | Hybrid | Hybrid_ARC | Delta | Root Cause |
|------|--------|-----------|-------|------------|
| dec-02 | 0.50 | 0.00 | -0.50 | "Why Pydantic?" — reasoning sentences don't match claim patterns (no "is/uses/implements" verbs) |
| loc-01 | 1.00 | 0.50 | -0.50 | OpenAPI schema location — claim extraction loses code-structure context present in raw chunks |

### Moderate losses (0.25 drop)

| Task | Hybrid | Hybrid_ARC | Delta | Pattern |
|------|--------|-----------|-------|---------|
| arch-03 | 0.75 | 0.50 | -0.25 | include_router merge logic — code context lost in extraction |
| arch-04 | 1.00 | 0.75 | -0.25 | Middleware stack — truncation clips relevant code |
| dec-01 | 0.75 | 0.50 | -0.25 | "Why Starlette?" — reasoning doesn't match claim regex |
| dec-03 | 0.50 | 0.25 | -0.25 | Declaration-order matching — implicit design decision |
| dec-04 | 0.50 | 0.25 | -0.25 | OpenAPI 3.1.0 choice — reasoning in prose, not claims |
| feat-01 | 0.75 | 0.50 | -0.25 | Path param validation — code detail lost in truncation |
| loc-02 | 0.50 | 0.25 | -0.25 | Pydantic validation location — short doc chunks miss |
| sec-02 | 1.00 | 0.75 | -0.25 | CORS middleware — multi-file context compressed too much |
| sec-03 | 1.00 | 0.75 | -0.25 | SecurityScopes — evidence across files compressed |
| xfile-02 | 0.50 | 0.25 | -0.25 | Exception handler + middleware interaction |
| xfile-03 | 0.75 | 0.50 | -0.25 | Router-level dependency propagation |
| xfile-04 | 1.00 | 0.75 | -0.25 | OAuth2 flow — multi-file, truncation clips |

### Tasks where refinement gained recall

| Task | Hybrid | Hybrid_ARC | Delta | Why |
|------|--------|-----------|-------|-----|
| xfile-01 | 0.40 | 0.80 | +0.40 | Pydantic model flow — code weighting (1.5x) surfaced relevant code chunks that hybrid underranked |
| arch-05 | 0.75 | 1.00 | +0.25 | Dependency cache — claim extraction captured key assertion |
| feat-04 | 0.50 | 0.75 | +0.25 | UploadFile — code chunks preserved verbatim with high ranking |
| loc-03 | 0.25 | 0.50 | +0.25 | DI graph — code weighting surfaced solver code |

---

## Failure Patterns

### 1. Claim extraction misses reasoning (decisions_constraints category)

**Impact**: Recall drops from 0.600 to 0.350 on decisions_constraints.

`extract_claims()` matches sentences with verbs like "is/uses/implements/supports". Design rationale sentences like "FastAPI chose X because Y" or "The reason for this is..." don't match these patterns. "Why" questions inherently need reasoning context that the claim regex doesn't capture.

**Potential fix**: Add reasoning-specific patterns (`because`, `since`, `therefore`, `the reason`, `chosen over`) to CLAIM_PATTERNS.

### 2. Token budget truncates relevant code (800 token cap per item)

**Impact**: Code chunks averaging 1000-3000 tokens get truncated to 800, losing tail-end functions and class methods.

The MAX_ITEM_TOKENS=800 limit was set to hit the token reduction target. Without it, tokens blow up to 11K+ per query. With it, some code context is clipped.

**Tradeoff**: This is inherent to the compression goal. Higher budget = more recall, more tokens.

### 3. Doc chunks that produce claims lose context

**Impact**: Claim extraction takes a sentence out of its markdown section, losing list items, code examples, and surrounding context that contributed to hybrid's recall.

The section heading enrichment in `extract_claims()` partially mitigates this, but bullet-point lists and code blocks within markdown sections are not captured.

---

## Per-Category Token Compression

| Category | Hybrid (avg tokens) | Hybrid_ARC (avg tokens) | Reduction |
|----------|-------------------|----------------------|-----------|
| architecture | 14,898 | 1,856 | 88% |
| decisions_constraints | 4,095 | 688 | 83% |
| feature_behavior | 6,513 | 1,569 | 76% |
| cross_file_reasoning | 4,530 | 2,295 | 49% |
| implementation_location | 776 | 773 | 0% |
| security_config | 1,286 | 1,342 | -4% |

**Key insight**: The biggest compression wins (architecture 88%, decisions 83%) correspond to the biggest recall losses. Categories where hybrid loads many large doc chunks see the most compression — and the most information loss.

Implementation_location and security_config show near-zero compression because they load mostly code chunks that are already compact.

---

## Latency

Refinement adds ~1ms per query (regex-based claim extraction, no LLM calls). Negligible compared to the 115s+ embedding build time.

---

## Honest Assessment

hybrid_arc is **not** a drop-in replacement for hybrid retrieval. It is a different system with a different tradeoff profile:

| Dimension | Hybrid | Hybrid_ARC | Winner |
|-----------|--------|-----------|--------|
| Recall | 0.663 | 0.568 | Hybrid |
| Tokens loaded | 5,350 | 1,420 | Hybrid_ARC (73% less) |
| Traceability | 0.000 | 1.000 | Hybrid_ARC |
| Debuggability | 0.000 | 0.817 | Hybrid_ARC |
| Token efficiency | 0.993 | 0.998 | Hybrid_ARC |

**Use hybrid_arc when**: you need traceable, debuggable context and can tolerate ~14% recall loss. Ideal for audit trails, compliance, and debugging.

**Use hybrid when**: raw recall is the priority and you don't need provenance.

---

## Next Steps to Close the Recall Gap

1. **Extend claim patterns** for reasoning/decision language
2. **Adaptive token budget** per category (more for code-heavy, less for doc-heavy)
3. **Hybrid fallback**: if refined recall < threshold, include top-k raw hybrid chunks
4. **Selective truncation**: truncate doc claims more aggressively, keep code less truncated
