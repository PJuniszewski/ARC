"""Dogfood tests — real agent handoff scenarios on the ARC repo.

Scenario 1 (sequential):
  Agent A reviews retrieval pipeline → review.arc
  Agent B receives review.arc, proposes fixes → fixes.arc
  Verify: B references A's decisions, trace back to source code.

Scenario 2 (parallel):
  Agent C reviews security → security.arc
  Agent D reviews performance → performance.arc
  Merge → combined.arc
  Verify: conflicts flagged, third agent can load combined.arc.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from arc.builder import build_archive
from arc.cas import ContentAddressedStore, open_cas
from arc.diff import diff_archives
from arc.loader import load
from arc.manifest import read_manifest_from_cas, write_manifest_to_cas
from arc.merge import merge
from arc.models import Claim, Decision, EvidencePointer, Layer
from arc.snapshot import snapshot


@pytest.fixture
def arc_repo_archive(tmp_path):
    """Build an archive from a mini ARC-like repo structure."""
    src = tmp_path / "repo"
    src.mkdir()

    # Simulate key ARC source files
    (src / "loader.py").write_text(
        "def load(archive_path, task=None):\n"
        "    '''Load archive with optional task filtering.'''\n"
        "    manifest = read_manifest(archive_path)\n"
        "    claims = deserialize_claims(manifest)\n"
        "    if task:\n"
        "        claims = filter_by_task(claims, task)\n"
        "    return claims\n"
        "\n"
        "def filter_by_task(claims, task):\n"
        "    '''Hybrid vector + keyword scoring.'''\n"
        "    scored = [(hybrid_score(c, task), c) for c in claims]\n"
        "    return [c for s, c in sorted(scored, reverse=True)[:12]]\n"
    )
    (src / "builder.py").write_text(
        "def build_archive(source_dir, output_dir):\n"
        "    '''8-stage pipeline: ingest, chunk, extract, dedup, index, assemble.'''\n"
        "    resources = ingest(source_dir)\n"
        "    chunks = chunk(resources)\n"
        "    claims = extract_claims(chunks)\n"
        "    claims = deduplicate(claims)\n"
        "    embeddings = build_embeddings(claims)\n"
        "    return assemble(claims, embeddings, output_dir)\n"
    )
    (src / "cas.py").write_text(
        "import hashlib\n"
        "class ContentAddressedStore:\n"
        "    '''SHA-256 blob storage with Merkle verification.'''\n"
        "    def store_blob(self, data):\n"
        "        digest = hashlib.sha256(data).hexdigest()\n"
        "        self.write(digest, data)\n"
        "        return digest\n"
        "    def verify_archive(self):\n"
        "        '''Re-hash all blobs and check against manifest.'''\n"
        "        return all(self.verify_blob(d) for d in self.list_blobs())\n"
    )
    (src / "config.py").write_text(
        "# Retrieval tuning constants\n"
        "MIN_SCORE = 0.15\n"
        "MAX_FILTERED_CLAIMS = 12\n"
        "TOP_K_BASE = 8\n"
        "KEYWORD_BOOST_WEIGHT = 0.3\n"
        "HEADING_BOOST_WEIGHT = 0.2\n"
    )

    out = tmp_path / "base.arc"
    result = build_archive(str(src), str(out), force_tfidf=True)
    assert result.valid
    return src, str(out)


def _make_agent_archive(base_archive, tmp_path, name, claims_list):
    """Create an agent's output archive by injecting typed claims into a base archive."""
    import shutil

    agent_arc = tmp_path / f"{name}.arc"
    shutil.copytree(base_archive, str(agent_arc))

    cas = ContentAddressedStore(agent_arc)
    manifest = read_manifest_from_cas(cas)

    # Get real source unit IDs for evidence pointers
    su_ids = []
    for layer in manifest.layers:
        if layer.type == "semantic.source_units":
            su_data = json.loads(cas.retrieve_blob(layer.digest))
            su_ids = [su["id"] for su in su_data]
            break

    # Attach evidence to first available source unit if not specified
    for c in claims_list:
        if not c.get("evidence") and su_ids:
            c["evidence"] = [EvidencePointer(source_unit_id=su_ids[0]).to_dict()]

    blob_data = json.dumps(claims_list).encode()
    new_digest = cas.store_blob(blob_data)
    for layer in manifest.layers:
        if layer.type == "semantic.claims":
            layer.digest = new_digest
            break
    manifest.root_digest = manifest.compute_root_digest()
    write_manifest_to_cas(manifest, cas)
    return str(agent_arc)


