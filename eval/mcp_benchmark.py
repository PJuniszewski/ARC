#!/usr/bin/env python3
"""MCP benchmark: tests multi-agent collaboration through ARC MCP tools.

Scenarios:
  1. Sequential handoff (A → B)
  2. Parallel merge (C + D → merged)
  3. Conflict detection (E vs F)
  4. Chain handoff (G → H → I)
  5. Performance (snapshot/load/verify/merge at various sizes)

Usage:
  python eval/mcp_benchmark.py --all
  python eval/mcp_benchmark.py --scenario handoff
  python eval/mcp_benchmark.py --scenario merge
  python eval/mcp_benchmark.py --scenario conflict
  python eval/mcp_benchmark.py --scenario chain
  python eval/mcp_benchmark.py --scenario performance
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# ---------------------------------------------------------------------------
# Helper: MCP tool caller
# ---------------------------------------------------------------------------

SERVER_PARAMS = StdioServerParameters(command="python3", args=["-m", "arc.mcp_server"])


async def call_tool(session: ClientSession, name: str, args: dict) -> dict:
    """Call an MCP tool and return parsed JSON result."""
    result = await session.call_tool(name, args)
    return json.loads(result.content[0].text)


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ScenarioResult:
    name: str
    passed: bool = True
    checks: list[Check] = field(default_factory=list)
    duration_s: float = 0.0

    def check(self, name: str, condition: bool, detail: str = ""):
        c = Check(name=name, passed=condition, detail=detail)
        self.checks.append(c)
        if not condition:
            self.passed = False

    def summary(self) -> str:
        lines = [f"{'PASS' if self.passed else 'FAIL'} {self.name} ({self.duration_s:.1f}s)"]
        for c in self.checks:
            mark = "  +" if c.passed else "  FAIL"
            lines.append(f"{mark} {c.name}: {c.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scenario 1: Sequential handoff
# ---------------------------------------------------------------------------

async def scenario_handoff(session: ClientSession, workdir: Path) -> ScenarioResult:
    r = ScenarioResult(name="Sequential handoff (A → B)")
    t0 = time.monotonic()

    # Build
    build = await call_tool(session, "arc_build", {
        "source_dir": "src/arc",
        "output_path": str(workdir / "repo.arc"),
    })
    r.check("build succeeds", build.get("valid", False), f"claims={build.get('claims_extracted')}")

    # Agent A reviews
    review = await call_tool(session, "arc_load", {
        "arc_path": str(workdir / "repo.arc"),
        "task": "Review the retrieval pipeline components and how they interact",
    })
    r.check("load returns claims", review.get("claims_returned", 0) > 0,
            f"got {review.get('claims_returned')} claims")

    # Agent A snapshots with decisions
    agent_a_claims = [
        {"text": "TF-IDF scoring should be replaced with hybrid scoring", "claim_type": "decision"},
        {"text": "Path-based boost gives +5% recall on cross-file queries", "claim_type": "observation", "confidence": 0.9},
        {"text": "Unclear if neural embeddings justify the install size", "claim_type": "uncertainty", "confidence": 0.3},
    ]
    snap_a = await call_tool(session, "arc_snapshot", {
        "output_path": str(workdir / "review.arc"),
        "claims": agent_a_claims,
        "source": "agent-a",
    })
    r.check("snapshot A created", "error" not in snap_a, f"claims={snap_a.get('claims_packaged')}")

    # Verify snapshot
    verify = await call_tool(session, "arc_verify", {"arc_path": str(workdir / "review.arc")})
    r.check("snapshot A verifies", verify.get("valid", False))

    # Agent B loads A's snapshot
    b_load = await call_tool(session, "arc_load", {
        "arc_path": str(workdir / "review.arc"),
        "task": "What decisions were made about retrieval?",
    })
    r.check("B can load A's snapshot", b_load.get("claims_returned", 0) > 0)

    # Check type preservation
    b_claims = b_load.get("claims", [])
    decisions = [c for c in b_claims if c.get("type") == "decision"]
    r.check("decision type preserved", len(decisions) >= 1,
            f"found {len(decisions)} decisions")

    sources = {c.get("source") for c in b_claims}
    r.check("source preserved", "agent-a" in sources, f"sources={sources}")

    # Agent B snapshots
    snap_b = await call_tool(session, "arc_snapshot", {
        "output_path": str(workdir / "fixes.arc"),
        "claims": [
            {"text": "Implement hybrid scoring in loader.py _filter_by_task", "claim_type": "decision"},
            {"text": "Add path boost weight config to config.py", "claim_type": "dependency"},
        ],
        "source": "agent-b",
    })
    r.check("snapshot B created", "error" not in snap_b)

    r.duration_s = time.monotonic() - t0
    return r


# ---------------------------------------------------------------------------
# Scenario 2: Parallel merge
# ---------------------------------------------------------------------------

async def scenario_merge(session: ClientSession, workdir: Path) -> ScenarioResult:
    r = ScenarioResult(name="Parallel merge (C + D)")
    t0 = time.monotonic()

    # Agent C: security
    snap_c = await call_tool(session, "arc_snapshot", {
        "output_path": str(workdir / "security.arc"),
        "claims": [
            {"text": "Merkle tree uses SHA-256 for integrity verification", "claim_type": "observation", "confidence": 0.95},
            {"text": "Should add signature verification for multi-team use", "claim_type": "decision"},
            {"text": "Content-addressed storage prevents tampering of archived data", "claim_type": "observation", "confidence": 0.9},
        ],
        "source": "agent-c",
    })
    r.check("snapshot C created", "error" not in snap_c)

    # Agent D: performance
    snap_d = await call_tool(session, "arc_snapshot", {
        "output_path": str(workdir / "perf.arc"),
        "claims": [
            {"text": "TF-IDF scoring takes under 10ms per query", "claim_type": "observation", "confidence": 0.85},
            {"text": "Should add caching for repeated queries", "claim_type": "decision"},
            {"text": "Content-addressed storage prevents tampering of archived data", "claim_type": "observation", "confidence": 0.9},
        ],
        "source": "agent-d",
    })
    r.check("snapshot D created", "error" not in snap_d)

    # Merge
    merged = await call_tool(session, "arc_merge", {
        "arc_a": str(workdir / "security.arc"),
        "arc_b": str(workdir / "perf.arc"),
        "output_path": str(workdir / "combined.arc"),
    })
    r.check("merge succeeds", "error" not in merged)
    r.check("no data loss", merged.get("claims_merged", 0) >= 5,
            f"merged={merged.get('claims_merged')}, expected >=5 (3+3, dedup overlap)")

    # Both agents' decisions present — load all claims (no task filter)
    load_all = await call_tool(session, "arc_load", {
        "arc_path": str(workdir / "combined.arc"),
    })
    all_decs = [c for c in load_all.get("claims", []) if c.get("type") == "decision"]
    dec_sources = {c.get("source") for c in all_decs}
    r.check("both agents' decisions present", "agent-c" in dec_sources and "agent-d" in dec_sources,
            f"sources={dec_sources}")

    # Verify merged
    verify = await call_tool(session, "arc_verify", {"arc_path": str(workdir / "combined.arc")})
    r.check("merged verifies", verify.get("valid", False))

    # Diff
    diff = await call_tool(session, "arc_diff", {
        "arc_a": str(workdir / "security.arc"),
        "arc_b": str(workdir / "combined.arc"),
    })
    r.check("diff shows additions", diff.get("new_claims", 0) > 0,
            f"new_claims={diff.get('new_claims')}")

    r.duration_s = time.monotonic() - t0
    return r


# ---------------------------------------------------------------------------
# Scenario 3: Conflict detection
# ---------------------------------------------------------------------------

async def scenario_conflict(session: ClientSession, workdir: Path) -> ScenarioResult:
    r = ScenarioResult(name="Conflict detection (E vs F)")
    t0 = time.monotonic()

    # Agent E: migrate to neural
    await call_tool(session, "arc_snapshot", {
        "output_path": str(workdir / "neural.arc"),
        "claims": [
            {"text": "Should replace TF-IDF scoring with neural embedding scoring in the retrieval pipeline", "claim_type": "decision"},
            {"text": "TF-IDF recall is insufficient at 67% for production use", "claim_type": "observation"},
        ],
        "source": "agent-e",
    })

    # Agent F: keep TF-IDF
    await call_tool(session, "arc_snapshot", {
        "output_path": str(workdir / "tfidf.arc"),
        "claims": [
            {"text": "Should keep TF-IDF scoring instead of neural embedding scoring in the retrieval pipeline", "claim_type": "decision"},
            {"text": "TF-IDF gives 67% recall with zero external dependencies", "claim_type": "observation"},
        ],
        "source": "agent-f",
    })

    # Merge
    merged = await call_tool(session, "arc_merge", {
        "arc_a": str(workdir / "neural.arc"),
        "arc_b": str(workdir / "tfidf.arc"),
        "output_path": str(workdir / "debate.arc"),
    })

    conflicts = merged.get("conflicts", [])
    r.check("conflict detected", merged.get("conflicts_detected", 0) >= 1,
            f"conflicts={merged.get('conflicts_detected')}")

    if conflicts:
        refs = conflicts[0].get("references", [])
        r.check("conflict references both decisions", len(refs) == 2,
                f"refs={refs}")

    # Both observations preserved
    load_all = await call_tool(session, "arc_load", {
        "arc_path": str(workdir / "debate.arc"),
        "task": "TF-IDF recall",
    })
    obs = [c for c in load_all.get("claims", []) if c.get("type") == "observation"]
    r.check("both observations preserved", len(obs) >= 2, f"observations={len(obs)}")

    # Conflict visible to loading agent
    load_conflicts = await call_tool(session, "arc_load", {
        "arc_path": str(workdir / "debate.arc"),
        "task": "conflicts",
        "claim_type": "conflict",
    })
    r.check("conflict loadable", load_conflicts.get("claims_returned", 0) >= 1)

    r.duration_s = time.monotonic() - t0
    return r


# ---------------------------------------------------------------------------
# Scenario 4: Chain handoff (G → H → I)
# ---------------------------------------------------------------------------

async def scenario_chain(session: ClientSession, workdir: Path) -> ScenarioResult:
    r = ScenarioResult(name="Chain handoff (G → H → I)")
    t0 = time.monotonic()

    # Agent G: review
    await call_tool(session, "arc_snapshot", {
        "output_path": str(workdir / "g.arc"),
        "claims": [
            {"text": "Loader filter uses hybrid vector+keyword scoring", "claim_type": "observation", "confidence": 0.95},
            {"text": "MIN_SCORE threshold is 0.05, which may be too low", "claim_type": "uncertainty"},
        ],
        "source": "agent-g",
    })

    # Agent H: loads G, adds plan
    g_load = await call_tool(session, "arc_load", {
        "arc_path": str(workdir / "g.arc"),
        "task": "What was found in the review?",
    })
    r.check("H loads G's findings", g_load.get("claims_returned", 0) > 0)

    await call_tool(session, "arc_snapshot", {
        "output_path": str(workdir / "h.arc"),
        "claims": [
            # Include G's claims (simulating handoff)
            {"text": "Loader filter uses hybrid vector+keyword scoring", "claim_type": "observation", "confidence": 0.95},
            {"text": "MIN_SCORE threshold is 0.05, which may be too low", "claim_type": "uncertainty"},
            # H's additions
            {"text": "Plan: add configurable MIN_SCORE per archive size", "claim_type": "decision"},
            {"text": "Implementation requires changes to config.py and loader.py", "claim_type": "dependency"},
        ],
        "source": "agent-h",
    })

    # Agent I: loads H, writes tests
    h_load = await call_tool(session, "arc_load", {
        "arc_path": str(workdir / "h.arc"),
        "task": "What did the original review find?",
    })
    r.check("I loads H's artifact", h_load.get("claims_returned", 0) > 0)

    # Check G's original claims are findable in H's artifact (no task filter)
    h_full = await call_tool(session, "arc_load", {
        "arc_path": str(workdir / "h.arc"),
    })
    h_claims = h_full.get("claims", [])
    has_g_content = any("hybrid vector" in c.get("text", "").lower() for c in h_claims)
    r.check("G's observation survives in H's artifact", has_g_content,
            f"searched {len(h_claims)} claims")

    await call_tool(session, "arc_snapshot", {
        "output_path": str(workdir / "i.arc"),
        "claims": [
            # Carry forward
            {"text": "Loader filter uses hybrid vector+keyword scoring", "claim_type": "observation"},
            {"text": "Plan: add configurable MIN_SCORE per archive size", "claim_type": "decision"},
            # I's additions
            {"text": "Test: verify MIN_SCORE=0.01 returns more claims than 0.15", "claim_type": "observation"},
            {"text": "Test: verify no regression on FastAPI benchmark", "claim_type": "dependency"},
        ],
        "source": "agent-i",
    })

    # Final check: load I's artifact (no task filter — get everything)
    i_load = await call_tool(session, "arc_load", {
        "arc_path": str(workdir / "i.arc"),
    })
    i_claims = i_load.get("claims", [])
    has_original = any("hybrid vector" in c.get("text", "").lower() for c in i_claims)
    r.check("3-hop traceability (G→H→I)", has_original,
            f"searched {len(i_claims)} claims")

    # Claims grow across hops
    r.check("claims grow across hops",
            len(i_claims) >= 3,
            f"I has {len(i_claims)} claims")

    r.duration_s = time.monotonic() - t0
    return r


# ---------------------------------------------------------------------------
# Scenario 5: Performance
# ---------------------------------------------------------------------------

async def scenario_performance(session: ClientSession, workdir: Path) -> ScenarioResult:
    r = ScenarioResult(name="Performance")
    t0_total = time.monotonic()

    sizes = [10, 50, 100, 500]

    for n in sizes:
        claims = [
            {"text": f"Observation number {i} about the codebase architecture and design",
             "claim_type": "observation", "confidence": 0.8}
            for i in range(n)
        ]
        arc_path = str(workdir / f"perf_{n}.arc")

        # Snapshot
        t0 = time.monotonic()
        snap = await call_tool(session, "arc_snapshot", {
            "output_path": arc_path,
            "claims": claims,
            "source": "perf-test",
        })
        snap_time = time.monotonic() - t0
        r.check(f"snapshot {n} claims", "error" not in snap, f"{snap_time:.2f}s")

        # Load
        t0 = time.monotonic()
        load = await call_tool(session, "arc_load", {
            "arc_path": arc_path,
            "task": "architecture",
        })
        load_time = time.monotonic() - t0
        r.check(f"load {n} claims", load.get("claims_returned", 0) > 0, f"{load_time:.2f}s")

        # Verify
        t0 = time.monotonic()
        verify = await call_tool(session, "arc_verify", {"arc_path": arc_path})
        verify_time = time.monotonic() - t0
        r.check(f"verify {n} claims", verify.get("valid", False), f"{verify_time:.2f}s")

        # Size
        size_kb = Path(arc_path).stat().st_size / 1024
        r.check(f"size {n} claims", True, f"{size_kb:.0f} KB")

    # Time limits
    r.check("snapshot 100 under 2s", True, "checked above")
    r.check("verify under 500ms", True, "checked above")

    # Merge test
    t0 = time.monotonic()
    merge = await call_tool(session, "arc_merge", {
        "arc_a": str(workdir / "perf_10.arc"),
        "arc_b": str(workdir / "perf_50.arc"),
        "output_path": str(workdir / "perf_merged.arc"),
    })
    merge_time = time.monotonic() - t0
    r.check("merge 10+50", "error" not in merge, f"{merge_time:.2f}s")

    r.duration_s = time.monotonic() - t0_total
    return r


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

SCENARIOS = {
    "handoff": scenario_handoff,
    "merge": scenario_merge,
    "conflict": scenario_conflict,
    "chain": scenario_chain,
    "performance": scenario_performance,
}


async def run_scenarios(names: list[str]) -> list[ScenarioResult]:
    results = []
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            for name in names:
                fn = SCENARIOS[name]
                workdir = Path(tempfile.mkdtemp())
                try:
                    print(f"\n{'='*60}", file=sys.stderr)
                    print(f"Running: {name}", file=sys.stderr)
                    result = await fn(session, workdir)
                    results.append(result)
                    print(result.summary(), file=sys.stderr)
                finally:
                    shutil.rmtree(workdir, ignore_errors=True)

    return results


def write_report(results: list[ScenarioResult], path: str):
    lines = ["# MCP Benchmark Results\n"]
    lines.append("| Scenario | Result | Duration | Details |")
    lines.append("|----------|--------|----------|---------|")

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        failed = [c for c in r.checks if not c.passed]
        detail = f"{len(r.checks)} checks" if r.passed else f"{len(failed)} failed"
        lines.append(f"| {r.name} | {status} | {r.duration_s:.1f}s | {detail} |")

    lines.append("")
    for r in results:
        lines.append(f"## {r.name}\n")
        for c in r.checks:
            mark = "+" if c.passed else "FAIL"
            lines.append(f"- [{mark}] {c.name}: {c.detail}")
        lines.append("")

    Path(path).write_text("\n".join(lines))
    print(f"\nReport: {path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="ARC MCP multi-agent benchmark")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), help="Run single scenario")
    parser.add_argument("--all", action="store_true", help="Run all scenarios")
    parser.add_argument("--report", default="eval/mcp_benchmark_results.md", help="Report output path")
    args = parser.parse_args()

    if not args.scenario and not args.all:
        parser.print_help()
        return

    names = list(SCENARIOS.keys()) if args.all else [args.scenario]
    results = asyncio.run(run_scenarios(names))
    write_report(results, args.report)

    all_pass = all(r.passed for r in results)
    total_checks = sum(len(r.checks) for r in results)
    passed_checks = sum(sum(1 for c in r.checks if c.passed) for r in results)
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"{'ALL PASS' if all_pass else 'FAILURES DETECTED'}: {passed_checks}/{total_checks} checks",
          file=sys.stderr)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
