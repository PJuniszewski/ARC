"""Tests for arc snapshot — lightweight subset archives."""

import json

import pytest

from arc.builder import build_archive
from arc.cas import ContentAddressedStore, open_cas
from arc.loader import load
from arc.manifest import read_manifest_from_cas, write_manifest_to_cas
from arc.models import Claim, EvidencePointer, Layer
from arc.snapshot import snapshot


@pytest.fixture
def source_archive(tmp_path):
    """Build a source archive with typed claims for snapshot testing."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(
        "class AuthMiddleware:\n"
        "    def process(self, request):\n"
        "        return self.check_session(request)\n"
    )
    (src / "views.py").write_text(
        "def login(request):\n"
        "    '''Login view using session auth.'''\n"
        "    return authenticate(request)\n"
    )
    out = tmp_path / "full.arc"
    result = build_archive(str(src), str(out), force_tfidf=True)
    assert result.valid

    # Inject typed claims with multiple types and sources
    cas = ContentAddressedStore(out)
    manifest = read_manifest_from_cas(cas)

    # Get a real source_unit_id from the archive
    for layer in manifest.layers:
        if layer.type == "semantic.source_units":
            su_data = json.loads(cas.retrieve_blob(layer.digest))
            su_id = su_data[0]["id"] if su_data else "su-fake"
            break
    else:
        su_id = "su-fake"

    typed_claims = [
        Claim(id=f"c{i}", text=text, claim_type=ct, source=src_agent,
              evidence=[EvidencePointer(source_unit_id=su_id)],
              confidence=conf).to_dict()
        for i, (text, ct, src_agent, conf) in enumerate([
            ("AuthMiddleware uses session auth", "observation", "agent-a", 0.9),
            ("login view delegates to authenticate()", "observation", "agent-a", 0.85),
            ("should migrate to token-based auth", "decision", "agent-a", 0.8),
            ("unclear if CSRF is handled", "uncertainty", "agent-b", 0.1),
            ("migration requires DB schema change", "dependency", "agent-b", 0.9),
            ("RBAC is enforced via decorators", "observation", "agent-b", 0.95),
            ("should add rate limiting", "decision", "agent-b", 0.7),
            ("password hashing uses bcrypt", "observation", "agent-a", 0.99),
        ], 1)
    ]

    blob_data = json.dumps(typed_claims).encode()
    new_digest = cas.store_blob(blob_data)
    for layer in manifest.layers:
        if layer.type == "semantic.claims":
            layer.digest = new_digest
            break
    manifest.root_digest = manifest.compute_root_digest()
    write_manifest_to_cas(manifest, cas)

    return str(out)


class TestSnapshot:
    def test_snapshot_last_n(self, source_archive, tmp_path):
        snap_path = tmp_path / "snap.arc"
        manifest = snapshot(source_archive, str(snap_path), last=3)

        loaded = load(str(snap_path))
        assert not loaded.rejected
        assert len(loaded.claims) == 3
        # Last 3 claims from the list
        assert loaded.claims[0].text == "RBAC is enforced via decorators"

    def test_snapshot_is_loadable(self, source_archive, tmp_path):
        snap_path = tmp_path / "snap.arc"
        snapshot(source_archive, str(snap_path), last=5)

        loaded = load(str(snap_path))
        assert not loaded.rejected
        assert len(loaded.claims) == 5
        assert loaded.manifest.archive_id.endswith("/snapshot")

    def test_snapshot_has_parent_ref(self, source_archive, tmp_path):
        snap_path = tmp_path / "snap.arc"
        manifest = snapshot(source_archive, str(snap_path), last=3)
        assert manifest.parent_archive is not None

    def test_snapshot_verifies(self, source_archive, tmp_path):
        snap_path = tmp_path / "snap.arc"
        snapshot(source_archive, str(snap_path), last=3)

        cas = open_cas(snap_path)
        result = cas.verify_archive()
        assert result.valid

    def test_snapshot_filter_by_type(self, source_archive, tmp_path):
        snap_path = tmp_path / "snap.arc"
        snapshot(source_archive, str(snap_path), last=100, claim_type="decision")

        loaded = load(str(snap_path))
        assert len(loaded.claims) == 2
        assert all(c.claim_type == "decision" for c in loaded.claims)

    def test_snapshot_filter_by_source(self, source_archive, tmp_path):
        snap_path = tmp_path / "snap.arc"
        snapshot(source_archive, str(snap_path), last=100, source="agent-b")

        loaded = load(str(snap_path))
        assert len(loaded.claims) == 4
        assert all(c.source == "agent-b" for c in loaded.claims)

    def test_snapshot_includes_referenced_source_units(self, source_archive, tmp_path):
        snap_path = tmp_path / "snap.arc"
        snapshot(source_archive, str(snap_path), last=3)

        loaded = load(str(snap_path))
        # Should have source units referenced by the claims
        assert len(loaded.source_units) > 0

    def test_snapshot_has_embeddings(self, source_archive, tmp_path):
        snap_path = tmp_path / "snap.arc"
        snapshot(source_archive, str(snap_path), last=3)

        loaded = load(str(snap_path))
        assert loaded.vector_store is not None
        assert len(loaded.vector_store.ids) == 3

    def test_snapshot_claims_findable_in_full(self, source_archive, tmp_path):
        """Snapshot claims should be findable in the full archive by content hash."""
        snap_path = tmp_path / "snap.arc"
        snapshot(source_archive, str(snap_path), last=3)

        snap_loaded = load(str(snap_path))
        full_loaded = load(source_archive)

        snap_ids = {c.id for c in snap_loaded.claims}
        full_ids = {c.id for c in full_loaded.claims}
        assert snap_ids.issubset(full_ids)


class TestSnapshotCLI:
    def test_cli_snapshot(self, source_archive, tmp_path):
        from arc.cli import main
        snap_path = tmp_path / "cli-snap.arc"
        ret = main(["snapshot", source_archive, "--out", str(snap_path), "--last", "5"])
        assert ret == 0
        assert snap_path.exists()

    def test_cli_snapshot_with_type(self, source_archive, tmp_path):
        from arc.cli import main
        snap_path = tmp_path / "cli-snap.arc"
        ret = main(["snapshot", source_archive, "--out", str(snap_path), "--type", "observation"])
        assert ret == 0
        loaded = load(str(snap_path))
        assert all(c.claim_type == "observation" for c in loaded.claims)
