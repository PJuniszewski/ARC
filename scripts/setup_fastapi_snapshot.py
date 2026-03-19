#!/usr/bin/env python3
"""Clone and freeze a repository at a pinned version for large-repo benchmarking.

Usage:
    python scripts/setup_fastapi_snapshot.py [--force]
    python scripts/setup_fastapi_snapshot.py --config path/to/config.json [--force]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "eval" / "large_repo_tasks" / "fastapi" / "REPO_CONFIG.json"


def main():
    parser = argparse.ArgumentParser(description="Set up repository snapshot for benchmarking")
    parser.add_argument("--force", action="store_true", help="Re-clone even if snapshot exists")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH,
        help="Path to repo config JSON (default: FastAPI)",
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text())
    repo_url = config["repo_url"]
    tag = config["tag"]
    exclude_dirs = config["exclude_dirs"]
    snapshot_dir = PROJECT_ROOT / config["snapshot_dir"]

    if snapshot_dir.exists() and not args.force:
        print(f"Snapshot already exists at {snapshot_dir}")
        print("Use --force to re-clone")
        return

    if snapshot_dir.exists():
        print(f"Removing existing snapshot: {snapshot_dir}")
        shutil.rmtree(snapshot_dir)

    # Clone at specific tag into a temp directory
    repo_name = snapshot_dir.name
    tmp_clone = snapshot_dir.parent / f"_{repo_name}_clone_tmp"
    if tmp_clone.exists():
        shutil.rmtree(tmp_clone)

    print(f"Cloning {repo_url} at tag {tag}...")
    subprocess.run(
        ["git", "clone", "--depth=1", "--branch", tag, repo_url, str(tmp_clone)],
        check=True,
    )

    # Verify clone
    result = subprocess.run(
        ["git", "-C", str(tmp_clone), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    actual_sha = result.stdout.strip()
    print(f"Cloned at SHA: {actual_sha}")

    if config.get("sha") and not actual_sha.startswith(config["sha"][:12]):
        print(f"WARNING: Expected SHA prefix {config['sha'][:12]}, got {actual_sha[:12]}")
        print("The tag may have been force-pushed. Proceeding anyway.")

    # Remove excluded directories
    for exclude in exclude_dirs:
        exclude_path = tmp_clone / exclude
        if exclude_path.exists():
            print(f"Excluding: {exclude}/")
            shutil.rmtree(exclude_path)

    # Remove .git directory (we don't need git history in the snapshot)
    git_dir = tmp_clone / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)

    # Move to final location
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_clone.rename(snapshot_dir)

    # Write metadata
    meta = {
        "repo_url": repo_url,
        "tag": tag,
        "sha": actual_sha,
        "exclude_dirs": exclude_dirs,
    }
    meta_path = snapshot_dir.parent / "snapshot_metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    # Count files and LOC
    py_files = list(snapshot_dir.rglob("*.py"))
    md_files = list(snapshot_dir.rglob("*.md"))
    total_loc = 0
    for f in py_files:
        try:
            total_loc += len(f.read_text(errors="replace").splitlines())
        except Exception:
            pass

    print(f"\nSnapshot ready: {snapshot_dir}")
    print(f"  Python files: {len(py_files)}")
    print(f"  Markdown files: {len(md_files)}")
    print(f"  Total Python LOC: {total_loc}")
    print(f"  Metadata: {meta_path}")


if __name__ == "__main__":
    main()
