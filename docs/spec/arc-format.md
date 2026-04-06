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

## Package format

### Single-file (canonical, default)

A `.arc` file is a SQLite database with two tables:

```sql
blobs(digest TEXT PRIMARY KEY, data BLOB NOT NULL, size INTEGER NOT NULL)
meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
-- meta keys: "manifest", "refs/provenance.json", "meta/inspect-cache.json"
```

Random access by digest via indexed lookup. No unpacking needed. See [`docs/single-file-format.md`](../single-file-format.md).

### Directory (legacy, still supported)

```text
project.arc/
├── manifest.json
├── blobs/sha256/<digest>
├── refs/provenance.json
└── meta/inspect-cache.json
```

`open_cas()` auto-detects file vs directory. Both formats have identical Merkle verification.

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

## Resolved format questions

- **Single-file is canonical.** SQLite is the default output format. Directory is legacy.
- **Blob serialization is JSON in v0.** All layers serialized as JSON with `indent=2, sort_keys=True` for determinism.
- **Layer typing is strict for required layers, lenient for optional.** Unknown optional layers are ignored.

