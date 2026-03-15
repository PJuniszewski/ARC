# Architecture

## One-line model

ARC is a build-time and load-time system for turning messy project context into a portable, verifiable archive for agents.

---

## System split

ARC should be reasoned about as five layers:

1. **Source layer**
   - repos
   - docs
   - ADRs
   - tickets
   - policies
   - logs

2. **Builder layer**
   - ingest
   - normalize
   - extract semantics
   - compress
   - write blobs
   - emit manifest

3. **Artifact layer**
   - content-addressed objects
   - manifest
   - optional local package or OCI transport
   - signatures / attestations

4. **Loader layer**
   - verify
   - resolve dependencies
   - mount selected layers
   - expose query surface to runtime

5. **Runtime layer**
   - task-aware retrieval
   - policy enforcement
   - agent-facing context assembly

---

## High-level flow

```text
sources
-> builder
-> semantic units + blobs + manifest + trust metadata
-> .arc archive
-> loader verify + selective mount
-> agent runtime consumes only what it needs
```

---

## Why this split matters

If build, format, and runtime are fused together, ARC becomes framework sludge.

The project should preserve clear boundaries:

- **builder** decides how raw sources become semantic artifacts
- **format** defines what is portable
- **loader** decides how archives are mounted and verified
- **runtime** decides how the agent uses loaded content

That separation keeps the format durable even if builders and runtimes evolve.

---

## Conceptual object model

### Source unit
A chunk or unit derived from original input with stable identity and provenance.

### Claim
An atomic assertion extracted from one or more source units.

### Decision
A structured record of rationale, options, and chosen path.

### Evidence pointer
A pointer from a claim or decision to the supporting source unit(s).

### Policy bundle
Rules or data that constrain runtime behavior.

### Index shard
Retrieval-oriented structure such as embedding shards or lexical indexes.

### Manifest
The root description of the archive and how all parts fit together.

---

## Recommended v0 architecture

### Keep in v0

- local-first archive layout
- immutable blobs
- one canonical root manifest
- claim and decision objects
- optional vector metadata
- verify / inspect / diff CLI

### Push later

- full graph-native execution engine
- advanced semantic merge
- full OCI-native-only workflow
- general-purpose executable plugin marketplace

---

## Build-time responsibilities

Builder should handle:

- source ingestion
- normalization
- chunking
- extraction of claims and decisions
- semantic compression with traceability
- writing immutable blobs
- generating manifest
- producing provenance metadata

Builder should **not** silently mutate prior archives.

---

## Load-time responsibilities

Loader should handle:

- digest verification
- signature and attestation checks
- compatibility validation
- layer selection
- task-aware selective mounting
- safe exposure to the runtime

Loader should **not** invent missing semantics.

---

## Runtime responsibilities

Runtime should:

- choose relevant mounted context
- combine claim/evidence/policy layers
- feed agents grounded inputs
- enforce or consult policies where needed

Runtime should **not** be the only place truth exists.

---

## Trust boundaries

Trust must be evaluated at each hop:

```text
raw source -> builder -> archive -> loader -> runtime -> model
```

Questions to answer:

- Was the source trustworthy?
- Was the builder policy-compliant?
- Was the archive tampered with?
- Was the mounted subset stale or incomplete?
- Did runtime treat data as instructions?

---

## Architecture principles

1. artifact first
2. provenance by default
3. immutable internals
4. explicit manifests
5. selective loading
6. security-first semantics
7. runtime portability

