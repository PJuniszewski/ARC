# ARC Format

## Definition

An ARC archive is a portable package of agent-relevant context with:

- a root manifest
- immutable referenced content blobs
- typed semantic payloads
- optional trust and index layers

ARC is an artifact contract, not just a storage convention.

---

## Design goals

- portability
- verifiability
- selective load
- incremental update friendliness
- semantic clarity

---

## Canonical concepts

### Archive
A named versioned package representing one logical context snapshot.

### Manifest
The root metadata object that defines the archive contents and relationships.

### Blob
An immutable content-addressed object.

### Layer
A logical category of blobs, such as claims, decisions, policies, or indexes.

### Package layout
How the archive is represented on disk or in transport.

---

## Recommended local layout

```text
project.arc/
├── manifest.json
├── blobs/
│   ├── sha256/
│   │   ├── aa/...
│   │   ├── bb/...
│   │   └── ...
├── refs/
│   ├── provenance.json
│   └── signatures.json
└── meta/
    └── inspect-cache.json
```

This can later map to a single-file package or OCI transport.

---

## Required archive properties

- exactly one root manifest
- every referenced blob must be content-addressed
- every semantic object must declare a type
- every claim or decision must have evidence or explicitly state why not
- version and compatibility fields must be present

---

## Archive classes

### Minimal archive
- source units
- claims
- manifest

### Standard archive
- source units
- claims
- decisions
- provenance
- manifest

### Extended archive
- source units
- claims
- decisions
- policies
- index metadata or shards
- signatures / attestations
- manifest

---

## Compatibility rules

- manifest schema version must be explicit
- unknown optional fields should be ignorable
- unknown required layer types should fail unless compatibility policy says otherwise
- archive id and version should be separate concepts

---

## Open format questions

- should single-file `.arc` be canonical or only a transport wrapper?
- should blob serialization be JSON only in v0?
- how strict should layer typing be across versions?

