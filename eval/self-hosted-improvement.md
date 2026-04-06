# Self-hosted Benchmark Improvement Log

## Benchmark: ARC on ARC repo (src/arc/, 24 Python files)

### Baseline (pre-Level 1)

| Metric | ARC claims | ARC search | Naive grep |
|--------|-----------|-----------|-----------|
| Fact recall | 41% | 59% | 75% |
| Avg tokens | 840 | 2436 | 2227 |
| Wins (of 15) | 4 | 8 | 4 |
| Token savings vs grep | 62% | -9% | — |

Claims extracted: 104

### Level 1: Stop throwing away good claims

**Changes:**
- `MAX_FILTERED_CLAIMS`: 12 → 20
- `TOP_K_BASE`: 8 → 10, `TOP_K_FLOOR`: 3 → 5, `TOP_K_RATIO`: 0.1 → 0.15
- Dynamic scaling: `TOP_K = max(10, int(n * 0.15))`, `MAX_TOTAL = max(20, int(n * 0.25))`
- Text normalization: split snake_case/camelCase before TF-IDF scoring
- Substring boost: +0.15 per query token found as substring in claim text (max 0.4)

**Results:**

| Metric | Before | After L1 | Delta |
|--------|--------|----------|-------|
| Fact recall | 41% | 51% | **+10%** |
| Avg tokens | 840 | 1171 | +331 |
| Wins | 4 | 5 | +1 |
| Token savings | 62% | 47% | -15% |

**Per-task changes:**

| Task | Before | After | Change |
|------|--------|-------|--------|
| hash-algo | 0% | 67% | **+67%** (substring boost caught "sha256" in CAS claims) |
| claim-types | 60% | 100% | **+40%** (more claims returned, all 5 types found) |
| arcconfig | 0% | 17% | +17% (partial, TOML not in any claim yet) |
| corrupt-handling | 0% | 0% | no change (DatabaseError not in any claim) |
| merkle-root | 0% | 0% | no change (root_digest computation not in any claim) |
| evidence-trace | 0% | 0% | no change (EvidencePointer details not in claims) |

**Dogfood queries:**
- "What hash algorithm does CAS use?" → 10 claims (was 0), CAS-related but sha256 not explicit
- "How does claim extraction work?" → 19 claims, relevant extractors surfaced
- "What is the merge conflict detection strategy?" → 21 claims, generic, cosine threshold missing

**Assessment:** 51% is good progress but below 60% target. Proceeding to Level 2.

### Level 2: Make claims carry meaning

**Changes:**
- New `_build_signature_claim()`: for functions without docstrings, build claim from name + params + return type + key calls from body
- Example: `sha256_digest (data: bytes) -> str uses hashlib.sha256`
- Fallback: fires only when docstring is absent or too short (< 15 chars)
- Language-agnostic: works on any function chunk with a declaration line

**Results:**

| Metric | After L1 | After L2 | Delta |
|--------|----------|----------|-------|
| Fact recall | 51% | 53% | **+2%** |
| Avg tokens | 1171 | 1268 | +97 |
| Claims extracted | 104 | 118 | +14 |

**Analysis:** Small delta because:
- `sha256_digest` claim IS generated and IS returned, but benchmark fact "SHA-256" (with hyphen) doesn't match "sha256" (without). 2 of 3 facts match → 67%, same as L1.
- New claims are low-confidence (0.75) and get ranked below existing claims
- The wins were already captured by L1's substring boost

**Per-task changes from L1 → L2:**

| Task | After L1 | After L2 | Change |
|------|----------|----------|--------|
| evidence-trace | 0% | 20% | +20% (EvidencePointer now in signature claims) |
| arcconfig | 17% | 33% | +16% (TOML, scan appear in signature claims) |
| All others | same | same | — |

**L1 + L2 combined: 53%.** Below 65% target. Proceeding to Level 3.

### Level 3: Signature claims for ALL functions

**Changes:**
- Generate signature claims (name + params + return type + key calls) for ALL functions, not just those without docstrings
- Functions WITH docstrings get both: docstring claim (0.85 conf) + signature claim (0.7 conf)
- This means every function in the codebase has a signature claim that lists its key dependencies

**Results:**

| Metric | After L2 | After L3 | Delta |
|--------|----------|----------|-------|
| Fact recall | 53% | 63% | **+10%** |
| Avg tokens | 1268 | 1952 | +684 |
| Claims extracted | 118 | ~160 | +42 |
| Wins (of 15) | 5 | 6 | +1 |
| Token savings vs grep | 43% | 12% | -31% |

**Per-task changes from L2 → L3:**

| Task | After L2 | After L3 | Change |
|------|----------|----------|--------|
| evidence-trace | 20% | 100% | **+80%** (EvidencePointer fields in signature) |
| conflict-detect | 25% | 50% | +25% (cosine, merge calls in signatures) |
| merkle-root | 0% | 25% | +25% (compute_root_digest signature visible) |
| arcconfig | 33% | 50% | +17% (TOML, scan in CLI signatures) |
| corrupt-handling | 0% | 0% | no change (DatabaseError is exception, not call) |

## Summary

| Level | Fact recall | Tokens | Claims | Token savings | Wins |
|-------|-----------|--------|--------|---------------|------|
| Baseline | 41% | 840 | 104 | 62% | 4 |
| After L1 | 51% | 1171 | 104 | 47% | 5 |
| After L2 | 53% | 1268 | 118 | 43% | 5 |
| After L3 | 63% | 1952 | ~160 | 12% | 6 |

**Total improvement: +22 percentage points (41% → 63%).**

Tradeoff: token savings dropped from 62% to 12%. More claims = more recall = more tokens.

**Remaining 0% tasks (unfixable by extraction):**
- `corrupt-handling`: facts are exception names (DatabaseError) — not extractable as claims
- ARC claims mode is not designed to replace grep for implementation-detail queries

**Claims mode now beats grep on 6/15 tasks** while providing typed, traceable context.
ARC search mode still wins on 8/15 tasks for semantic queries.
