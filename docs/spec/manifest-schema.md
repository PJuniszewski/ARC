# Manifest Schema

## Purpose

The manifest is the root authority of an ARC archive.

If manifest semantics are sloppy, the entire format becomes slippery.

---

## Minimum fields

```json
{
  "schema_version": "0.1.0",
  "archive_id": "arc://project/example",
  "archive_version": "0.1.0",
  "created_at": "2026-03-15T00:00:00Z",
  "root_digest": "sha256:...",
  "layers": [],
  "provenance": {},
  "compatibility": {}
}
```

---

## Suggested fields

### Identity
- `schema_version`
- `archive_id`
- `archive_version`
- `created_at`

### Content
- `layers`
- `entrypoints`
- `default_mount_policy`

### Trust
- `signatures`
- `attestations`
- `provenance`
- `freshness`

### Compatibility
- `requires_loader`
- `requires_features`
- `optional_features`

### Lineage
- `parent_archive`
- `diff_base`
- `build_id`

---

## Layer object sketch

```json
{
  "name": "claims",
  "type": "semantic.claims",
  "digest": "sha256:...",
  "media_type": "application/arc+json",
  "required": true,
  "depends_on": ["source-units"]
}
```

---

## Manifest rules

- `archive_id` stays stable across versions of the same logical archive
- `archive_version` changes when archive content changes
- `digest` references must be immutable
- layer names should be stable within an archive family
- dependency cycles between layers are invalid

