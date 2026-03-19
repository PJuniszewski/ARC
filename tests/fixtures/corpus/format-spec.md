# ARC Format Specification

## Archive Layout

An ARC archive follows this directory structure:

```
project.arc/
├── manifest.json
├── blobs/sha256/<digest>
├── refs/provenance.json
└── meta/
```

## Archive Classes

ARC defines three archive classes with increasing completeness:

- **Minimal**: source units + claims + manifest
- **Standard**: source units + claims + decisions + provenance + manifest
- **Extended**: all standard layers plus policies, index metadata, and signatures

## Manifest Schema

The manifest requires these fields:
- schema_version: semantic version string
- archive_id: stable identifier across versions
- archive_version: changes when content changes
- created_at: ISO 8601 timestamp
- root_digest: SHA-256 hash covering all other manifest fields
- layers: array of layer descriptors

Each layer has a name, type, digest, media_type, required flag, and optional depends_on array. Dependency cycles between layers are invalid.

## Compatibility

The archive format follows these compatibility rules:
- Unknown optional fields should be ignored
- Unknown required layer types should cause load failure
- The manifest schema version must be explicit
- Archive ID stays stable across versions while archive_version changes
