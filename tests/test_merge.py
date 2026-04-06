"""Tests for arc merge — two-way archive merging."""

import json

import pytest

from arc.builder import build_archive
from arc.cas import ContentAddressedStore
from arc.loader import load
from arc.manifest import read_manifest_from_cas, write_manifest_to_cas
from arc.merge import merge
from arc.models import Claim, EvidencePointer


def _inject_claims(archive_path, claims_dicts):
    """Replace claims layer in an archive with custom claims."""
    cas = ContentAddressedStore(archive_path)
    manifest = read_manifest_from_cas(cas)
    blob_data = json.dumps(claims_dicts).encode()
    new_digest = cas.store_blob(blob_data)
    for layer in manifest.layers:
        if layer.type == "semantic.claims":
            layer.digest = new_digest
            break
    manifest.root_digest = manifest.compute_root_digest()
    write_manifest_to_cas(manifest, cas)


@pytest.fixture
def two_archives(tmp_path):
    """Create two archives with different typed claims from different agents."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    pass\n")

    # Build archive A
    arc_a = tmp_path / "a.arc"
    result_a = build_archive(str(src), str(arc_a), force_tfidf=True)
    assert result_a.valid

    # Get a source unit ID
    cas = ContentAddressedStore(arc_a)
    manifest = read_manifest_from_cas(cas)
    su_id = "su-fake"
    for layer in manifest.layers:
        if layer.type == "semantic.source_units":
            su_data = json.loads(cas.retrieve_blob(layer.digest))
            if su_data:
                su_id = su_data[0]["id"]
            break

    # Inject claims for A (security review)
    claims_a = [
        Claim(id="a1", text="app uses no authentication",
              claim_type="observation", source="agent-security",
              evidence=[EvidencePointer(source_unit_id=su_id)]).to_dict(),
        Claim(id="a2", text="should add JWT authentication",
              claim_type="decision", source="agent-security",
              confidence=0.8).to_dict(),
        Claim(id="a3", text="unclear if CORS is configured",
              claim_type="uncertainty", source="agent-security").to_dict(),
    ]
    _inject_claims(arc_a, claims_a)

    # Build archive B
    arc_b = tmp_path / "b.arc"
    result_b = build_archive(str(src), str(arc_b), force_tfidf=True)
    assert result_b.valid

    # Inject claims for B (performance review)
    claims_b = [
        Claim(id="b1", text="main() has no error handling",
              claim_type="observation", source="agent-perf",
              evidence=[EvidencePointer(source_unit_id=su_id)]).to_dict(),
        Claim(id="b2", text="should add OAuth2 authentication",
              claim_type="decision", source="agent-perf",
              confidence=0.7).to_dict(),
        Claim(id="b3", text="app uses no authentication",
              claim_type="observation", source="agent-perf",
              evidence=[EvidencePointer(source_unit_id=su_id)]).to_dict(),
    ]
    _inject_claims(arc_b, claims_b)

    return str(arc_a), str(arc_b)


class TestMerge:
    def test_merge_produces_valid_archive(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        result, manifest = merge(a, b, str(out))

        cas = ContentAddressedStore(out)
        verification = cas.verify_archive()
        assert verification.valid

    def test_merge_loadable(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        merge(a, b, str(out))

        loaded = load(str(out))
        assert not loaded.rejected
        assert len(loaded.claims) > 0

    def test_observations_coexist(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        merge(a, b, str(out))

        loaded = load(str(out))
        obs = [c for c in loaded.claims if c.claim_type == "observation"]
        # a1 and b3 have same text → deduped to 1. b1 is unique. Total: 2 observations.
        assert len(obs) == 2

    def test_duplicate_claims_deduped(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        result, _ = merge(a, b, str(out))

        # "app uses no authentication" appears in both → deduped
        assert result.duplicates_removed >= 1

    def test_conflicting_decisions_flagged(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        result, _ = merge(a, b, str(out))

        # "should add JWT authentication" vs "should add OAuth2 authentication"
        # Both are decisions from different sources about authentication
        assert result.conflicts_detected >= 1

        loaded = load(str(out))
        conflicts = [c for c in loaded.claims if c.claim_type == "conflict"]
        assert len(conflicts) >= 1
        assert conflicts[0].source == "arc-merge"
        assert conflicts[0].status == "contested"
        assert len(conflicts[0].references) == 2

    def test_merge_preserves_source_tracking(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        merge(a, b, str(out))

        loaded = load(str(out))
        sources = {c.source for c in loaded.claims if c.claim_type != "conflict"}
        assert "agent-security" in sources
        assert "agent-perf" in sources

    def test_merge_result_stats(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        result, _ = merge(a, b, str(out))

        assert result.claims_a == 3
        assert result.claims_b == 3
        # 3 from A + 2 unique from B + conflicts
        assert result.merged_claims >= 5

    def test_merge_has_embeddings(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        merge(a, b, str(out))

        loaded = load(str(out))
        assert loaded.vector_store is not None

    def test_filter_merged_by_type(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        merge(a, b, str(out))

        loaded = load(str(out), claim_type="uncertainty")
        assert len(loaded.claims) == 1
        assert loaded.claims[0].source == "agent-security"

    def test_filter_merged_by_source(self, two_archives, tmp_path):
        a, b = two_archives
        out = tmp_path / "merged.arc"
        merge(a, b, str(out))

        loaded = load(str(out), source="agent-security")
        assert all(c.source == "agent-security" for c in loaded.claims)


    def test_merge_remaps_references_on_dedup(self, tmp_path):
        """When a claim is deduped, references to its ID should be remapped."""
        from arc.create import create_archive

        arc_a = tmp_path / "remap-a.arc"
        create_archive(str(arc_a), [
            Claim(id="shared-obs", text="the app has no auth",
                  claim_type="observation", source="agent-a"),
        ])

        arc_b = tmp_path / "remap-b.arc"
        create_archive(str(arc_b), [
            Claim(id="b-obs", text="the app has no auth",
                  claim_type="observation", source="agent-b"),
            Claim(id="b-dec", text="should add auth", claim_type="decision",
                  source="agent-b", references=["b-obs"]),
        ])

        out = tmp_path / "remapped.arc"
        result, _ = merge(str(arc_a), str(arc_b), str(out))
        assert result.duplicates_removed == 1

        loaded = load(str(out))
        dec = next(c for c in loaded.claims if c.id == "b-dec")
        # "b-obs" was deduped into "shared-obs", so reference should be remapped
        assert dec.references == ["shared-obs"]


class TestMergeCLI:
    def test_cli_merge(self, two_archives, tmp_path):
        from arc.cli import main
        a, b = two_archives
        out = tmp_path / "cli-merged.arc"
        ret = main(["merge", a, b, "--out", str(out)])
        assert ret == 0
        assert out.exists()
