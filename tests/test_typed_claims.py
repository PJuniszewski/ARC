"""Tests for typed claims — claim_type, source, timestamp, references, filtering."""

import pytest

from arc.models import CLAIM_TYPES, Claim, Decision, EvidencePointer


class TestClaimTypes:
    """Claim type field validation and round-trip."""

    def test_valid_claim_types(self):
        for ct in CLAIM_TYPES:
            c = Claim(text="test", claim_type=ct)
            assert c.claim_type == ct

    def test_invalid_claim_type(self):
        with pytest.raises(ValueError, match="Invalid claim type"):
            Claim(text="test", claim_type="invalid")

    def test_default_claim_type(self):
        c = Claim(text="test")
        assert c.claim_type == "observation"

    def test_round_trip_observation(self):
        c = Claim(
            id="c1",
            text="file auth/views.py uses session-based auth",
            kind="fact",
            claim_type="observation",
            source="agent-a",
            timestamp="2026-04-06T14:30:00Z",
            evidence=[EvidencePointer(source_unit_id="su-1", span=(15, 42))],
            confidence=0.95,
            status="observed",
        )
        d = c.to_dict()
        assert d["claim_type"] == "observation"
        assert d["source"] == "agent-a"
        assert d["timestamp"] == "2026-04-06T14:30:00Z"
        assert d["references"] == []

        restored = Claim.from_dict(d)
        assert restored.claim_type == "observation"
        assert restored.source == "agent-a"
        assert restored.timestamp == "2026-04-06T14:30:00Z"
        assert restored.references == []

    def test_round_trip_decision(self):
        c = Claim(
            text="we should migrate to JWT",
            claim_type="decision",
            source="agent-a",
            confidence=0.8,
        )
        d = c.to_dict()
        restored = Claim.from_dict(d)
        assert restored.claim_type == "decision"
        assert restored.source == "agent-a"

    def test_round_trip_uncertainty(self):
        c = Claim(
            text="unclear if rate limiting applies to /admin",
            claim_type="uncertainty",
            source="agent-b",
            confidence=0.0,
        )
        d = c.to_dict()
        restored = Claim.from_dict(d)
        assert restored.claim_type == "uncertainty"
        assert restored.confidence == 0.0

    def test_round_trip_dependency(self):
        c = Claim(
            text="requires updating middleware config",
            claim_type="dependency",
            source="agent-a",
            confidence=0.9,
        )
        d = c.to_dict()
        restored = Claim.from_dict(d)
        assert restored.claim_type == "dependency"

    def test_round_trip_conflict(self):
        c = Claim(
            text="conflicting decisions on auth: JWT vs OAuth2",
            claim_type="conflict",
            source="arc-merge",
            confidence=1.0,
            status="contested",
            references=["claim-1", "claim-2"],
        )
        d = c.to_dict()
        assert d["references"] == ["claim-1", "claim-2"]
        restored = Claim.from_dict(d)
        assert restored.claim_type == "conflict"
        assert restored.source == "arc-merge"
        assert restored.status == "contested"
        assert restored.references == ["claim-1", "claim-2"]

    def test_default_source_is_builder(self):
        c = Claim(text="auto-extracted")
        assert c.source == "builder"

    def test_default_timestamp_is_empty(self):
        c = Claim(text="test")
        assert c.timestamp == ""

    def test_references_default_empty(self):
        c = Claim(text="test")
        assert c.references == []

    def test_from_dict_ignores_unknown_fields(self):
        d = {
            "id": "c1",
            "text": "test",
            "kind": "fact",
            "claim_type": "observation",
            "source": "agent-x",
            "timestamp": "2026-01-01T00:00:00Z",
            "evidence": [],
            "confidence": 0.9,
            "status": "observed",
            "references": [],
            "unknown_future_field": "should be ignored",
        }
        c = Claim.from_dict(d)
        assert c.source == "agent-x"


class TestDecisionSourceTimestamp:
    """Decision model also carries source and timestamp."""

    def test_decision_source_default(self):
        d = Decision(title="test")
        assert d.source == "builder"
        assert d.timestamp == ""

    def test_decision_round_trip_with_source(self):
        d = Decision(
            title="Use JWT",
            source="agent-a",
            timestamp="2026-04-06T14:30:00Z",
        )
        serialized = d.to_dict()
        assert serialized["source"] == "agent-a"
        assert serialized["timestamp"] == "2026-04-06T14:30:00Z"
        restored = Decision.from_dict(serialized)
        assert restored.source == "agent-a"
        assert restored.timestamp == "2026-04-06T14:30:00Z"


