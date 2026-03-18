# Reasoning Fix Report

Post-retrieval refinement boost for reasoning-bearing text chunks.

## Problem

hybrid_arc decisions_constraints recall = 0.400 (vs hybrid 0.600). Root cause: reasoning sentences ("because", "chose", "rather than") don't match `CLAIM_PATTERNS` in `extract_claims()`, so they're either dropped or become low-confidence fallback docs (0.35), crowded out by code items.

## Fix

1. **New module `src/arc/reasoning.py`**: Regex-based reasoning detection (causal connectives, decision verbs, contrastive markers, ADR headings).
2. **`reasoning_boost` field on `RefinementMode`**: Additive confidence boost applied to reasoning-bearing claims and fallback docs.
3. **Mode-specific boosts**:
   - `decision`: reasoning_boost=0.6 (pushes reasoning claims from ~0.56 to ~1.16)
   - `security`: passthrough_k 3→4, reasoning_boost=0.3
   - `cross_file`: reasoning_boost=0.3
   - `implementation`, `feature`, `balanced`: reasoning_boost=0.0 (unaffected)

## Results (full benchmark, 30 tasks)

### Overall

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| hybrid_arc recall | 0.643 | 0.660 | +0.017 |
| hybrid recall | 0.663 | 0.663 | — |
| Cohen's d (vs hybrid) | -0.079 | -0.014 | improved (closer to parity) |
| Avg tokens | 1,839 | 1,863 | +24 (within budget) |
| Traceability | 1.000 | 1.000 | no change |
| Debuggability | 0.866 | 0.874 | +0.008 |

### Per-Category Context Recall

| Category | Before | After | Delta | Target | Met? |
|----------|--------|-------|-------|--------|------|
| decisions_constraints | 0.400 | 0.500 | +0.100 | ≥ 0.50 | Yes |
| security_config | 0.600 | 0.600 | 0.000 | ≥ 0.65 | No |
| cross_file_reasoning | 0.810 | 0.810 | 0.000 | ≥ 0.80 | Yes |
| implementation_location | 0.600 | 0.600 | 0.000 | ≥ 0.55 | Yes |
| architecture | 0.700 | 0.700 | 0.000 | — | Yes |
| feature_behavior | 0.750 | 0.750 | 0.000 | — | Yes |

### Token Usage

| Category | Avg Tokens |
|----------|-----------|
| Overall | 1,863 |
| architecture | 2,197 |
| cross_file_reasoning | 3,068 |
| decisions_constraints | 1,255 |
| feature_behavior | 1,810 |
| implementation_location | 1,219 |
| security_config | 1,629 |

## What Worked

- **decisions_constraints +0.100**: Reasoning boost pushes "because X chose Y" claims above the confidence threshold, so they survive the max_items cap instead of being crowded out by code items.
- **Zero regressions**: No category lost recall. All modes without reasoning_boost=0.0 are unaffected.
- **Token budget**: 1,863 avg, well under 2,200 ceiling.

## What Didn't Work

- **security_config unchanged at 0.600**: The root cause here is multi-file evidence diversity loss (sec-02, sec-03 need chunks from different files), not reasoning detection. passthrough_k 3→4 and reasoning_boost=0.3 weren't sufficient. This needs a different fix (e.g., file-diversity constraint in chunk selection).

## Assessment

The fix is worth keeping. It closes the worst category gap (decisions_constraints), improves overall recall from 0.643 to 0.660 (now essentially tied with hybrid at 0.663, d=-0.014 negligible), and has zero regressions. The security_config gap (0.600 vs 0.700) remains an open item requiring a diversity-based approach.

## Files Changed

| File | Change |
|------|--------|
| `src/arc/reasoning.py` | NEW — reasoning marker detection (~50 lines) |
| `src/arc/refinement.py` | reasoning_boost field, mode dict updates, boost logic in refine() |
| `scripts/run_large_repo_benchmark.py` | --categories flag for targeted eval |
