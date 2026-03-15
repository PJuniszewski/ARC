# Builder Pipeline

## Purpose

The builder turns messy raw context into a portable ARC artifact.

The builder is where most value is created and most mistakes are introduced.
So its stages need to be explicit.

---

## Proposed stages

### 1. Source ingestion
Collect inputs from:
- repos
- docs
- ADRs
- tickets
- policies
- logs

Outputs:
- source inventory
- normalized metadata

### 2. Normalization
Convert sources into stable internal representations.

Examples:
- markdown -> text sections
- code -> file/symbol metadata
- tickets -> structured issue records

### 3. Chunking / source units
Produce addressable source units with provenance.

Outputs:
- source unit ids
- byte or line spans where relevant
- parent source linkage

### 4. Semantic extraction
Extract:
- claims
- decisions
- entities or relations if needed
- evidence pointers

### 5. Semantic compression
Reduce bulk while preserving traceability.

Rules:
- never compress without source linkage
- distinguish extracted fact from generated summary
- preserve enough evidence to audit results

### 6. Index generation
Optionally create:
- vector shards
- lexical indexes
- relation maps

### 7. Artifact assembly
Write:
- blobs
- manifest
- provenance records
- optional signature bundle references

### 8. Validation
Check:
- schema correctness
- internal reference validity
- missing evidence
- duplicate or contradictory ids

---

## Builder anti-patterns

Do not let builder:

- silently drop provenance
- generate claims with no evidence path
- mutate prior artifacts in place
- rely on hidden external state with no trace
- mix trusted and untrusted inputs without marking them

---

## MVP builder output

For v0, builder should output enough to prove the end-to-end flow:

- manifest
- source unit blobs
- claim blobs
- decision blobs
- provenance blob
- optional index metadata blob

