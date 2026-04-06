"""End-to-end tests for SQLite single-file archives."""

import pytest

from arc.builder import build_archive
from arc.cas import open_cas
from arc.create import create_archive
from arc.diff import diff_archives
from arc.loader import load, verify
from arc.merge import merge
from arc.models import Claim
from arc.snapshot import snapshot


class TestSqliteBuild:
    def test_build_produces_single_file(self, corpus_dir, tmp_path):
        out = tmp_path / "project.arc"
        result = build_archive(corpus_dir, out, output_format="sqlite")
        assert result.valid
        assert out.is_file()
        assert not out.is_dir()

    def test_sqlite_verify(self, corpus_dir, tmp_path):
        out = tmp_path / "project.arc"
        build_archive(corpus_dir, out, output_format="sqlite")
        v = verify(out)
        assert v.valid

    def test_sqlite_load(self, corpus_dir, tmp_path):
        out = tmp_path / "project.arc"
        build_archive(corpus_dir, out, output_format="sqlite")
        loaded = load(out)
        assert not loaded.rejected
        assert len(loaded.claims) > 0
        assert len(loaded.source_units) > 0

    def test_sqlite_load_with_task(self, corpus_dir, tmp_path):
        out = tmp_path / "project.arc"
        build_archive(corpus_dir, out, output_format="sqlite")
        loaded = load(out, task="security threat model")
        assert not loaded.rejected
        assert len(loaded.claims) > 0

    def test_sqlite_inspect(self, corpus_dir, tmp_path):
        from arc.cli import main
        out = tmp_path / "project.arc"
        build_archive(corpus_dir, out, output_format="sqlite")
        ret = main(["inspect", str(out)])
        assert ret == 0

    def test_sqlite_diff(self, corpus_dir, tmp_path):
        import shutil
        a = tmp_path / "a.arc"
        b = tmp_path / "b.arc"
        build_archive(corpus_dir, a, output_format="sqlite", archive_version="1.0.0")

        modified = tmp_path / "modified"
        shutil.copytree(corpus_dir, modified)
        (modified / "new.md").write_text(
            "# New Feature\n\n"
            "## Overview\n\n"
            "This feature provides automatic backup scheduling for all archives.\n\n"
            "## Requirements\n\n"
            "The system must support hourly, daily, and weekly backup schedules.\n"
            "All backups should be encrypted at rest using AES-256.\n"
        )
        build_archive(modified, b, output_format="sqlite", archive_version="2.0.0")

        diff = diff_archives(a, b)
        assert len(diff.new_claims) > 0


class TestSqliteProtocol:
    def test_create_produces_single_file(self, tmp_path):
        out = tmp_path / "agent.arc"
        claims = [
            Claim(text="test observation", claim_type="observation", source="agent"),
            Claim(text="test decision", claim_type="decision", source="agent"),
        ]
        create_archive(str(out), claims)
        assert out.is_file()

        loaded = load(str(out))
        assert len(loaded.claims) == 2

    def test_snapshot_produces_single_file(self, corpus_dir, tmp_path):
        full = tmp_path / "full.arc"
        build_archive(corpus_dir, full, output_format="sqlite")

        snap = tmp_path / "snap.arc"
        snapshot(str(full), str(snap), last=5)
        assert snap.is_file()

        loaded = load(str(snap))
        assert len(loaded.claims) == 5

    def test_merge_produces_single_file(self, tmp_path):
        a = tmp_path / "a.arc"
        create_archive(str(a), [
            Claim(text="obs a", claim_type="observation", source="agent-a"),
        ])
        b = tmp_path / "b.arc"
        create_archive(str(b), [
            Claim(text="obs b", claim_type="observation", source="agent-b"),
        ])

        merged = tmp_path / "merged.arc"
        result, _ = merge(str(a), str(b), str(merged))
        assert merged.is_file()
        assert result.merged_claims == 2

    def test_full_protocol_single_file(self, corpus_dir, tmp_path):
        """Full protocol: build → snapshot → create → merge → verify."""
        # Build from source
        full = tmp_path / "full.arc"
        build_archive(corpus_dir, full, output_format="sqlite")
        assert full.is_file()
        assert verify(full).valid

        # Snapshot
        snap = tmp_path / "snap.arc"
        snapshot(str(full), str(snap), last=5)
        assert verify(snap).valid

        # Agent creates
        agent = tmp_path / "agent.arc"
        create_archive(str(agent), [
            Claim(text="new finding", claim_type="observation", source="agent-x"),
        ])
        assert verify(agent).valid

        # Merge
        merged = tmp_path / "merged.arc"
        merge(str(snap), str(agent), str(merged))
        assert verify(merged).valid

        loaded = load(str(merged))
        sources = {c.source for c in loaded.claims}
        assert "agent-x" in sources


class TestSqliteSize:
    def test_archive_is_compact(self, corpus_dir, tmp_path):
        """SQLite archive should be reasonably compact."""
        out = tmp_path / "project.arc"
        build_archive(corpus_dir, out, output_format="sqlite")
        size_mb = out.stat().st_size / (1024 * 1024)
        assert size_mb < 5, f"Archive is {size_mb:.1f}MB, expected < 5MB"
