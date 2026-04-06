"""End-to-end protocol tests — the full agent workflow using the public API.

No blob hacking. Everything goes through create_archive, load, snapshot, merge.
These are the tests that prove the protocol actually works.
"""

import pytest

from arc.create import create_archive
from arc.loader import load
from arc.merge import merge
from arc.models import Claim, Decision, EvidencePointer, Resource, TextUnit
from arc.snapshot import snapshot


class TestAgentProducesArchive:
    """An agent should be able to create a valid, loadable archive from claims alone."""

    def test_agent_creates_archive_from_scratch(self, tmp_path):
        out = tmp_path / "agent-output.arc"
        claims = [
            Claim(text="auth module uses bcrypt", claim_type="observation",
                  source="review-agent", confidence=0.95),
            Claim(text="should add rate limiting to login endpoint",
                  claim_type="decision", source="review-agent", confidence=0.8),
            Claim(text="unclear if password reset uses same hash",
                  claim_type="uncertainty", source="review-agent", confidence=0.1),
            Claim(text="rate limiting requires Redis dependency",
                  claim_type="dependency", source="review-agent", confidence=0.9),
        ]
        create_archive(str(out), claims, archive_id="arc://review")

        loaded = load(str(out))
        assert not loaded.rejected
        assert len(loaded.claims) == 4

        # Filter works
        decs = load(str(out), claim_type="decision").claims
        assert len(decs) == 1
        assert "rate limiting" in decs[0].text

        obs = load(str(out), claim_type="observation").claims
        assert len(obs) == 1


class TestAgentWithEvidence:
    """An agent can attach source evidence to claims for traceability."""

    def test_claims_with_evidence_traceable(self, tmp_path):
        res = Resource(id="r1", locator="auth/views.py")
        tu = TextUnit(resource_id="r1", content="def login(request):\n    pass",
                      kind="function", span=(1, 2))
        claims = [
            Claim(text="login function has no validation",
                  claim_type="observation", source="agent",
                  evidence=[EvidencePointer(source_unit_id=tu.id, span=(1, 2))]),
        ]
        out = tmp_path / "evidence.arc"
        create_archive(str(out), claims, resources=[res], source_units=[tu])

        loaded = load(str(out))
        c = loaded.claims[0]
        assert c.evidence[0].source_unit_id == tu.id

        # Trace from claim → source unit → resource
        su = next(s for s in loaded.source_units if s.id == tu.id)
        r = next(r for r in loaded.resources if r.id == su.resource_id)
        assert r.locator == "auth/views.py"


class TestSequentialHandoffE2E:
    """Agent A → archive → Agent B → archive, using the real API."""

    def test_full_handoff_chain(self, tmp_path):
        # Agent A produces review
        a_claims = [
            Claim(id="a1", text="the scoring pipeline is not batched",
                  claim_type="observation", source="agent-a",
                  timestamp="2026-04-06T10:00:00Z"),
            Claim(id="a2", text="should batch embedding calls for performance",
                  claim_type="decision", source="agent-a",
                  timestamp="2026-04-06T10:01:00Z"),
            Claim(id="a3", text="unclear if numpy vectorization would help more",
                  claim_type="uncertainty", source="agent-a",
                  timestamp="2026-04-06T10:02:00Z"),
        ]
        a_arc = tmp_path / "agent-a.arc"
        create_archive(str(a_arc), a_claims, archive_id="arc://review")

        # Agent B loads A's review
        review = load(str(a_arc))
        assert len(review.claims) == 3

        # B reads decisions only
        decisions_from_a = load(str(a_arc), claim_type="decision")
        assert len(decisions_from_a.claims) == 1
        assert decisions_from_a.claims[0].id == "a2"

        # B produces fix plan referencing A's decision
        b_claims = [
            Claim(id="b1", text="refactored embed() to accept batches",
                  claim_type="observation", source="agent-b",
                  timestamp="2026-04-06T11:00:00Z"),
            Claim(id="b2", text="batch size of 32 optimal for TF-IDF",
                  claim_type="decision", source="agent-b",
                  timestamp="2026-04-06T11:01:00Z",
                  references=["a2"]),
            Claim(id="b3", text="need to update VectorStore.add() signature",
                  claim_type="dependency", source="agent-b",
                  timestamp="2026-04-06T11:02:00Z",
                  references=["b1"]),
        ]
        b_arc = tmp_path / "agent-b.arc"
        create_archive(str(b_arc), b_claims, archive_id="arc://fixes")

        # Verify: trace B's decision back to A
        fixes = load(str(b_arc))
        b_dec = next(c for c in fixes.claims if c.id == "b2")
        assert "a2" in b_dec.references

        # Load A's archive to verify the reference target exists
        a_claim = next((c for c in review.claims if c.id == "a2"), None)
        assert a_claim is not None
        assert a_claim.source == "agent-a"


