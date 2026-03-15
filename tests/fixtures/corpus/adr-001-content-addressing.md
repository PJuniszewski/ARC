# ADR-001: Content Addressing for Archive Blobs

## Context

ARC needs a reliable way to identify and verify archive content. We need to choose between path-based references, UUID-based identifiers, or content-addressed hashing.

## Decision

We will use SHA-256 content addressing for all archive blobs. Each blob is stored at a path derived from its content hash. The manifest references blobs by their digest.

## Consequences

- Deduplication is automatic — identical content produces the same hash
- Tamper detection is built-in — any modification changes the digest
- Incremental updates only need to store new or modified blobs
- Blob references are stable and portable across environments
- The archive layout is compatible with OCI artifact conventions
