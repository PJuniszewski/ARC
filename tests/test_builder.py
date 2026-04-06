"""Integration tests for the builder pipeline — end-to-end build from corpus."""

import json
from pathlib import Path

import pytest

from arc.builder import build_archive
from arc.cas import ContentAddressedStore
from arc.manifest import read_manifest_from_cas, validate_manifest


class TestBuildPipeline:
    def test_build_from_corpus(self, corpus_dir, tmp_archive):
        """Build a complete archive from test corpus."""
        result = build_archive(
            source_dir=corpus_dir,
            output_dir=tmp_archive,
            archive_id="arc://test",
            archive_version="1.0.0",
        )
        assert result.valid, f"Build failed: {result.errors}"
        assert len(result.resources) > 0
        assert len(result.text_units) > 0
        assert len(result.claims) > 0

    def test_manifest_is_valid(self, built_archive):
        """Built manifest passes validation."""
        errors = validate_manifest(built_archive.manifest)
        assert errors == [], f"Manifest errors: {errors}"

    def test_all_layers_present(self, built_archive):
        """Archive has expected layers."""
        layer_names = {l.name for l in built_archive.manifest.layers}
        assert "source-units" in layer_names
        assert "claims" in layer_names
        assert "embeddings" in layer_names

    def test_all_blobs_exist(self, built_archive, tmp_archive):
        """Every layer digest corresponds to an existing blob."""
        cas = ContentAddressedStore(tmp_archive)
        for layer in built_archive.manifest.layers:
            assert cas.has_blob(layer.digest), f"Missing blob for layer {layer.name}"

    def test_manifest_on_disk(self, built_archive, tmp_archive):
        """manifest.json exists and is valid."""
        manifest_path = tmp_archive / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["archive_id"] == "arc://test-corpus"

    def test_provenance_recorded(self, built_archive, tmp_archive):
        """Provenance is recorded in the archive."""
        cas = ContentAddressedStore(tmp_archive)
        prov = cas.read_json("provenance.json")
        assert prov is not None
        assert "source_inventory" in prov
        assert len(prov["source_inventory"]) > 0

    def test_claims_have_evidence(self, built_archive):
        """Every claim has at least one evidence pointer."""
        for claim in built_archive.claims:
            assert len(claim.evidence) > 0, f"Claim without evidence: {claim.text[:50]}"

    def test_evidence_references_valid_units(self, built_archive):
        """All evidence pointers reference existing source units."""
        su_ids = {tu.id for tu in built_archive.text_units}
        for claim in built_archive.claims:
            for ev in claim.evidence:
                assert ev.source_unit_id in su_ids, (
                    f"Claim '{claim.id}' references unknown unit '{ev.source_unit_id}'"
                )

    def test_decisions_extracted(self, built_archive):
        """ADR documents produce Decision objects."""
        assert len(built_archive.decisions) >= 2, (
            f"Expected ≥2 decisions from ADRs, got {len(built_archive.decisions)}"
        )

    def test_deduplication_applied(self, built_archive):
        """Deduplication runs during build."""
        assert built_archive.deduplication is not None
        assert built_archive.deduplication.original_count >= len(built_archive.claims)

    def test_all_claims_preserved(self, corpus_dir, tmp_path):
        """Builder preserves all unique non-contested claims (no lossy compression)."""
        from arc.extractor import extract_claims
        from arc.compressor import deduplicate_claims

        out = tmp_path / "fidelity_test.arc"
        result = build_archive(corpus_dir, out)
        assert result.valid

        # The archive should contain exactly the deduplicated set
        assert result.deduplication is not None
        assert len(result.claims) == (
            result.deduplication.original_count - result.deduplication.duplicates_removed
        )

    def test_archive_directory_structure(self, built_archive, tmp_archive):
        """Archive has correct directory layout."""
        assert (tmp_archive / "manifest.json").exists()
        assert (tmp_archive / "blobs" / "sha256").is_dir()
        assert (tmp_archive / "refs").is_dir()
        assert (tmp_archive / "meta").is_dir()


