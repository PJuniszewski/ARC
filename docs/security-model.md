# Security Model

## Brutal truth

If ARC becomes a trusted source of context, then ARC becomes a high-value attack surface.

That means security is not a hardening phase.
It is part of the format.

---

## Security goals

ARC should help ensure:

- integrity of archive contents
- provenance of built artifacts
- controlled updates
- safe treatment of source-derived content
- safe loading of optional executable layers

---

## Threat classes

### 1. Source poisoning
Attacker manipulates raw docs, tickets, comments, or code to smuggle false facts or malicious instructions.

### 2. Indirect prompt injection
Source material contains text crafted to hijack an agent that later consumes the archive.

### 3. Archive tampering
Blobs or manifest are modified after build.

### 4. Rollback / stale archive substitution
A valid but older archive is served as if it were current.

### 5. Provenance forgery
Attacker claims archive came from a trusted builder or trusted inputs when it did not.

### 6. Policy/tool layer abuse
An executable or policy bundle does something broader than declared.

### 7. Over-trust in compression
Important nuance is removed during semantic compression, leading to false certainty.

---

## Security principles

1. data is not instructions
2. immutable internals
3. explicit trust metadata
4. offline verifiability where practical
5. least privilege for executable layers
6. human-auditable inspect surface

---

## Required controls

### Integrity
- digest each blob
- digest the manifest root
- fail closed on mismatch

### Provenance
- record builder identity
- record source inputs
- record build parameters and time
- attach attestations where possible

### Update safety
- support freshness / version policy
- detect rollback attempts
- make downgrade explicit, never silent

### Prompt injection containment
- classify archive content as data by default
- never elevate source-derived text into instructions without explicit policy
- preserve source boundaries and provenance

### Executable layers
- optional only in v0
- sandbox required
- explicit permissions contract
- independently verifiable identity and digest

---

## Trust boundaries

```text
external source
-> ingestion
-> extraction/compression
-> archive packaging
-> signing/attestation
-> loader verification
-> runtime use
-> model output
```

Each boundary needs a clear answer for:

- what is trusted?
- what is verified?
- what can be stale?
- what can execute?

---

## Design implications

### Manifest must expose
- format version
- blob digests
- semantic layer types
- build provenance references
- signature / attestation references
- update lineage references

### Semantic objects should expose
- source pointers
- confidence if used
- extraction method if relevant
- last-derived timestamp

### Loader must support
- strict verify mode
- permissive inspect-only mode
- stale-check policy mode

---

## Open security questions

- how much trust can be delegated to builder automation?
- do claims need confidence plus review status?
- should archives distinguish “verified facts” vs “generated summaries” explicitly?
- how should runtime be forced to prefer evidence over summaries when stakes are high?

