"""Tests for create_archive — programmatic archive creation from claims."""

import pytest

from arc.cas import open_cas
from arc.create import create_archive
from arc.loader import load
from arc.models import Claim, Decision, EvidencePointer, Resource, TextUnit


class TestCreateArchive:
    def test_create_from_claims(self, tmp_path):
        out = tmp_path / "agent.arc"
        claims = [
            Claim(text="app uses session auth", claim_type="observation",
                  source="my-agent", confidence=0.9),
            Claim(text="should migrate to JWT", claim_type="decision",
                  source="my-agent", confidence=0.8),
        ]
        manifest = create_archive(str(out), claims, archive_id="arc://test")
        assert manifest.archive_id == "arc://test"

        loaded = load(str(out))
        assert not loaded.rejected
        assert len(loaded.claims) == 2

    def test_create_verifies(self, tmp_path):
        out = tmp_path / "verified.arc"
        claims = [Claim(text="test claim", source="agent-x")]
        create_archive(str(out), claims)

        cas = open_cas(out)
        assert cas.verify_archive().valid

    def test_create_with_source_stamp(self, tmp_path):
        out = tmp_path / "stamped.arc"
        claims = [
            Claim(text="unstamped claim"),  # source defaults to "builder"
            Claim(text="already stamped", source="agent-y"),
        ]
        create_archive(str(out), claims, source="agent-x")

        loaded = load(str(out))
        sources = {c.source for c in loaded.claims}
        # "builder" default was overridden to "agent-x", "agent-y" kept
        assert "agent-x" in sources
        assert "agent-y" in sources
        assert "builder" not in sources

    def test_create_with_decisions(self, tmp_path):
        out = tmp_path / "with-dec.arc"
        claims = [Claim(text="obs", claim_type="observation", source="a")]
        decisions = [
            Decision(title="Use JWT", decision="JWT over sessions",
                     source="a", status="accepted"),
        ]
        create_archive(str(out), claims, decisions=decisions)

        loaded = load(str(out))
        assert len(loaded.decisions) == 1
        assert loaded.decisions[0].title == "Use JWT"

    def test_create_with_evidence(self, tmp_path):
        out = tmp_path / "evidence.arc"
        tu = TextUnit(resource_id="r1", content="session auth code here",
                      kind="function", span=(1, 10))
        res = Resource(id="r1", locator="auth.py")
        claims = [
            Claim(text="uses session auth", claim_type="observation",
                  source="agent", evidence=[EvidencePointer(source_unit_id=tu.id)]),
        ]
        create_archive(str(out), claims, resources=[res], source_units=[tu])

        loaded = load(str(out))
        assert len(loaded.source_units) == 1
        assert len(loaded.resources) == 1
        assert loaded.claims[0].evidence[0].source_unit_id == tu.id

    def test_create_loadable_with_filters(self, tmp_path):
        out = tmp_path / "filterable.arc"
        claims = [
            Claim(text="obs 1", claim_type="observation", source="agent-a"),
            Claim(text="dec 1", claim_type="decision", source="agent-a"),
            Claim(text="obs 2", claim_type="observation", source="agent-b"),
        ]
        create_archive(str(out), claims)

        loaded = load(str(out), claim_type="observation")
        assert len(loaded.claims) == 2

        loaded = load(str(out), source="agent-a")
        assert len(loaded.claims) == 2

    def test_create_then_merge(self, tmp_path):
        """Two agents create archives independently, then merge."""
        from arc.merge import merge

        arc_a = tmp_path / "a.arc"
        create_archive(str(arc_a), [
            Claim(text="app has no auth", claim_type="observation", source="agent-a"),
            Claim(text="should add auth middleware", claim_type="decision", source="agent-a"),
        ], archive_id="arc://review-a")

        arc_b = tmp_path / "b.arc"
        create_archive(str(arc_b), [
            Claim(text="app has no logging", claim_type="observation", source="agent-b"),
            Claim(text="should add structured logging", claim_type="decision", source="agent-b"),
        ], archive_id="arc://review-b")

        merged = tmp_path / "merged.arc"
        result, manifest = merge(str(arc_a), str(arc_b), str(merged))

        assert result.merged_claims == 4
        assert result.conflicts_detected == 0  # different topics

        loaded = load(str(merged))
        assert len(loaded.claims) == 4

    def test_create_does_not_mutate_input(self, tmp_path):
        """create_archive should not modify the caller's Claim objects."""
        out = tmp_path / "nomut.arc"
        claims = [Claim(text="test claim")]  # source defaults to "builder"
        create_archive(str(out), claims, source="agent-x")
        assert claims[0].source == "builder"  # original untouched

    def test_create_then_snapshot(self, tmp_path):
        from arc.snapshot import snapshot

        full = tmp_path / "full.arc"
        claims = [
            Claim(text=f"observation {i}", claim_type="observation", source="agent")
            for i in range(20)
        ]
        create_archive(str(full), claims)

        snap = tmp_path / "snap.arc"
        manifest = snapshot(str(full), str(snap), last=5)

        loaded = load(str(snap))
        assert len(loaded.claims) == 5
