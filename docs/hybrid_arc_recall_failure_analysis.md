# Hybrid_ARC Recall Failure Analysis

## Summary

hybrid_arc v1 achieves recall=0.568 vs hybrid's 0.663 — a 14.3% gap. 14 of 30 tasks lose recall, 4 gain, 12 tie. This document categorizes each failing task by root cause to guide targeted improvements.

---

## Failure Modes

| # | Mode | Description |
|---|------|-------------|
| 1 | Useful raw chunk removed too early | Top hybrid chunks dropped by refinement pipeline |
| 2 | Claim extraction missed impl detail | Specific identifiers (function names, file paths) lost in extraction |
| 3 | Code chunk too aggressively compressed | MAX_ITEM_TOKENS=800 truncates key code |
| 4 | Docs/code balancing wrong | Doc claims outnumber code in ranking |
| 5 | Evidence grouping dropped diversity | Single-source items crowd out multi-file coverage |
| 6 | Token budget too strict | Budget caps relevant items |
| 7 | Detail not representable as claims | Reasoning ("because/since"), code structure, config semantics |

---

## Per-Task Failure Matrix

| Task | Hybrid | H_ARC | Delta | Mode 1 | Mode 2 | Mode 3 | Mode 4 | Mode 5 | Mode 6 | Mode 7 | Primary Root Cause |
|------|--------|-------|-------|--------|--------|--------|--------|--------|--------|--------|-------------------|
| **Tasks that lost recall** |||||||||||||
| dec-02 | 0.50 | 0.00 | -0.50 | X | | | | | | X | Reasoning text ("chose because") not extractable as claims |
| loc-01 | 1.00 | 0.50 | -0.50 | X | X | | | | | | "get_openapi in fastapi/openapi/utils.py" in raw chunks but not in claims |
| arch-03 | 0.75 | 0.50 | -0.25 | X | | | X | | | | include_router merge — doc claims outnumber code |
| arch-04 | 1.00 | 0.75 | -0.25 | | | X | | | | | Middleware stack code truncated at 800 tokens |
| dec-01 | 0.75 | 0.50 | -0.25 | X | | | | | | X | "Why Starlette?" — reasoning doesn't match claim regex |
| dec-03 | 0.50 | 0.25 | -0.25 | | | | | | | X | Declaration-order matching — implicit design reasoning |
| dec-04 | 0.50 | 0.25 | -0.25 | | | | | | | X | OpenAPI 3.1.0 choice — reasoning in prose, not claims |
| feat-01 | 0.75 | 0.50 | -0.25 | | X | X | | | | | Path param validation — code identifiers lost + truncation |
| loc-02 | 0.50 | 0.25 | -0.25 | | X | | | | | | Pydantic validation location — function names dropped |
| sec-02 | 1.00 | 0.75 | -0.25 | | | | | X | | | CORS middleware — multi-file evidence compressed to single source |
| sec-03 | 1.00 | 0.75 | -0.25 | | | | | X | | | SecurityScopes — evidence across files compressed |
| xfile-02 | 0.50 | 0.25 | -0.25 | | | | X | X | | | Exception handler + middleware — docs dominate, diversity lost |
| xfile-03 | 0.75 | 0.50 | -0.25 | | | | X | | | | Router-level deps — doc claims outnumber propagation code |
| xfile-04 | 1.00 | 0.75 | -0.25 | | | X | | | | | OAuth2 flow — multi-file code truncated |
| **Tasks that gained recall** |||||||||||||
| xfile-01 | 0.40 | 0.80 | +0.40 | | | | | | | | Code weighting (1.5x) surfaced relevant code hybrid underranked |
| arch-05 | 0.75 | 1.00 | +0.25 | | | | | | | | Claim extraction captured key assertion about dependency_cache |
| feat-04 | 0.50 | 0.75 | +0.25 | | | | | | | | Code chunks preserved verbatim with high ranking |
| loc-03 | 0.25 | 0.50 | +0.25 | | | | | | | | Code weighting surfaced solver code |

---

## Failure Mode Frequency