class TestParallelMergeE2E:
    """Two agents work independently, merge, verify conflicts."""

    def test_merge_detects_real_conflicts(self, tmp_path):
        # Agent C: security review
        c_arc = tmp_path / "security.arc"
        create_archive(str(c_arc), [
            Claim(text="all API endpoints lack authentication",
                  claim_type="observation", source="security-agent"),
            Claim(text="should implement OAuth2 token-based authentication for all endpoints",
                  claim_type="decision", source="security-agent"),
        ], archive_id="arc://security")

        # Agent D: simplicity review
        d_arc = tmp_path / "simple.arc"
        create_archive(str(d_arc), [
            Claim(text="codebase has too many abstractions",
                  claim_type="observation", source="simplicity-agent"),
            Claim(text="should implement simple API key authentication for all endpoints",
                  claim_type="decision", source="simplicity-agent"),
        ], archive_id="arc://simplicity")

        # Merge
        merged_arc = tmp_path / "combined.arc"
        result, _ = merge(str(c_arc), str(d_arc), str(merged_arc))

        # Both observations coexist
        loaded = load(str(merged_arc))
        obs = [c for c in loaded.claims if c.claim_type == "observation"]
        assert len(obs) == 2

        # The two auth decisions should conflict (semantically similar)
        assert result.conflicts_detected >= 1
        conflicts = [c for c in loaded.claims if c.claim_type == "conflict"]
        assert len(conflicts) >= 1
        # Conflict references both original decisions
        assert len(conflicts[0].references) == 2

    def test_merge_no_false_positives(self, tmp_path):
        # Two agents with completely different topics
        a_arc = tmp_path / "a.arc"
        create_archive(str(a_arc), [
            Claim(text="should add comprehensive logging to the build pipeline",
                  claim_type="decision", source="agent-a"),
        ])

        b_arc = tmp_path / "b.arc"
        create_archive(str(b_arc), [
            Claim(text="should increase unit test coverage for the security module",
                  claim_type="decision", source="agent-b"),
        ])

        out = tmp_path / "merged.arc"
        result, _ = merge(str(a_arc), str(b_arc), str(out))
        assert result.conflicts_detected == 0

    def test_merged_archive_queryable_by_source(self, tmp_path):
        a_arc = tmp_path / "a.arc"
        create_archive(str(a_arc), [
            Claim(text="obs from a", claim_type="observation", source="agent-a"),
            Claim(text="dec from a", claim_type="decision", source="agent-a"),
        ])
        b_arc = tmp_path / "b.arc"
        create_archive(str(b_arc), [
            Claim(text="obs from b", claim_type="observation", source="agent-b"),
        ])

        out = tmp_path / "merged.arc"
        merge(str(a_arc), str(b_arc), str(out))

        assert len(load(str(out), source="agent-a").claims) == 2
        assert len(load(str(out), source="agent-b").claims) == 1
        assert len(load(str(out), claim_type="decision").claims) == 1


class TestSnapshotE2E:
    """Snapshot → load → verify subset relationship."""

    def test_snapshot_is_strict_subset(self, tmp_path):
        full_arc = tmp_path / "full.arc"
        claims = [
            Claim(id=f"c{i}", text=f"observation number {i}",
                  claim_type="observation", source="agent",
                  timestamp=f"2026-04-06T{10+i:02d}:00:00Z")
            for i in range(15)
        ]
        create_archive(str(full_arc), claims)

        snap_arc = tmp_path / "snap.arc"
        snapshot(str(full_arc), str(snap_arc), last=5)

        snap = load(str(snap_arc))
        full = load(str(full_arc))

        snap_ids = {c.id for c in snap.claims}
        full_ids = {c.id for c in full.claims}
        assert snap_ids.issubset(full_ids)
        assert len(snap.claims) == 5

        # Should be the 5 with latest timestamps (c10-c14)
        snap_texts = {c.text for c in snap.claims}
        for i in range(10, 15):
            assert f"observation number {i}" in snap_texts

    def test_snapshot_then_merge(self, tmp_path):
        """Snapshot from one agent, full from another, merge both."""
        full = tmp_path / "full.arc"
        claims = [
            Claim(text=f"obs {i}", claim_type="observation", source="agent-a",
                  timestamp=f"2026-04-06T{10+i:02d}:00:00Z")
            for i in range(10)
        ] + [
            Claim(text="should refactor auth", claim_type="decision", source="agent-a",
                  timestamp="2026-04-06T20:00:00Z"),
        ]
        create_archive(str(full), claims)

        snap = tmp_path / "snap.arc"
        snapshot(str(full), str(snap), last=3)

        other = tmp_path / "other.arc"
        create_archive(str(other), [
            Claim(text="app has no tests", claim_type="observation", source="agent-b"),
        ])

        merged = tmp_path / "merged.arc"
        result, _ = merge(str(snap), str(other), str(merged))

        loaded = load(str(merged))
        sources = {c.source for c in loaded.claims}
        assert "agent-a" in sources
        assert "agent-b" in sources


class TestDecisionSurfacing:
    """--type decision should include both Claim decisions and Decision objects."""

    def test_decision_type_includes_decision_model(self, tmp_path):
        out = tmp_path / "dec.arc"
        claims = [
            Claim(text="obs about auth", claim_type="observation", source="a"),
            Claim(text="should use JWT", claim_type="decision", source="a"),
        ]
        decisions = [
            Decision(title="Use SHA-256", decision="SHA-256 is the standard",
                     source="a", status="accepted"),
        ]
        create_archive(str(out), claims, decisions=decisions)

        loaded = load(str(out), claim_type="decision")
        # Should have: the claim-type decision + the Decision object surfaced
        assert len(loaded.claims) == 2
        texts = {c.text for c in loaded.claims}
        assert "should use JWT" in texts
        assert "Use SHA-256: SHA-256 is the standard" in texts
