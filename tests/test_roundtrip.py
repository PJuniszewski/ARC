"""Roundtrip tests: build → verify → restore → compare."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from arc.builder import build_archive
from arc.cas import ContentAddressedStore, sha256_digest
from arc.loader import load, restore_sources, verify


class TestBuildVerifyRestoreCompare:
    """Build archive, verify integrity, restore files, compare to originals."""

    def test_roundtrip_corpus(self, corpus_dir, tmp_path):
        """Full roundtrip on the standard corpus."""
        arc_dir = tmp_path / "corpus.arc"
        restored_dir = tmp_path / "restored"

        # Build
        result = build_archive(
            source_dir=corpus_dir,
            output_dir=arc_dir,
            archive_id="arc://roundtrip-test",
            archive_version="1.0.0",
        )
        assert result.valid, f"Build failed: {result.errors}"
        assert len(result.text_units) > 0
        assert len(result.claims) > 0

        # Verify
        v = verify(arc_dir)
        assert v.valid, f"Verify failed: {v.errors}"
        assert len(v.failed_digests) == 0
        assert len(v.missing_blobs) == 0

        # Restore
        restore_result = restore_sources(arc_dir, restored_dir)
        assert len(restore_result["restored_files"]) > 0
        assert restore_result["total_bytes"] > 0
        assert "error" not in restore_result

    def test_roundtrip_aider(self, tmp_path):
        """Roundtrip on Aider fixtures."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "aider"
        arc_dir = tmp_path / "aider.arc"
        restored_dir = tmp_path / "restored"

        result = build_archive(
            source_dir=fixtures_dir,
            output_dir=arc_dir,
            archive_id="arc://agent/aider",
        )
        assert result.valid, f"Build failed: {result.errors}"

        v = verify(arc_dir)
        assert v.valid

        restore_result = restore_sources(arc_dir, restored_dir)
        assert len(restore_result["restored_files"]) > 0

    def test_roundtrip_crewai(self, tmp_path):
        """Roundtrip on CrewAI fixtures."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "crewai"
        arc_dir = tmp_path / "crewai.arc"
        restored_dir = tmp_path / "restored"

        result = build_archive(
            source_dir=fixtures_dir,
            output_dir=arc_dir,
            archive_id="arc://agent/crewai",
        )
        assert result.valid, f"Build failed: {result.errors}"

        v = verify(arc_dir)
        assert v.valid

        restore_result = restore_sources(arc_dir, restored_dir)
        assert len(restore_result["restored_files"]) > 0

    def test_restored_content_preserves_semantics(self, corpus_dir, tmp_path):
        """Restored content must contain all original text (semantic preservation)."""
        arc_dir = tmp_path / "corpus.arc"
        restored_dir = tmp_path / "restored"

        build_archive(
            source_dir=corpus_dir,
            output_dir=arc_dir,
            archive_id="arc://roundtrip-semantics",
        )
        restore_sources(arc_dir, restored_dir)

        # For each restored file, verify key content is preserved
        for restored_file in restored_dir.rglob("*"):
            if not restored_file.is_file():
                continue
            rel = restored_file.relative_to(restored_dir)
            original = corpus_dir / rel
            if not original.exists():
                continue

            restored_text = restored_file.read_text()
            original_text = original.read_text()

            # Key sentences from original should appear in restored
            # (chunking may reformat whitespace, but content is preserved)
            for line in original_text.split("\n"):
                line = line.strip()
                if len(line) > 30 and not line.startswith("#"):
                    assert line in restored_text or line in " ".join(restored_text.split()), (
                        f"Lost content in {rel}: {line[:80]}..."
                    )


class TestTamperDetection:
    """Verify that tampering with blobs, manifest, or deletions is caught."""

    def test_tampered_blob_detected(self, corpus_dir, tmp_path):
        """Modifying a single byte in any blob must cause verify to fail."""
        arc_dir = tmp_path / "tamper.arc"
        result = build_archive(
            source_dir=corpus_dir,
            output_dir=arc_dir,
            archive_id="arc://tamper-test",
        )
        assert result.valid

        # Tamper with the first blob
        cas = ContentAddressedStore(arc_dir)
        blobs = cas.list_blobs()
        assert len(blobs) > 0

        blob_path = cas.blobs_dir / blobs[0]
        data = blob_path.read_bytes()
        # Flip one byte
        tampered = bytes([data[0] ^ 0xFF]) + data[1:]
        blob_path.write_bytes(tampered)

        v = verify(arc_dir)
        assert not v.valid
        assert len(v.failed_digests) > 0

    def test_deleted_blob_detected(self, corpus_dir, tmp_path):
        """Deleting a blob must cause verify to fail."""
        arc_dir = tmp_path / "delete.arc"
        result = build_archive(
            source_dir=corpus_dir,
            output_dir=arc_dir,
            archive_id="arc://delete-test",
        )
        assert result.valid

        cas = ContentAddressedStore(arc_dir)
        blobs = cas.list_blobs()
        # Delete the first blob
        (cas.blobs_dir / blobs[0]).unlink()

        v = verify(arc_dir)
        assert not v.valid
        assert len(v.missing_blobs) > 0

    def test_manifest_tamper_detected(self, corpus_dir, tmp_path):
        """Modifying the manifest root_digest must be detected."""
        arc_dir = tmp_path / "manifest-tamper.arc"
        result = build_archive(
            source_dir=corpus_dir,
            output_dir=arc_dir,
            archive_id="arc://manifest-tamper",
        )
        assert result.valid

        # Tamper with manifest
        manifest_path = arc_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["root_digest"] = "0" * 64  # bogus digest
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))

        v = verify(arc_dir)
        assert not v.valid
        assert any("root_digest" in e for e in v.errors)


class TestDiffBetweenVersions:
    """Build v1 → modify source → build v2 → diff shows changes."""

    def test_diff_shows_added_removed_claims(self, corpus_dir, tmp_path):
        """Diff between two versions shows added/removed claims."""
        from arc.diff import diff_archives

        v1_dir = tmp_path / "v1.arc"
        v2_dir = tmp_path / "v2.arc"
        modified_dir = tmp_path / "modified_corpus"

        # Build v1
        r1 = build_archive(
            source_dir=corpus_dir,
            output_dir=v1_dir,
            archive_id="arc://diff-test",
            archive_version="1.0.0",
        )
        assert r1.valid

        # Create modified corpus
        shutil.copytree(corpus_dir, modified_dir)
        new_file = modified_dir / "new-feature.md"
        new_file.write_text(
            "# New Feature\n\n"
            "## Overview\n\n"
            "This feature provides automatic backup scheduling.\n\n"
            "## Requirements\n\n"
            "The system must support hourly, daily, and weekly backup schedules.\n"
            "All backups should be encrypted at rest using AES-256.\n"
        )

        # Build v2
        r2 = build_archive(
            source_dir=modified_dir,
            output_dir=v2_dir,
            archive_id="arc://diff-test",
            archive_version="2.0.0",
        )
        assert r2.valid

        # Diff
        diff = diff_archives(v1_dir, v2_dir)
        assert len(diff.new_claims) > 0, "Expected new claims from added file"
        assert len(diff.new_blobs) > 0, "Expected new blobs"