class TestSequentialHandoff:
    """Scenario 1: Agent A → review.arc → Agent B → fixes.arc"""

    def test_sequential_handoff(self, arc_repo_archive, tmp_path):
        src, base_arc = arc_repo_archive

        # --- Agent A: Review retrieval pipeline ---
        agent_a_claims = [
            Claim(id="a-obs-1",
                  text="filter_by_task uses hard-coded limit of 12 claims",
                  claim_type="observation", source="agent-review",
                  timestamp="2026-04-06T10:00:00Z", confidence=0.95,
                  evidence=[]).to_dict(),
            Claim(id="a-obs-2",
                  text="hybrid_score function is called per-claim with no batching",
                  claim_type="observation", source="agent-review",
                  timestamp="2026-04-06T10:01:00Z", confidence=0.9,
                  evidence=[]).to_dict(),
            Claim(id="a-dec-1",
                  text="should make MAX_FILTERED_CLAIMS configurable at load time",
                  claim_type="decision", source="agent-review",
                  timestamp="2026-04-06T10:02:00Z", confidence=0.85,
                  evidence=[]).to_dict(),
            Claim(id="a-unc-1",
                  text="unclear if batch embedding would improve latency on large archives",
                  claim_type="uncertainty", source="agent-review",
                  timestamp="2026-04-06T10:03:00Z", confidence=0.1,
                  evidence=[]).to_dict(),
            Claim(id="a-dep-1",
                  text="changing MAX_FILTERED_CLAIMS requires updating config.py defaults",
                  claim_type="dependency", source="agent-review",
                  timestamp="2026-04-06T10:04:00Z", confidence=0.9,
                  evidence=[]).to_dict(),
        ]
        review_arc = _make_agent_archive(base_arc, tmp_path, "review", agent_a_claims)

        # --- Agent B: Load review, propose fixes ---
        review_loaded = load(review_arc)
        assert not review_loaded.rejected

        # B should see A's decisions
        a_decisions = [c for c in review_loaded.claims if c.claim_type == "decision"]
        assert len(a_decisions) == 1
        assert "MAX_FILTERED_CLAIMS" in a_decisions[0].text

        # B produces fixes referencing A's decisions
        agent_b_claims = [
            Claim(id="b-obs-1",
                  text="config.py defines MAX_FILTERED_CLAIMS = 12 at module level",
                  claim_type="observation", source="agent-fix",
                  timestamp="2026-04-06T11:00:00Z", confidence=0.99,
                  evidence=[]).to_dict(),
            Claim(id="b-dec-1",
                  text="add max_claims parameter to load() with default from config",
                  claim_type="decision", source="agent-fix",
                  timestamp="2026-04-06T11:01:00Z", confidence=0.9,
                  references=["a-dec-1"]).to_dict(),
            Claim(id="b-dep-1",
                  text="updating load() signature requires updating CLI argument parser",
                  claim_type="dependency", source="agent-fix",
                  timestamp="2026-04-06T11:02:00Z", confidence=0.85,
                  references=["a-dep-1"]).to_dict(),
        ]
        fixes_arc = _make_agent_archive(base_arc, tmp_path, "fixes", agent_b_claims)

        # --- Verification ---

        # 1. Agent B correctly references Agent A's decisions
        fixes_loaded = load(fixes_arc)
        b_decisions = [c for c in fixes_loaded.claims if c.claim_type == "decision"]
        assert len(b_decisions) == 1
        assert "a-dec-1" in b_decisions[0].references

        # 2. Trace B's proposal back through A to source
        b_dec = b_decisions[0]
        assert b_dec.source == "agent-fix"
        # B references A's decision ID
        a_ref = b_dec.references[0]
        # Verify A's decision exists in review.arc
        a_claim = next((c for c in review_loaded.claims if c.id == a_ref), None)
        assert a_claim is not None
        assert a_claim.source == "agent-review"
        assert a_claim.claim_type == "decision"

        # 3. Diff between review and fixes makes sense
        diff_result = diff_archives(review_arc, fixes_arc)
        assert diff_result is not None

    def test_snapshot_handoff(self, arc_repo_archive, tmp_path):
        """Test that snapshot works as a lightweight handoff mechanism."""
        src, base_arc = arc_repo_archive

        # Agent A produces full review
        agent_a_claims = [
            Claim(id=f"a-{i}", text=f"observation {i} about the codebase",
                  claim_type="observation", source="agent-review",
                  evidence=[]).to_dict()
            for i in range(20)
        ] + [
            Claim(id="a-key-dec",
                  text="the critical decision: refactor the scoring pipeline",
                  claim_type="decision", source="agent-review",
                  evidence=[]).to_dict(),
        ]
        review_arc = _make_agent_archive(base_arc, tmp_path, "review-full", agent_a_claims)

        # Snapshot just the last 5 for quick handoff
        snap_path = tmp_path / "handoff.arc"
        snapshot(review_arc, str(snap_path), last=5)

        snap_loaded = load(str(snap_path))
        assert len(snap_loaded.claims) == 5

        # The critical decision should be in the snapshot (it's the last claim)
        dec = [c for c in snap_loaded.claims if c.claim_type == "decision"]
        assert len(dec) == 1
        assert "refactor" in dec[0].text

        # Snapshot claims exist in the full archive
        snap_ids = {c.id for c in snap_loaded.claims}
        full_loaded = load(review_arc)
        full_ids = {c.id for c in full_loaded.claims}
        assert snap_ids.issubset(full_ids)