class TestCLI:
    def test_build_command(self, corpus_dir, tmp_path):
        """CLI build command produces a single-file archive."""
        from arc.cli import main
        out = tmp_path / "cli_test.arc"
        ret = main(["build", str(corpus_dir), "--out", str(out)])
        assert ret == 0
        assert out.is_file()  # SQLite single file

    def test_inspect_command(self, built_archive, tmp_archive):
        """CLI inspect command works."""
        from arc.cli import main
        ret = main(["inspect", str(tmp_archive)])
        assert ret == 0

    def test_verify_command(self, built_archive, tmp_archive):
        """CLI verify command works on valid archive."""
        from arc.cli import main
        ret = main(["verify", str(tmp_archive)])
        assert ret == 0

    def test_load_command(self, built_archive, tmp_archive):
        """CLI load command works."""
        from arc.cli import main
        ret = main(["load", str(tmp_archive)])
        assert ret == 0

    def test_load_with_task(self, built_archive, tmp_archive):
        """CLI load with task filter works."""
        from arc.cli import main
        ret = main(["load", str(tmp_archive), "--task", "security threats"])
        assert ret == 0

    def test_load_raw_mode(self, built_archive, tmp_archive):
        from arc.cli import main
        ret = main(["load", str(tmp_archive), "--task", "architecture", "--raw"])
        assert ret == 0

    def test_load_code_filter(self, built_archive, tmp_archive):
        from arc.cli import main
        ret = main(["load", str(tmp_archive), "--task", "architecture", "--raw", "--code"])
        assert ret == 0

    def test_load_ext_filter(self, built_archive, tmp_archive):
        from arc.cli import main
        ret = main(["load", str(tmp_archive), "--task", "architecture", "--raw", "--ext", ".py"])
        assert ret == 0

    def test_diff_command(self, corpus_dir, tmp_path):
        from arc.cli import main
        a = tmp_path / "a.arc"
        b = tmp_path / "b.arc"
        build_archive(corpus_dir, a, archive_version="1.0.0")
        build_archive(corpus_dir, b, archive_version="2.0.0")
        ret = main(["diff", str(a), str(b)])
        assert ret == 0

    def test_diff_json(self, corpus_dir, tmp_path):
        from arc.cli import main
        a = tmp_path / "a.arc"
        b = tmp_path / "b.arc"
        build_archive(corpus_dir, a, archive_version="1.0.0")
        build_archive(corpus_dir, b, archive_version="2.0.0")
        ret = main(["diff", str(a), str(b), "--json"])
        assert ret == 0

    def test_restore_command(self, built_archive, tmp_archive, tmp_path):
        from arc.cli import main
        out = tmp_path / "restored"
        ret = main(["restore", str(tmp_archive), "--out", str(out)])
        assert ret == 0
        assert out.exists()

    def test_inspect_json(self, built_archive, tmp_archive):
        from arc.cli import main
        ret = main(["inspect", str(tmp_archive), "--json"])
        assert ret == 0

    def test_verify_json(self, built_archive, tmp_archive):
        from arc.cli import main
        ret = main(["verify", str(tmp_archive), "--json"])
        assert ret == 0

    def test_no_command_returns_1(self):
        from arc.cli import main
        ret = main([])
        assert ret == 1

    def test_verify_tampered(self, built_archive, tmp_archive):
        """Verify detects tampered archive."""
        from arc.cli import main
        # Corrupt a blob
        blobs = list((tmp_archive / "blobs" / "sha256").iterdir())
        if blobs:
            blobs[0].write_text("corrupted")
        ret = main(["verify", str(tmp_archive)])
        assert ret == 1

    def test_build_with_progress(self, corpus_dir, tmp_path):
        from arc.cli import main
        out = tmp_path / "progress.arc"
        ret = main(["build", str(corpus_dir), "--out", str(out)])
        assert ret == 0
