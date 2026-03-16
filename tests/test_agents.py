"""Full 3-agent test protocol: Claude Code, Aider, CrewAI.

Tests build → verify → inspect → restore → selective load → evidence traceability
for each agent, then generates results/ directory with summary.json.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from arc.builder import build_archive
from arc.cas import ContentAddressedStore
from arc.diff import diff_archives
from arc.loader import load, restore_sources, verify

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent
RESULTS_DIR = REPO_ROOT / "results"


@dataclass
class AgentTestConfig:
    name: str
    source_dir: str | Path
    archive_id: str
    expected_claim_keywords: list[str] = field(default_factory=list)
    expected_min_claims: int = 1


def _get_claude_code_sources(tmp_path: Path) -> Path:
    """Collect Claude Code agent files into a temp directory for archiving."""
    source_dir = tmp_path / "claude-code-sources"
    source_dir.mkdir()

    # Copy files from repo that constitute Claude Code's context
    files_to_copy = [
        "CLAUDE.md",
        "memory/MEMORY.md",
        "memory/active.md",
        "memory/architecture.md",
        "memory/spec-knowledge.md",
        "memory/gotchas.md",
        "memory/research.md",
    ]

    for rel_path in files_to_copy:
        src = REPO_ROOT / rel_path
        if src.exists():
            dst = source_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # Also copy .claude commands if they exist (skip hidden dir filtering)
    commands_dir = REPO_ROOT / ".claude" / "commands"
    if commands_dir.exists():
        dst_commands = source_dir / "claude-commands"
        dst_commands.mkdir(parents=True, exist_ok=True)
        for cmd_file in commands_dir.glob("*.md"):
            shutil.copy2(cmd_file, dst_commands / cmd_file.name)

    return source_dir


AGENT_CONFIGS = [
    AgentTestConfig(
        name="claude-code",
        source_dir="<dynamic>",  # resolved at test time
        archive_id="arc://agent/claude-code",
        expected_claim_keywords=["must", "should", "prefer", "artifact", "manifest"],
        expected_min_claims=5,
    ),
    AgentTestConfig(
        name="aider",
        source_dir=FIXTURES_DIR / "aider",
        archive_id="arc://agent/aider",
        expected_claim_keywords=["pytest", "ruff", "lint", "docstring", "coverage"],
        expected_min_claims=3,
    ),
    AgentTestConfig(
        name="crewai",
        source_dir=FIXTURES_DIR / "crewai",
        archive_id="arc://agent/crewai",
        expected_claim_keywords=["agent", "research", "writer", "review", "sources"],
        expected_min_claims=3,
    ),
]


class TestAgentProtocol:
    """Run the full test protocol for each agent."""

    @pytest.fixture(params=AGENT_CONFIGS, ids=[a.name for a in AGENT_CONFIGS])
    def agent_config(self, request, tmp_path):
        config = request.param
        if config.name == "claude-code":
            config = AgentTestConfig(
                name=config.name,
                source_dir=_get_claude_code_sources(tmp_path),
                archive_id=config.archive_id,
                expected_claim_keywords=config.expected_claim_keywords,
                expected_min_claims=config.expected_min_claims,
            )
        return config

    @pytest.fixture
    def built(self, agent_config, tmp_path):
        """Build the archive for this agent."""
        arc_dir = tmp_path / f"{agent_config.name}.arc"
        result = build_archive(
            source_dir=agent_config.source_dir,
            output_dir=arc_dir,
            archive_id=agent_config.archive_id,
        )
        return result, arc_dir

    def test_build_succeeds(self, built):
        result, _ = built
        assert result.valid, f"Build failed: {result.errors}"
        assert len(result.text_units) > 0
        assert len(result.claims) > 0

    def test_verify_passes(self, built):
        result, arc_dir = built
        assert result.valid
        v = verify(arc_dir)
        assert v.valid, f"Verify failed: {v.errors}"
        assert len(v.failed_digests) == 0
        assert len(v.missing_blobs) == 0

    def test_inspect_produces_output(self, built):
        """Inspect should show archive metadata."""
        result, arc_dir = built
        assert result.valid
        from arc.manifest import read_manifest_from_cas

        cas = ContentAddressedStore(arc_dir)
        manifest = read_manifest_from_cas(cas)
        assert manifest is not None
        assert manifest.archive_id != ""
        assert len(manifest.layers) >= 2  # at least source-units + claims

    def test_restore_produces_files(self, built, tmp_path):
        result, arc_dir = built
        assert result.valid
        restored_dir = tmp_path / "restored"
        restore_result = restore_sources(arc_dir, restored_dir)
        assert len(restore_result["restored_files"]) > 0
        assert restore_result["total_bytes"] > 0

    def test_selective_load_claims_only(self, built):
        """Loading only claims layer should return claims but no decisions."""
        result, arc_dir = built
        assert result.valid
        loaded = load(arc_dir, layers=["claims"])
        assert not loaded.rejected
        assert len(loaded.claims) > 0
        # Source units not loaded
        assert len(loaded.source_units) == 0

    def test_selective_load_decisions(self, built):
        """Loading decisions layer separately."""
        result, arc_dir = built
        assert result.valid
        loaded = load(arc_dir, layers=["decisions"])
        assert not loaded.rejected
        # Decisions may or may not exist depending on agent
        # But load should succeed without rejection

    def test_claims_have_evidence(self, built):
        """Every claim must have at least one evidence pointer."""
        result, _ = built
        assert result.valid
        for claim in result.claims:
            assert len(claim.evidence) > 0, (
                f"Claim has no evidence: {claim.text[:60]}..."
            )

    def test_evidence_points_to_valid_source(self, built):
        """Every evidence pointer must reference a real source unit."""
        result, _ = built
        assert result.valid
        su_ids = {tu.id for tu in result.text_units}
        for claim in result.claims:
            for ev in claim.evidence:
                assert ev.source_unit_id in su_ids, (
                    f"Claim '{claim.text[:40]}...' references unknown source unit "
                    f"'{ev.source_unit_id}'"
                )

    def test_expected_claims_found(self, agent_config, built):
        """Agent-specific keywords should appear in extracted claims."""
        result, _ = built
        assert result.valid
        all_claim_text = " ".join(c.text.lower() for c in result.claims)
        found_keywords = [
            kw for kw in agent_config.expected_claim_keywords
            if kw.lower() in all_claim_text
        ]
        assert len(found_keywords) >= 1, (
            f"None of expected keywords {agent_config.expected_claim_keywords} "
            f"found in {len(result.claims)} claims"
        )

    def test_minimum_claim_count(self, agent_config, built):
        result, _ = built
        assert result.valid
        assert len(result.claims) >= agent_config.expected_min_claims, (
            f"Expected at least {agent_config.expected_min_claims} claims, "
            f"got {len(result.claims)}"
        )


class TestGenerateResults:
    """Generate results/ directory with evidence for all 3 agents."""

    def test_generate_summary(self, tmp_path):
        """Build all 3 agents and produce results/summary.json."""
        results = []

        for config in AGENT_CONFIGS:
            if config.name == "claude-code":
                source_dir = _get_claude_code_sources(tmp_path)
            else:
                source_dir = config.source_dir

            arc_dir = tmp_path / f"{config.name}.arc"
            build_result = build_archive(
                source_dir=source_dir,
                output_dir=arc_dir,
                archive_id=config.archive_id,
            )

            if not build_result.valid:
                results.append({
                    "agent": config.name,
                    "build_success": False,
                    "errors": build_result.errors,
                })
                continue

            # Verify
            v = verify(arc_dir)

            # Restore
            restored_dir = tmp_path / f"restored-{config.name}"
            restore_result = restore_sources(arc_dir, restored_dir)

            # Selective load
            claims_load = load(arc_dir, layers=["claims"])
            decisions_load = load(arc_dir, layers=["decisions"])

            results.append({
                "agent": config.name,
                "build_success": True,
                "source_files": len(build_result.resources),
                "source_units": len(build_result.text_units),
                "claims_extracted": len(build_result.claims),
                "decisions_extracted": len(build_result.decisions),
                "verify_passed": v.valid,
                "restore_files": len(restore_result["restored_files"]),
                "restore_bytes": restore_result["total_bytes"],
                "selective_load_claims": len(claims_load.claims),
                "selective_load_decisions": len(decisions_load.decisions),
                "all_claims_have_evidence": all(
                    len(c.evidence) > 0 for c in build_result.claims
                ),
            })

        summary = {
            "test_date": "2026-03-16",
            "agents_tested": len(results),
            "results": results,
        }

        # Write to results/ in the repo (not committed)
        RESULTS_DIR.mkdir(exist_ok=True)
        summary_path = RESULTS_DIR / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))

        # Also write per-agent reports
        for config in AGENT_CONFIGS:
            agent_results_dir = RESULTS_DIR / config.name
            agent_results_dir.mkdir(exist_ok=True)

            arc_dir = tmp_path / f"{config.name}.arc"
            if not arc_dir.exists():
                continue

            # Verify report
            v = verify(arc_dir)
            verify_report = {
                "valid": v.valid,
                "failed_digests": v.failed_digests,
                "missing_blobs": v.missing_blobs,
                "errors": v.errors,
            }
            (agent_results_dir / "verify-report.json").write_text(
                json.dumps(verify_report, indent=2)
            )

            # Inspect report
            from arc.manifest import read_manifest_from_cas
            cas = ContentAddressedStore(arc_dir)
            manifest = read_manifest_from_cas(cas)
            if manifest:
                lines = [
                    f"Archive: {manifest.archive_id}",
                    f"Version: {manifest.archive_version}",
                    f"Schema: {manifest.schema_version}",
                    f"Created: {manifest.created_at}",
                    f"Root digest: {manifest.root_digest[:16]}...",
                    f"Layers: {len(manifest.layers)}",
                    f"Blobs: {len(cas.list_blobs())} ({cas.archive_size():,} bytes)",
                ]
                (agent_results_dir / "inspect-report.txt").write_text("\n".join(lines))

            # Claims sample
            loaded = load(arc_dir)
            if not loaded.rejected and loaded.claims:
                sample = [c.to_dict() for c in loaded.claims[:10]]
                (agent_results_dir / "claims-sample.json").write_text(
                    json.dumps(sample, indent=2)
                )

            # Decisions sample
            if not loaded.rejected and loaded.decisions:
                sample = [d.to_dict() for d in loaded.decisions[:5]]
                (agent_results_dir / "decisions-sample.json").write_text(
                    json.dumps(sample, indent=2)
                )

        # Assert all agents built successfully
        assert all(r["build_success"] for r in results), (
            f"Some agents failed: {[r for r in results if not r['build_success']]}"
        )
        assert all(r.get("verify_passed", False) for r in results)
        assert all(r.get("all_claims_have_evidence", False) for r in results)

        # Print summary for visibility
        print(f"\n{'='*60}")
        print(f"ARC 3-Agent Test Summary")
        print(f"{'='*60}")
        for r in results:
            print(f"\n{r['agent']}:")
            print(f"  Sources: {r.get('source_files', 0)}")
            print(f"  Units:   {r.get('source_units', 0)}")
            print(f"  Claims:  {r.get('claims_extracted', 0)}")
            print(f"  Decisions: {r.get('decisions_extracted', 0)}")
            print(f"  Verify:  {'PASS' if r.get('verify_passed') else 'FAIL'}")
            print(f"  Restored: {r.get('restore_files', 0)} files")
            print(f"  Evidence: {'complete' if r.get('all_claims_have_evidence') else 'INCOMPLETE'}")
        print(f"\nResults written to: {RESULTS_DIR}")