class TestParallelMerge:
    """Scenario 2: Agent C (security) + Agent D (perf) → merge → combined.arc"""

    def test_parallel_merge(self, arc_repo_archive, tmp_path):
        src, base_arc = arc_repo_archive

        # --- Agent C: Security review ---
        security_claims = [
            Claim(id="c-obs-1",
                  text="CAS verify_archive re-hashes all blobs — no shortcut for attacker",
                  claim_type="observation", source="agent-security",
                  timestamp="2026-04-06T10:00:00Z", confidence=0.95,
                  evidence=[]).to_dict(),
            Claim(id="c-obs-2",
                  text="no input sanitization on archive_path parameter",
                  claim_type="observation", source="agent-security",
                  timestamp="2026-04-06T10:01:00Z", confidence=0.9,
                  evidence=[]).to_dict(),
            Claim(id="c-dec-1",
                  text="should add input validation and path sanitization to load() function",
                  claim_type="decision", source="agent-security",
                  timestamp="2026-04-06T10:02:00Z", confidence=0.85,
                  evidence=[]).to_dict(),
        ]
        security_arc = _make_agent_archive(base_arc, tmp_path, "security", security_claims)

        # --- Agent D: Performance review ---
        perf_claims = [
            Claim(id="d-obs-1",
                  text="build_embeddings runs on all claims sequentially",
                  claim_type="observation", source="agent-perf",
                  timestamp="2026-04-06T10:00:00Z", confidence=0.9,
                  evidence=[]).to_dict(),
            Claim(id="d-obs-2",
                  text="filter_by_task recomputes embeddings on every call",
                  claim_type="observation", source="agent-perf",
                  timestamp="2026-04-06T10:01:00Z", confidence=0.85,
                  evidence=[]).to_dict(),
            Claim(id="d-dec-1",
                  text="should add input validation and caching to load() function",
                  claim_type="decision", source="agent-perf",
                  timestamp="2026-04-06T10:02:00Z", confidence=0.75,
                  evidence=[]).to_dict(),
        ]
        perf_arc = _make_agent_archive(base_arc, tmp_path, "performance", perf_claims)

        # --- Merge ---
        combined_path = tmp_path / "combined.arc"
        result, manifest = merge(security_arc, perf_arc, str(combined_path))

        # --- Verify ---

        # 1. Combined archive is valid
        cas = open_cas(combined_path)
        assert cas.verify_archive().valid

        # 2. All observations from both agents are present
        loaded = load(str(combined_path))
        assert not loaded.rejected
        observations = [c for c in loaded.claims if c.claim_type == "observation"]
        assert len(observations) == 4  # 2 from C + 2 from D

        # 3. Both sources are represented
        sources = {c.source for c in loaded.claims if c.claim_type != "conflict"}
        assert "agent-security" in sources
        assert "agent-perf" in sources

        # 4. Conflicting decisions are flagged
        # Both agents say "should add ... to load()" — similar enough to conflict
        conflicts = [c for c in loaded.claims if c.claim_type == "conflict"]
        assert len(conflicts) >= 1
        assert conflicts[0].source == "arc-merge"
        assert len(conflicts[0].references) == 2

        # 5. A third agent can load and understand both reviews
        security_only = load(str(combined_path), source="agent-security")
        assert len(security_only.claims) == 3
        perf_only = load(str(combined_path), source="agent-perf")
        assert len(perf_only.claims) == 3

    def test_no_false_conflicts(self, arc_repo_archive, tmp_path):
        """Decisions about completely different topics should not conflict."""
        src, base_arc = arc_repo_archive

        claims_a = [
            Claim(id="x1", text="should add logging to the build pipeline",
                  claim_type="decision", source="agent-x", evidence=[]).to_dict(),
        ]
        claims_b = [
            Claim(id="y1", text="should increase test coverage for security module",
                  claim_type="decision", source="agent-y", evidence=[]).to_dict(),
        ]
        arc_a = _make_agent_archive(base_arc, tmp_path, "x", claims_a)
        arc_b = _make_agent_archive(base_arc, tmp_path, "y", claims_b)

        combined = tmp_path / "no-conflict.arc"
        result, _ = merge(arc_a, arc_b, str(combined))

        assert result.conflicts_detected == 0

    def test_diff_on_merged(self, arc_repo_archive, tmp_path):
        """arc diff should work on merged archives."""
        src, base_arc = arc_repo_archive

        claims_a = [
            Claim(id="x1", text="obs A", claim_type="observation",
                  source="agent-a", evidence=[]).to_dict(),
        ]
        claims_b = [
            Claim(id="y1", text="obs B", claim_type="observation",
                  source="agent-b", evidence=[]).to_dict(),
        ]
        arc_a = _make_agent_archive(base_arc, tmp_path, "diff-a", claims_a)
        arc_b = _make_agent_archive(base_arc, tmp_path, "diff-b", claims_b)

        combined = tmp_path / "for-diff.arc"
        merge(arc_a, arc_b, str(combined))

        # Diff combined vs original A
        diff = diff_archives(arc_a, str(combined))
        assert diff is not None
        # Merged has more claims than A alone
        assert len(diff.new_claims) >= 1