class TestClaimFiltering:
    """Test filtering claims by type and source."""

    @pytest.fixture
    def mixed_claims(self):
        return [
            Claim(id="c1", text="file uses auth", claim_type="observation", source="agent-a"),
            Claim(id="c2", text="should use JWT", claim_type="decision", source="agent-a"),
            Claim(id="c3", text="unclear about rate limiting", claim_type="uncertainty", source="agent-b"),
            Claim(id="c4", text="needs middleware update", claim_type="dependency", source="agent-a"),
            Claim(id="c5", text="file uses RBAC", claim_type="observation", source="agent-b"),
            Claim(id="c6", text="conflict on auth", claim_type="conflict", source="arc-merge",
                  status="contested", references=["c2", "c99"]),
        ]

    def test_filter_by_type(self, mixed_claims):
        observations = [c for c in mixed_claims if c.claim_type == "observation"]
        assert len(observations) == 2
        assert all(c.claim_type == "observation" for c in observations)

    def test_filter_by_source(self, mixed_claims):
        from_a = [c for c in mixed_claims if c.source == "agent-a"]
        assert len(from_a) == 3

    def test_filter_by_type_and_source(self, mixed_claims):
        obs_from_b = [c for c in mixed_claims if c.claim_type == "observation" and c.source == "agent-b"]
        assert len(obs_from_b) == 1
        assert obs_from_b[0].text == "file uses RBAC"

    def test_filter_conflicts(self, mixed_claims):
        conflicts = [c for c in mixed_claims if c.claim_type == "conflict"]
        assert len(conflicts) == 1
        assert conflicts[0].references == ["c2", "c99"]


class TestLoaderFiltering:
    """Integration test: build → load with --type/--source filtering."""

    @pytest.fixture
    def archive_with_typed_claims(self, tmp_path):
        """Build an archive, then manually inject typed claims for testing."""
        import json
        from arc.builder import build_archive

        # Build from a simple source
        src = tmp_path / "src"
        src.mkdir()
        (src / "auth.py").write_text(
            "class AuthMiddleware:\n"
            "    \"\"\"Handles authentication.\"\"\"\n"
            "    def process(self, request):\n"
            "        # Session-based authentication is used here\n"
            "        return self.check_session(request)\n"
        )
        out = tmp_path / "test.arc"
        result = build_archive(str(src), str(out), force_tfidf=True)
        assert result.valid

        # Now replace the claims layer with typed claims
        from arc.cas import ContentAddressedStore, sha256_digest
        from arc.manifest import read_manifest_from_cas, write_manifest_to_cas

        cas = ContentAddressedStore(out)
        manifest = read_manifest_from_cas(cas)

        typed_claims = [
            Claim(id="c1", text="AuthMiddleware uses session-based auth",
                  claim_type="observation", source="agent-a",
                  timestamp="2026-04-06T14:30:00Z", confidence=0.95).to_dict(),
            Claim(id="c2", text="should migrate to JWT",
                  claim_type="decision", source="agent-a",
                  timestamp="2026-04-06T14:31:00Z", confidence=0.8).to_dict(),
            Claim(id="c3", text="unclear if rate limiting applies",
                  claim_type="uncertainty", source="agent-b",
                  timestamp="2026-04-06T14:32:00Z", confidence=0.0).to_dict(),
            Claim(id="c4", text="requires middleware config update",
                  claim_type="dependency", source="agent-a",
                  timestamp="2026-04-06T14:33:00Z", confidence=0.9).to_dict(),
        ]

        blob_data = json.dumps(typed_claims).encode()
        new_digest = cas.store_blob(blob_data)

        # Update claims layer digest in manifest
        for layer in manifest.layers:
            if layer.type == "semantic.claims":
                layer.digest = new_digest
                break

        manifest.root_digest = manifest.compute_root_digest()
        write_manifest_to_cas(manifest, cas)
        return str(out)

    def test_load_all(self, archive_with_typed_claims):
        from arc.loader import load
        loaded = load(archive_with_typed_claims)
        assert not loaded.rejected
        assert len(loaded.claims) == 4

    def test_load_filter_type(self, archive_with_typed_claims):
        from arc.loader import load
        loaded = load(archive_with_typed_claims, claim_type="observation")
        assert len(loaded.claims) == 1
        assert loaded.claims[0].claim_type == "observation"

    def test_load_filter_source(self, archive_with_typed_claims):
        from arc.loader import load
        loaded = load(archive_with_typed_claims, source="agent-a")
        assert len(loaded.claims) == 3

    def test_load_filter_type_and_source(self, archive_with_typed_claims):
        from arc.loader import load
        loaded = load(archive_with_typed_claims, claim_type="decision", source="agent-a")
        assert len(loaded.claims) == 1
        assert loaded.claims[0].text == "should migrate to JWT"

    def test_load_filter_no_match(self, archive_with_typed_claims):
        from arc.loader import load
        loaded = load(archive_with_typed_claims, claim_type="conflict")
        assert len(loaded.claims) == 0

    def test_load_filter_uncertainty(self, archive_with_typed_claims):
        from arc.loader import load
        loaded = load(archive_with_typed_claims, claim_type="uncertainty")
        assert len(loaded.claims) == 1
        assert loaded.claims[0].source == "agent-b"
