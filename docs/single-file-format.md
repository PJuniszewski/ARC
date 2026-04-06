# Single-file Archive Format

## Problem

ARC archives were directories with 5+ files (`manifest.json`, `blobs/sha256/*`, `refs/`, `meta/`). You can't commit a directory to a CI artifact, drag it into Slack, or attach it to a ticket. Single-file packaging removes the adoption barrier.

## Format choice: SQLite

SQLite was chosen over zip/tar because:

- **Random access**: look up any blob by digest via indexed PRIMARY KEY — no decompression or full scan needed
- **Zero dependencies**: `sqlite3` is in Python stdlib since 3.0
- **Merkle verification works without reading entire file**: read manifest (1 row), then verify each layer blob individually
- **WAL mode**: concurrent readers with one writer — ideal for build-once-read-many

## Schema

```sql
CREATE TABLE blobs (
    digest TEXT PRIMARY KEY,  -- SHA-256 hex string
    data   BLOB NOT NULL,     -- raw layer content (JSON)
    size   INTEGER NOT NULL   -- byte count for fast archive_size()
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,   -- logical path (e.g. "manifest", "refs/provenance.json")
    value TEXT NOT NULL        -- JSON text
);
```

The `meta` table stores everything that isn't a content-addressed blob:
- `"manifest"` → the manifest JSON (previously `manifest.json` file)
- `"refs/provenance.json"` → build provenance
- `"meta/inspect-cache.json"` → optional inspection cache

## How random access works

Loading a single claim layer from a 50MB archive:
1. SQLite reads the manifest from `meta` table (one indexed lookup)
2. Parse manifest JSON, find the `semantic.claims` layer digest
3. SQLite reads the claims blob from `blobs` table (one indexed lookup)
4. Deserialize JSON into Claim objects

No other blobs are read. Total I/O: two small reads from an indexed database.

## How verification works

Same as directory format — Merkle integrity is preserved:
1. Read manifest from `meta` table
2. Verify `root_digest` by recomputing SHA-256 of manifest (excluding the root_digest field itself)
3. For each layer, read blob data and verify `sha256(data) == layer.digest`

Each step is an independent database query. No need to read the entire file.

## Architecture

Two CAS backends with the same interface:
- `ContentAddressedStore` — directory-based (legacy, still supported)
- `SqliteCAS` — single-file SQLite (new default)

Factory functions:
- `open_cas(path)` — auto-detects: `path.is_file()` → SQLite, `path.is_dir()` → directory
- `create_cas(path, fmt="sqlite")` — creates new archive in specified format

All consumers (builder, loader, diff, snapshot, merge, create) use factory functions. The CAS backend is invisible to them.

## Migration from directory format

- Old directory-based archives continue to work forever via `open_cas()` auto-detection
- `arc build` CLI defaults to SQLite (`--format directory` for legacy)
- `build_archive()` Python API defaults to directory format for backward compat
- No conversion tool needed — both formats are first-class

## File sizes

| Corpus | Directory size | SQLite size | Ratio |
|--------|---------------|-------------|-------|
| Test corpus (9 docs) | ~15 KB (5 blobs) | ~4 KB | 0.3x |
| ARC src/ (34 files) | ~8 KB | ~4 KB | 0.5x |

SQLite is typically smaller because it avoids filesystem overhead (one inode per blob file).
