# Roadmap

## Roadmap principle

Do not build the cathedral before proving the hallway.

The first job is to prove that ARC can be:

- built
- inspected
- verified
- loaded selectively
- diffed

If those five are shaky, everything else is cosmetic.

---

## Phase 0 — repo and spec foundation

### Outcomes

- repo structure exists
- navigation is clean
- architecture docs exist
- initial ADRs exist

### Exit criteria

- someone new can understand the repo in under 20 minutes
- top-level concepts are not contradictory

---

## Phase 1 — minimal format skeleton

### Scope

- archive layout
- root manifest
- blob addressing
- inspect command contract
- verify command contract

### Deliverables

- `arc-format.md`
- `manifest-schema.md`
- sample archive tree
- fixture examples

### Exit criteria

- a minimal `.arc` can be described unambiguously
- integrity verification logic is straightforward

---

## Phase 2 — semantic payload model

### Scope

- source unit model
- claim model
- decision model
- evidence pointers

### Deliverables

- `semantic-model.md`
- templates for claims and decisions
- example payload files

### Exit criteria

- builder can output portable semantic objects
- a claim can always point back to evidence

---

## Phase 3 — loader and selective mount

### Scope

- layer classification
- mount rules
- compatibility checks
- task-aware loading hints

### Deliverables

- `loader-runtime.md`
- manifest fields for load policy
- examples for selective load

### Exit criteria

- loader can mount a subset without violating archive semantics

---

## Phase 4 — trust chain

### Scope

- signatures
- attestations
- provenance model
- update trust and rollback handling

### Deliverables

- `provenance-signing.md`
- verification policy examples
- trust flow diagrams

### Exit criteria

- consumers can answer who built this, from what, and whether it is trustworthy

---

## Phase 5 — benchmarking and validation

### Scope

- fidelity tests
- retrieval tests
- security tests
- diff / merge tests

### Deliverables

- evaluation harness plan
- benchmark fixture definitions
- regression checklist

### Exit criteria

- ARC can be compared against naive runtime retrieval

---

## Phase 6 — transport and interoperability

### Scope

- local package vs directory layout
- OCI mapping
- external index references
- possible runtime integrations

### Exit criteria

- archive can move between machines and runtimes without losing meaning

