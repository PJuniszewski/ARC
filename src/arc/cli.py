"""CLI interface for ARC — build, inspect, verify, load, diff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _suppress_library_noise() -> None:
    """Silence noisy warnings from sentence-transformers / HuggingFace / MLX."""
    import logging as _logging
    import os as _os
    import warnings

    warnings.filterwarnings("ignore", message=".*unauthenticated.*HF Hub.*")
    warnings.filterwarnings("ignore", category=FutureWarning)
    for name in ("sentence_transformers", "transformers", "huggingface_hub", "mlx"):
        _logging.getLogger(name).setLevel(_logging.ERROR)
    _os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    _os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    _os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    _os.environ.setdefault("MLX_VERBOSE", "0")
    # Suppress the BertModel LOAD REPORT table printed by mlx_engine
    _os.environ.setdefault("MLX_LOAD_REPORT", "0")


def main(argv: list[str] | None = None) -> int:
    _suppress_library_noise()
    parser = argparse.ArgumentParser(
        prog="arc",
        description="ARC (Agent Reasoning Context) — portable, verifiable context packaging for AI agents",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # arc build
    build_parser = subparsers.add_parser("build", help="Build archive from sources")
    build_parser.add_argument("source_dir", help="Source directory to archive")
    build_parser.add_argument("--out", required=True, help="Output archive path")
    build_parser.add_argument("--id", default=None, help="Archive ID")
    build_parser.add_argument("--version", default="1.0.0", help="Archive version")
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
    load_parser.add_argument("--raw", action="store_true", help="Search raw source chunks instead of extracted claims")
    load_parser.add_argument(
        "--code", action="store_true", help="Filter to code files only (exclude .md, .txt, .json, .yaml)"
    )
    load_parser.add_argument("--ext", default=None, help="Filter to specific extension (e.g. --ext .kt)")

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
    import time

    from .builder import build_archive

    t0 = time.monotonic()

    def _on_progress(stage: str, detail: str) -> None:
        elapsed = time.monotonic() - t0
        if stage == "done":
            return
        print(f"  [{stage}] {detail}  ({elapsed:.1f}s)", file=sys.stderr, flush=True)

    result = build_archive(
        source_dir=args.source_dir,
        output_dir=args.out,
        archive_id=args.id,
        archive_version=args.version,
        parent_archive=args.parent,
        on_progress=_on_progress,
    )

    elapsed = time.monotonic() - t0

    if result.valid:
        print(f"\nArchive built: {result.archive_path}  ({elapsed:.1f}s)")
        print(f"  Resources:  {len(result.resources)}")
        print(f"  Text units: {len(result.text_units)}")
        print(f"  Claims:     {len(result.claims)}")
        print(f"  Decisions:  {len(result.decisions)}")
        if result.deduplication and result.deduplication.duplicates_removed > 0:
            print(f"  Deduped:    {result.deduplication.duplicates_removed} removed")
        print(f"  Layers:     {len(result.manifest.layers)}")
        return 0
    else:
        print(f"\nBuild failed with {len(result.errors)} error(s):", file=sys.stderr)
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

    ext_filter = getattr(args, "ext", None)
    code_only = getattr(args, "code", False)
    if args.task and getattr(args, "raw", False):
        _print_raw_results(loaded, args.task, code_only=code_only, ext_filter=ext_filter)
    elif args.task and loaded.claims:
        _print_claim_results(loaded, args.task)

    return 0


def _print_claim_results(loaded, task: str) -> None:
    """Display claim-based search results with provenance."""
    su_by_id = {tu.id: tu for tu in loaded.source_units}
    res_by_id = {r.id: r for r in loaded.resources}

    print(f"\n{'─' * 60}")
    print(f"  Query: {task}")
    print(f"  Results: {len(loaded.claims)} claims")
    print(f"{'─' * 60}")

    for i, claim in enumerate(loaded.claims[:10], 1):
        source_hint = ""
        su = None
        if claim.evidence:
            su = su_by_id.get(claim.evidence[0].source_unit_id)
        elif claim.derived_from:
            su = su_by_id.get(claim.derived_from)

        if su:
            res = res_by_id.get(su.resource_id)
            loc = res.locator if res else "?"
            source_hint = f"  {loc}:{su.span[0]}-{su.span[1]}"

        kind_label = claim.kind.upper()
        print(f"\n  {i}. [{kind_label}]{source_hint}")
        _print_wrapped(claim.text, indent=5, width=76)


_DOC_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".xml", ".graphql", ".proto"}


def _print_raw_results(loaded, task: str, code_only: bool = False, ext_filter: str | None = None) -> None:
    """Search raw source units (code + docs) via embeddings and display results."""
    from .embeddings import VectorStore, get_embedder

    res_by_id = {r.id: r for r in loaded.resources}

    # Filter source units by file type if requested
    source_units = loaded.source_units
    if code_only or ext_filter:
        filtered = []
        for tu in source_units:
            res = res_by_id.get(tu.resource_id)
            if not res:
                continue
            loc = res.locator
            ext = "." + loc.rsplit(".", 1)[-1] if "." in loc else ""
            if ext_filter and ext != ext_filter:
                continue
            if code_only and ext in _DOC_EXTENSIONS:
                continue
            filtered.append(tu)
        source_units = filtered

    if not source_units:
        print("\n  No matching source units found.")
        return

    # Build a temporary vector index over source units
    texts = [tu.content for tu in source_units]
    embedder = get_embedder(force_tfidf=False)
    embedder.fit(texts)

    store = VectorStore(index_info=embedder.get_index_info())
    for tu in source_units:
        vec = embedder.embed(tu.content)
        store.add(tu.id, vec, tu.content, {"resource_id": tu.resource_id})

    query_vec = embedder.embed(task)
    results = store.search(query_vec, top_k=10)

    su_by_id = {tu.id: tu for tu in source_units}

    mode_label = "raw"
    if ext_filter:
        mode_label += f" [{ext_filter}]"
    elif code_only:
        mode_label += " [code only]"

    print(f"\n{'─' * 60}")
    print(f"  Query: {task}")
    print(f"  Mode: {mode_label}  ({len(source_units)} chunks searched)")
    print(f"  Results: {len(results)} chunks")
    print(f"{'─' * 60}")

    for i, (tu_id, score, _text) in enumerate(results, 1):
        tu = su_by_id.get(tu_id)
        if not tu:
            continue
        res = res_by_id.get(tu.resource_id)
        loc = res.locator if res else "?"
        print(f"\n  {i}. [{tu.kind.upper()}]  {loc}:{tu.span[0]}-{tu.span[1]}  (score: {score:.3f})")
        _print_wrapped(tu.content, indent=5, width=76)


def _print_wrapped(text: str, indent: int = 4, width: int = 76) -> None:
    """Print text wrapped at word boundaries with indentation."""
    prefix = " " * indent
    # Take first ~500 chars to avoid dumping huge claims
    text = text.strip()
    if len(text) > 500:
        text = text[:497] + "..."
    for paragraph in text.split("\n"):
        line = prefix
        for word in paragraph.split():
            if len(line) + len(word) + 1 > width and line.strip():
                print(line)
                line = prefix + word
            else:
                line = line + " " + word if line.strip() else prefix + word
        if line.strip():
            print(line)


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