| Mode | Count | Affected Tasks |
|------|-------|---------------|
| 1. Raw chunk removed | 4 | dec-02, loc-01, arch-03, dec-01 |
| 2. Impl detail missed | 3 | loc-01, feat-01, loc-02 |
| 3. Code compressed | 3 | arch-04, feat-01, xfile-04 |
| 4. Docs/code imbalance | 3 | arch-03, xfile-02, xfile-03 |
| 5. Diversity dropped | 3 | sec-02, sec-03, xfile-02 |
| 6. Token budget strict | 0 | (max_items is binding, not budget) |
| 7. Non-claim-representable | 4 | dec-01, dec-02, dec-03, dec-04 |

**Key insight**: Mode 6 (token budget) is never the binding constraint — max_items=10 from the benchmark always hits first. Current avg tokens = 1420, well below budget of 3700. This means we have ~580 tokens of headroom for adding passthrough chunks.

---

## Root Cause Analysis by Category

### decisions_constraints (0.600 → 0.350, -41.7%)
All 4 losses are Mode 7 (reasoning not representable as claims). "Why" questions need causal reasoning that `extract_claims()` regex doesn't match. Passthrough raw chunks would preserve the reasoning prose that hybrid retrieves.

### implementation_location (0.550 → 0.450, -18.2%)
2 of 3 losses are Mode 2 (impl detail missed). Specific identifiers like "get_openapi in fastapi/openapi/utils.py" appear in raw chunks but are dropped when claims are extracted. Passthrough preserves these verbatim.

### cross_file_reasoning (0.680 → 0.610, -10.3%)
Losses from Mode 3 (truncation), Mode 4 (docs/code imbalance), Mode 5 (diversity). These tasks need broad multi-file coverage that single-source compression hurts.

### security_config (0.700 → 0.600, -14.3%)
Mode 5 (diversity) is primary. Security tasks need evidence from multiple files that gets compressed to single sources.

### architecture (0.700 → 0.650, -7.1%)
Moderate losses from truncation and docs/code imbalance, partially offset by code weighting gains.

### feature_behavior (0.750 → 0.750, 0%)
No net change. Losses from feat-01 offset by gains from feat-04.

---

## Prescribed Fixes

### Fix 1: Raw chunk passthrough lane
**Targets**: Mode 1 (4 tasks), Mode 2 (3 tasks), Mode 7 (4 tasks)
**Mechanism**: Keep top-k raw hybrid chunks verbatim in output. These chunks are exactly what gives hybrid its 0.663 recall.
**Expected impact**: Recovers dec-02 (reasoning text preserved), loc-01 (identifiers preserved), dec-01/dec-03/dec-04 (prose preserved).

### Fix 2: Task-aware refinement modes
**Targets**: All modes
**Mechanism**: Detect query type (implementation/decision/cross_file/feature/security) and adjust passthrough_k, code_weight, docs_weight per type.
**Expected impact**: "Where" questions get more passthrough (5) + higher code weight. "Why" questions get 4 passthrough chunks to preserve reasoning.

### Fix 3: Code minimum guarantee
**Targets**: Mode 4 (3 tasks)
**Mechanism**: Ensure at least min_code_items code chunks survive the max_items cap by boosting their confidence.
**Expected impact**: arch-03, xfile-02, xfile-03 recover code that was crowded out by doc claims.

### Fix 4: Mode-specific truncation limits
**Targets**: Mode 3 (3 tasks)
**Mechanism**: Implementation mode gets max_item_tokens=1000 (vs 800 default). Cross-file gets 900.
**Expected impact**: arch-04, feat-01, xfile-04 retain more code context.

---

## Token Budget Arithmetic

With passthrough (balanced mode, passthrough_k=3):
- 3 passthrough chunks x ~400 tokens avg = ~1200 tokens
- 7 remaining items x ~100 tokens avg (claims are short) = ~700 tokens
- **Total: ~1900 tokens avg** (within 2000 target, well within 3700 budget)

With passthrough (implementation mode, passthrough_k=5):
- 5 passthrough x ~400 = ~2000 tokens
- 5 remaining items x ~100 = ~500 tokens
- **Total: ~2500 tokens** (implementation queries currently avg 773 tokens per chunk, so chunks are smaller)

max_items=10 remains the binding constraint, not token_budget.

---

## Data Source

- Per-task scores: `reports/large-repo-results.json`
- Task definitions + required_facts: `eval/large_repo_tasks/tasks.json`
- Previous failure analysis: `docs/arc_v2_failures.md`
