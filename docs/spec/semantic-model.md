# Semantic Model

## Objective

The semantic layer is what makes ARC more than a glorified file bundle.

It should carry portable meaning, not just bytes.

---

## Core object types

### SourceUnit
Represents an addressable source fragment.

Suggested fields:
- `id`
- `source_id`
- `kind`
- `locator`
- `content_digest`
- `metadata`

### Claim
Represents an atomic assertion.

Suggested fields:
- `id`
- `text`
- `kind`
- `evidence`
- `confidence` optional
- `derived_from`
- `status`

### Decision
Represents a durable choice and its rationale.

Suggested fields:
- `id`
- `title`
- `context`
- `options`
- `decision`
- `consequences`
- `evidence`

### EvidencePointer
Links semantic objects back to source units.

Suggested fields:
- `source_unit_id`
- `span` optional
- `weight` optional

---

## Important modeling rule

A summary without evidence should never pretend to be a verified fact.

So the model should distinguish:

- extracted fact
- inferred summary
- accepted decision
- unresolved hypothesis

---

## Suggested status values

For claims:
- `observed`
- `derived`
- `verified`
- `deprecated`
- `contested`

For decisions:
- `proposed`
- `accepted`
- `superseded`
- `rejected`

