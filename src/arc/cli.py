"""CLI interface for ARC Archive — build, inspect, verify, load, diff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arc",
        description="ARC Archive — Portable, verifiable, semantic archives for AI agents",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # arc build
    build_parser = subparsers.add_parser("build", help="Build archive from sources")
    build_parser.add_argument("source_dir", help="Source directory to archive")
    build_parser.add_argument("--out", required=True, help="Output archive path")
    build_parser.add_argument("--id", default=None, help="Archive ID")
    build_parser.add_argument("--version", default="0.1.0", help="Archive version")
    build_parser.add_argument("--parent", default=None, help="Parent archive for incremental build")

    # arc inspect
    inspect_parser = subparsers.add_parser("inspect", help="Inspect archive contents")
    inspect_parser.add_argument("archive", help="Archive path")
    inspect_parser.add_argument("--json", action="store_true", help="JSON output")

    # arc verify
    verify_parser = subparsers.add_parser("verify", help="Verify archive integrity")
    verify_parser.add_argument("archive", help="Archive path")
    verify_parser.add_argument("--json", action="store_true", help="JSON output")

    # arc load
    load_parser = subparsers.add_parser("load", help="Load archive content")
    load_parser.add_argument("archive", help="Archive path")
    load_parser.add_argument("--task", default=None, help="Task for selective loading")
    load_parser.add_argument("--layer", action="append", default=None, help="Specific layers to load")

    # arc diff
    diff_parser = subparsers.add_parser("diff", help="Compare two archives")
    diff_parser.add_argument("archive_a", help="First archive")
    diff_parser.add_argument("archive_b", help="Second archive")
    diff_parser.add_argument("--json", action="store_true", help="JSON output")

    # arc restore
    restore_parser = subparsers.add_parser("restore", help="Restore source files from archive")
    restore_parser.add_argument("archive", help="Archive path")
    restore_parser.add_argument("--out", required=True, help="Output directory")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    dispatch = {
        "build": _cmd_build,
        "inspect": _cmd_inspect,
        "verify": _cmd_verify,
        "load": _cmd_load,
        "diff": _cmd_diff,
        "restore": _cmd_restore,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        return 1

    try:
        return handler(args)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"Error: permission denied: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _cmd_build(args) -> int:
    from .builder import build_archive

    result = build_archive(
        source_dir=args.source_dir,
        output_dir=args.out,
        archive_id=args.id,
        archive_version=args.version,
        parent_archive=args.parent,
    )

    if result.valid:
        print(f"Archive built: {result.archive_path}")
        print(f"  Resources: {len(result.resources)}")
        print(f"  Text units: {len(result.text_units)}")
        print(f"  Claims: {len(result.claims)}")
        print(f"  Decisions: {len(result.decisions)}")
        if result.deduplication and result.deduplication.duplicates_removed > 0:
            print(f"  Duplicates removed: {result.deduplication.duplicates_removed}")
        print(f"  Layers: {len(result.manifest.layers)}")
        return 0
    else:
        print(f"Build failed with {len(result.errors)} error(s):", file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1


def _cmd_inspect(args) -> int:
    from .cas import ContentAddressedStore
    from .manifest import read_manifest_from_cas

    cas = ContentAddressedStore(Path(args.archive))
    manifest = read_manifest_from_cas(cas)

    if manifest is None:
        print("Error: No manifest found", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(manifest.to_json())
    else:
        print(f"Archive: {manifest.archive_id}")
        print(f"Version: {manifest.archive_version}")
        print(f"Schema: {manifest.schema_version}")
        print(f"Created: {manifest.created_at}")
        print(f"Root digest: {manifest.root_digest[:16]}...")
        if manifest.parent_archive:
            print(f"Parent: {manifest.parent_archive[:16]}...")
        print(f"\nLayers ({len(manifest.layers)}):")
        for layer in manifest.layers:
            req = " [required]" if layer.required else ""
            deps = f" (depends: {', '.join(layer.depends_on)})" if layer.depends_on else ""
            print(f"  {layer.name}: {layer.type} ({layer.digest[:12]}...){req}{deps}")

        # Blob stats
        blobs = cas.list_blobs()
        total_size = cas.archive_size()
        print(f"\nBlobs: {len(blobs)} ({total_size:,} bytes)")

    return 0


def _cmd_verify(args) -> int:
    from .cas import ContentAddressedStore

    cas = ContentAddressedStore(Path(args.archive))
    result = cas.verify_archive()

    if getattr(args, "json", False):
        print(json.dumps({
            "valid": result.valid,
            "failed_digests": result.failed_digests,
            "missing_blobs": result.missing_blobs,
            "errors": result.errors,
        }, indent=2))
    else:
        if result.valid:
            print("Verification: PASSED")
        else:
            print("Verification: FAILED")
            for err in result.errors:
                print(f"  Error: {err}")
            for d in result.failed_digests:
                print(f"  Failed digest: {d[:16]}...")
            for d in result.missing_blobs:
                print(f"  Missing blob: {d[:16]}...")

    return 0 if result.valid else 1


def _cmd_load(args) -> int:
    from .loader import load

    loaded = load(
        archive_path=args.archive,
        layers=args.layer,
        task=args.task,
    )

    if loaded.rejected:
        print(f"Load rejected: {loaded.reason}", file=sys.stderr)
        return 1

    print(f"Loaded archive: {loaded.manifest.archive_id}")
    print(f"  Source units: {len(loaded.source_units)}")
    print(f"  Claims: {len(loaded.claims)}")
    print(f"  Decisions: {len(loaded.decisions)}")
    if loaded.vector_store:
        print(f"  Embeddings: {len(loaded.vector_store.ids)} vectors")

    if args.task:
        print(f"\nRelevant claims for task: '{args.task}'")
        for claim in loaded.claims[:10]:
            print(f"  [{claim.kind}] {claim.text[:100]}...")

    return 0


def _cmd_diff(args) -> int:
    from .diff import diff_archives

    result = diff_archives(args.archive_a, args.archive_b)

    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.summary())

    return 0


def _cmd_restore(args) -> int:
    from .loader import restore_sources

    result = restore_sources(
        archive_path=args.archive,
        output_dir=args.out,
    )

    if result.get("error"):
        print(f"Restore failed: {result['error']}", file=sys.stderr)
        return 1

    print(f"Restored {len(result['restored_files'])} files ({result['total_bytes']:,} bytes)")
    for f in result["restored_files"]:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
