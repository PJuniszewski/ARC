"""Integration tests for the loader — verify, selective mount, version checks."""

import pytest

from arc.loader import load, verify


class TestVerification:
    def test_valid_archive(self, built_archive, tmp_archive):
        """Valid archive passes verification."""
        result = verify(tmp_archive)
        assert result.valid

    def test_missing_manifest(self, tmp_path):
        """Archive without manifest fails verification."""
        empty = tmp_path / "empty.arc"
        empty.mkdir()
        result = verify(empty)
        assert not result.valid

    def test_corrupted_blob(self, built_archive, tmp_archive):
        """Corrupted blob fails verification."""
        from arc.cas import ContentAddressedStore
        cas = ContentAddressedStore(tmp_archive)
        blobs = cas.list_blobs()
        assert len(blobs) > 0

        # Corrupt first blob
        blob_path = cas.blobs_dir / blobs[0]
        blob_path.write_bytes(b"corrupted data")

        result = verify(tmp_archive)
        assert not result.valid


class TestLoad:
    def test_load_all(self, built_archive, tmp_archive):
        """Loading without filters returns all content."""
        loaded = load(tmp_archive)
        assert not loaded.rejected
        assert len(loaded.claims) > 0
        assert len(loaded.source_units) > 0

    def test_load_specific_layers(self, built_archive, tmp_archive):
        """Loading specific layers only returns those layers."""
        loaded = load(tmp_archive, layers=["claims"])
        assert not loaded.rejected
        assert len(loaded.claims) > 0
        assert len(loaded.source_units) == 0  # not requested

    def test_load_with_task(self, built_archive, tmp_archive):
        """Task-based loading filters to relevant claims."""
        full = load(tmp_archive)
        selective = load(tmp_archive, task="security threats and attacks")

        assert not selective.rejected
        assert len(selective.claims) > 0
        # Selective should have fewer or equal claims
        assert len(selective.claims) <= len(full.claims)

    def test_load_decisions(self, built_archive, tmp_archive):
        """Decisions are loaded correctly."""
        loaded = load(tmp_archive)
        assert len(loaded.decisions) >= 2

    def test_flat_search(self, built_archive, tmp_archive):
        """Flat text search returns relevant claims."""
        loaded = load(tmp_archive)
        results = loaded.flat_search("SHA-256 content addressing")
        assert len(results) > 0
        # At least one result should mention SHA-256 or content
        texts = " ".join(c.text for c in results).lower()
        assert "sha-256" in texts or "content" in texts or "hash" in texts

    def test_evidence_graph_traversal(self, built_archive, tmp_archive):
        """Graph traversal finds related claims across documents."""
        loaded = load(tmp_archive)
        results = loaded.traverse_evidence_graph("security and verification")
        assert len(results) > 0


class TestVersionControl:
    def test_version_check_passes(self, built_archive, tmp_archive):
        """Loading with satisfied min version succeeds."""
        loaded = load(tmp_archive, expected_min_version="0.9.0")
        assert not loaded.rejected

    def test_version_check_fails(self, built_archive, tmp_archive):
        """Loading with unsatisfied min version is rejected."""
        loaded = load(tmp_archive, expected_min_version="2.0.0")
        assert loaded.rejected
        assert "rollback" in loaded.reason.lower() or "version" in loaded.reason.lower()
