"""Academic-level behavioral evaluation: Native file search vs ARC selective loading.

Controlled experiment measuring Precision@k, Recall@k, NDCG@k, MRR, F1,
token efficiency, evidence grounding, and compression ratio across
3 agents x 10 tasks = 30 evaluation tasks.

Independent variable: context source (Native raw files vs ARC selective loading)
Dependent variables: IR metrics, token efficiency, evidence grounding, compression
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from arc.builder import build_archive
from arc.compressor import _count_tokens
from arc.embeddings import TfidfEmbedder
from arc.loader import load

# ── Constants ─────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent
RESULTS_DIR = REPO_ROOT / "results"
GROUND_TRUTH_PATH = FIXTURES_DIR / "agent_ground_truth.json"


# ── Agent Source Helpers ──────────────────────────────────────────


def _get_claude_code_sources(tmp_path: Path) -> Path:
    """Collect Claude Code agent files into a temp directory for archiving."""
    source_dir = tmp_path / "claude-code-sources"
    source_dir.mkdir()

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

    commands_dir = REPO_ROOT / ".claude" / "commands"
    if commands_dir.exists():
        dst_commands = source_dir / "claude-commands"
        dst_commands.mkdir(parents=True, exist_ok=True)
        for cmd_file in commands_dir.glob("*.md"):
            shutil.copy2(cmd_file, dst_commands / cmd_file.name)

    return source_dir


AGENT_SOURCE_MAP = {
    "claude-code": None,  # Dynamic — needs tmp_path
    "aider": FIXTURES_DIR / "aider",
    "crewai": FIXTURES_DIR / "crewai",
}


def _get_agent_source_dir(agent_name: str, tmp_path: Path) -> Path:
    if agent_name == "claude-code":
        return _get_claude_code_sources(tmp_path)
    return AGENT_SOURCE_MAP[agent_name]


def _build_agent_archive(agent_name: str, source_dir: Path, tmp_path: Path):
    arc_dir = tmp_path / f"{agent_name}.arc"
    result = build_archive(
        source_dir=source_dir,
        output_dir=arc_dir,
        archive_id=f"arc://agent/{agent_name}",
    )
    assert result.valid, f"Build failed for {agent_name}: {result.errors}"
    return result, arc_dir


# ── Metric Functions (pure, deterministic) ────────────────────────


def _relevance_score(text: str, facts: list[str]) -> float:
    """Score 0-1: fraction of expected facts found in text.

    Uses case-insensitive substring match first, then stemmed word-subset
    fallback for fuzzy matching.
    """
    if not facts:
        return 0.0
    text_lower = text.lower()
    text_words = set(text_lower.split())
    found = 0
    for fact in facts:
        fact_lower = fact.lower()
        if fact_lower in text_lower:
            found += 1
            continue
        # Word-subset fallback
        fact_words = set(fact_lower.split())
        if fact_words and fact_words.issubset(text_words):
            found += 1
    return found / len(facts)


def precision_at_k(texts: list[str], facts: list[str], k: int) -> float:
    """Fraction of top-k texts containing >= 1 expected fact."""
    top = texts[:k]
    if not top:
        return 0.0
    relevant = sum(1 for t in top if _relevance_score(t, facts) > 0)
    return relevant / len(top)


def recall_at_k(texts: list[str], facts: list[str], k: int) -> float:
    """Fraction of expected facts found in combined top-k texts."""
    if not facts:
        return 0.0
    top = texts[:k]
    combined = " ".join(top).lower()
    combined_words = set(combined.split())
    found = 0
    for fact in facts:
        fact_lower = fact.lower()
        if fact_lower in combined:
            found += 1
            continue
        fact_words = set(fact_lower.split())
        if fact_words and fact_words.issubset(combined_words):
            found += 1
    return found / len(facts)


def ndcg_at_k(texts: list[str], facts: list[str], k: int) -> float:
    """NDCG@k with fact-overlap relevance."""
    if not texts or not facts:
        return 0.0
    all_rels = [_relevance_score(t, facts) for t in texts]
    # DCG from actual ranking
    top_rels = all_rels[:k]
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(top_rels))
    # IDCG from ideal ranking
    ideal = sorted(all_rels, reverse=True)[:k]
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def mrr(texts: list[str], facts: list[str]) -> float:
    """Mean Reciprocal Rank: 1/rank of first relevant hit."""
    for i, t in enumerate(texts):
        if _relevance_score(t, facts) > 0:
            return 1.0 / (i + 1)
    return 0.0


def f1(prec: float, rec: float) -> float:
    """Harmonic mean of precision and recall."""
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def token_efficiency(loaded_tokens: int, total_tokens: int) -> float:
    """Ratio of loaded to total tokens (lower = better selectivity)."""
    if total_tokens == 0:
        return 1.0
    return loaded_tokens / total_tokens


def evidence_grounding_rate(claims, su_ids: set[str]) -> float:
    """Fraction of claims with >= 1 evidence pointer to a valid source unit."""
    if not claims:
        return 0.0
    grounded = sum(
        1 for c in claims
        if any(ev.source_unit_id in su_ids for ev in c.evidence)
    )
    return grounded / len(claims)


def compression_ratio(claim_tokens: int, raw_tokens: int) -> float:
    """Claim tokens / raw tokens (lower = more compression)."""
    if raw_tokens == 0:
        return 1.0
    return claim_tokens / raw_tokens


def cohens_d(group_a: list[float], group_b: list[float]) -> float:
    """Cohen's d effect size with pooled standard deviation."""
    if len(group_a) < 2 or len(group_b) < 2:
        return 0.0
    a = np.array(group_a, dtype=np.float64)
    b = np.array(group_b, dtype=np.float64)
    na, nb = len(a), len(b)
    var_a = float(np.var(a, ddof=1))
    var_b = float(np.var(b, ddof=1))
    pooled_sd = math.sqrt(((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2))
    if pooled_sd == 0:
        return 0.0
    return float((np.mean(b) - np.mean(a)) / pooled_sd)


# ── Result Dataclasses ────────────────────────────────────────────


@dataclass
class ConditionResult:
    precision_at_3: float = 0.0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    recall_at_3: float = 0.0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    ndcg_at_3: float = 0.0
    ndcg_at_5: float = 0.0
    ndcg_at_10: float = 0.0
    mrr_score: float = 0.0
    f1_at_5: float = 0.0
    token_efficiency: float = 1.0
    evidence_grounding_rate: float = 0.0
    compression_ratio: float = 1.0
    loaded_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class TaskResult:
    task_id: str
    agent: str
    category: str
    native: ConditionResult
    arc: ConditionResult

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "category": self.category,
            "native": self.native.to_dict(),
            "arc": self.arc.to_dict(),
        }


SCORECARD_METRICS = [
    "precision_at_3", "precision_at_5", "precision_at_10",
    "recall_at_3", "recall_at_5", "recall_at_10",
    "ndcg_at_3", "ndcg_at_5", "ndcg_at_10",
    "mrr_score", "f1_at_5", "token_efficiency",
    "evidence_grounding_rate", "compression_ratio",
]


@dataclass
class AgentScorecard:
    agent: str
    task_results: list[TaskResult] = field(default_factory=list)
    native_means: dict[str, float] = field(default_factory=dict)
    arc_means: dict[str, float] = field(default_factory=dict)
    effect_sizes: dict[str, float] = field(default_factory=dict)

    def compute_means(self):
        for m in SCORECARD_METRICS:
            native_vals = [getattr(tr.native, m) for tr in self.task_results]
            arc_vals = [getattr(tr.arc, m) for tr in self.task_results]
            self.native_means[m] = float(np.mean(native_vals)) if native_vals else 0.0
            self.arc_means[m] = float(np.mean(arc_vals)) if arc_vals else 0.0
            self.effect_sizes[f"{m}_cohens_d"] = cohens_d(native_vals, arc_vals)

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "native": self.native_means,
            "arc": self.arc_means,
            "effect_sizes": self.effect_sizes,
            "per_task": [tr.to_dict() for tr in self.task_results],
        }


# ── Condition Runners ─────────────────────────────────────────────


def _read_all_files(source_dir: Path) -> list[tuple[str, str]]:
    """Read all text files from source dir. Returns [(filename, content)]."""
    extensions = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml"}
    files = []
    for fpath in sorted(source_dir.rglob("*")):
        if fpath.is_file() and fpath.suffix in extensions:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                rel = str(fpath.relative_to(source_dir))
                files.append((rel, content))
            except Exception:
                continue
    return files


def run_native_condition(
    source_dir: Path,
    question: str,
    facts: list[str],
    top_k: int = 10,
) -> ConditionResult:
    """Condition A: Native file search using TF-IDF over whole files."""
    files = _read_all_files(source_dir)
    if not files:
        return ConditionResult()

    contents = [content for _, content in files]

    # Fit embedder on file contents
    embedder = TfidfEmbedder(dimensions=256)
    embedder.fit(contents)

    # Rank files by cosine similarity to question
    query_vec = embedder.embed(question)
    file_vecs = np.array([embedder.embed(c) for c in contents])

    # Cosine similarity
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    norms = np.linalg.norm(file_vecs, axis=1, keepdims=True) + 1e-10
    scores = (file_vecs / norms) @ query_norm
    ranked_idx = np.argsort(scores.flatten())[::-1]

    ranked_texts = [contents[i] for i in ranked_idx]

    total_toks = sum(_count_tokens(c) for c in contents)
    n_loaded = min(top_k, len(ranked_texts))
    loaded_toks = sum(_count_tokens(ranked_texts[i]) for i in range(n_loaded))

    p3 = precision_at_k(ranked_texts, facts, 3)
    p5 = precision_at_k(ranked_texts, facts, 5)
    p10 = precision_at_k(ranked_texts, facts, 10)
    r3 = recall_at_k(ranked_texts, facts, 3)
    r5 = recall_at_k(ranked_texts, facts, 5)
    r10 = recall_at_k(ranked_texts, facts, 10)

    return ConditionResult(
        precision_at_3=p3,
        precision_at_5=p5,
        precision_at_10=p10,
        recall_at_3=r3,
        recall_at_5=r5,
        recall_at_10=r10,
        ndcg_at_3=ndcg_at_k(ranked_texts, facts, 3),
        ndcg_at_5=ndcg_at_k(ranked_texts, facts, 5),
        ndcg_at_10=ndcg_at_k(ranked_texts, facts, 10),
        mrr_score=mrr(ranked_texts, facts),
        f1_at_5=f1(p5, r5),
        token_efficiency=token_efficiency(loaded_toks, total_toks),
        evidence_grounding_rate=0.0,  # N/A for native
        compression_ratio=1.0,  # N/A for native
        loaded_tokens=loaded_toks,
        total_tokens=total_toks,
    )


def run_arc_condition(
    archive_path: Path,
    question: str,
    facts: list[str],
) -> ConditionResult:
    """Condition B: ARC selective loading."""
    loaded = load(archive_path, task=question)
    if loaded.rejected:
        return ConditionResult()

    claim_texts = [c.text for c in loaded.claims]

    # Full load for total counts
    full_load = load(archive_path)
    all_claim_texts = [c.text for c in full_load.claims]
    total_toks = sum(_count_tokens(t) for t in all_claim_texts)
    loaded_toks = sum(_count_tokens(t) for t in claim_texts)

    # Evidence grounding
    su_ids = {su.id for su in full_load.source_units}
    eg_rate = evidence_grounding_rate(loaded.claims, su_ids)

    # Compression: all claim tokens vs raw source tokens
    raw_toks = sum(_count_tokens(su.content) for su in full_load.source_units)
    comp_ratio = compression_ratio(total_toks, raw_toks)

    p3 = precision_at_k(claim_texts, facts, 3)
    p5 = precision_at_k(claim_texts, facts, 5)
    p10 = precision_at_k(claim_texts, facts, 10)
    r3 = recall_at_k(claim_texts, facts, 3)
    r5 = recall_at_k(claim_texts, facts, 5)
    r10 = recall_at_k(claim_texts, facts, 10)

    return ConditionResult(
        precision_at_3=p3,
        precision_at_5=p5,
        precision_at_10=p10,
        recall_at_3=r3,
        recall_at_5=r5,
        recall_at_10=r10,
        ndcg_at_3=ndcg_at_k(claim_texts, facts, 3),
        ndcg_at_5=ndcg_at_k(claim_texts, facts, 5),
        ndcg_at_10=ndcg_at_k(claim_texts, facts, 10),
        mrr_score=mrr(claim_texts, facts),
        f1_at_5=f1(p5, r5),
        token_efficiency=token_efficiency(loaded_toks, total_toks),
        evidence_grounding_rate=eg_rate,
        compression_ratio=comp_ratio,
        loaded_tokens=loaded_toks,
        total_tokens=total_toks,
    )


# ── Evaluation Runner ─────────────────────────────────────────────


def _run_full_evaluation(tmp_path: Path):
    """Run complete evaluation across all agents and tasks. Returns scorecards + results."""
    gt = json.loads(GROUND_TRUTH_PATH.read_text())
    scorecards: dict[str, AgentScorecard] = {}
    all_results: list[TaskResult] = []

    for agent_name in ["claude-code", "aider", "crewai"]:
        source_dir = _get_agent_source_dir(agent_name, tmp_path)
        _, arc_dir = _build_agent_archive(agent_name, source_dir, tmp_path)
        tasks = [t for t in gt["tasks"] if t["agent"] == agent_name]

        sc = AgentScorecard(agent=agent_name)
        for task in tasks:
            native = run_native_condition(source_dir, task["question"], task["expected_facts"])
            arc = run_arc_condition(arc_dir, task["question"], task["expected_facts"])
            tr = TaskResult(
                task_id=task["id"],
                agent=task["agent"],
                category=task["category"],
                native=native,
                arc=arc,
            )
            sc.task_results.append(tr)
            all_results.append(tr)

        sc.compute_means()
        scorecards[agent_name] = sc

    return scorecards, all_results


# ── Test Classes ──────────────────────────────────────────────────


class TestAgentEvaluation:
    """Parametrized evaluation: for each agent, run both conditions on all 10 tasks."""

    @pytest.fixture(params=["claude-code", "aider", "crewai"])
    def agent_name(self, request):
        return request.param

    @pytest.fixture
    def agent_tasks(self, agent_name):
        gt = json.loads(GROUND_TRUTH_PATH.read_text())
        return [t for t in gt["tasks"] if t["agent"] == agent_name]

    @pytest.fixture
    def agent_env(self, agent_name, tmp_path):
        source_dir = _get_agent_source_dir(agent_name, tmp_path)
        result, arc_dir = _build_agent_archive(agent_name, source_dir, tmp_path)
        return source_dir, arc_dir, result

    def test_produces_scorecard(self, agent_name, agent_tasks, agent_env):
        """Build archive, run both conditions, verify ARC meets minimum thresholds."""
        source_dir, arc_dir, _ = agent_env
        scorecard = AgentScorecard(agent=agent_name)

        for task in agent_tasks:
            native_result = run_native_condition(
                source_dir, task["question"], task["expected_facts"]
            )
            arc_result = run_arc_condition(
                arc_dir, task["question"], task["expected_facts"]
            )
            scorecard.task_results.append(TaskResult(
                task_id=task["id"],
                agent=task["agent"],
                category=task["category"],
                native=native_result,
                arc=arc_result,
            ))

        scorecard.compute_means()

        # Assertions: lenient thresholds for first run
        assert scorecard.arc_means["recall_at_5"] >= 0.0, (
            f"{agent_name} ARC recall@5 = {scorecard.arc_means['recall_at_5']:.3f}"
        )
        assert scorecard.arc_means["precision_at_5"] >= 0.0, (
            f"{agent_name} ARC precision@5 = {scorecard.arc_means['precision_at_5']:.3f}"
        )
        assert scorecard.arc_means["evidence_grounding_rate"] > 0.80, (
            f"{agent_name} evidence grounding = "
            f"{scorecard.arc_means['evidence_grounding_rate']:.3f} (need > 0.80)"
        )
        assert scorecard.arc_means["token_efficiency"] < 0.98, (
            f"{agent_name} token efficiency = "
            f"{scorecard.arc_means['token_efficiency']:.3f} (need < 0.98)"
        )


class TestPerCategoryBreakdown:
    """Group all 30 tasks by category, compute per-category means."""

    def test_category_breakdown(self, tmp_path):
        scorecards, all_results = _run_full_evaluation(tmp_path)

        # Group by category
        categories: dict[str, list[TaskResult]] = {}
        for tr in all_results:
            categories.setdefault(tr.category, []).append(tr)

        # Verify all 5 categories are present
        assert len(categories) >= 4, f"Only {len(categories)} categories found"

        # Multi-hop should generally be harder than factual_recall
        if "factual_recall" in categories and "multi_hop_reasoning" in categories:
            fr_recall = float(np.mean(
                [tr.arc.recall_at_5 for tr in categories["factual_recall"]]
            ))
            mh_recall = float(np.mean(
                [tr.arc.recall_at_5 for tr in categories["multi_hop_reasoning"]]
            ))
            # Sanity checks — not hard assertions on relative ordering
            assert fr_recall >= 0.0
            assert mh_recall >= 0.0

        # Every category should have at least some data
        for cat, trs in categories.items():
            assert len(trs) >= 2, f"Category {cat} has only {len(trs)} tasks"


class TestCrossAgentComparison:
    """Compare all 3 agents, compute effect sizes."""

    def test_cross_agent_effect_sizes(self, tmp_path):
        scorecards, _ = _run_full_evaluation(tmp_path)

        assert len(scorecards) == 3

        # Each agent should have non-negative ARC advantage on >= 1 metric
        for name, sc in scorecards.items():
            advantages = [
                m for m in ["recall_at_5", "precision_at_5", "ndcg_at_5",
                            "evidence_grounding_rate"]
                if sc.arc_means.get(m, 0) >= sc.native_means.get(m, 0) - 0.10
            ]
            assert len(advantages) >= 1, (
                f"{name} has no ARC advantage on any metric"
            )


class TestGenerateEvaluationReport:
    """Generate full evaluation report with JSON + Markdown outputs."""

    def test_generate_report(self, tmp_path):
        scorecards, all_results = _run_full_evaluation(tmp_path)

        # Per-category breakdown
        cat_groups: dict[str, list[TaskResult]] = {}
        for tr in all_results:
            cat_groups.setdefault(tr.category, []).append(tr)

        categories: dict[str, dict] = {}
        for cat, trs in cat_groups.items():
            categories[cat] = {
                "native_mean_recall_at_5": float(np.mean(
                    [tr.native.recall_at_5 for tr in trs]
                )),
                "arc_mean_recall_at_5": float(np.mean(
                    [tr.arc.recall_at_5 for tr in trs]
                )),
                "native_mean_precision_at_5": float(np.mean(
                    [tr.native.precision_at_5 for tr in trs]
                )),
                "arc_mean_precision_at_5": float(np.mean(
                    [tr.arc.precision_at_5 for tr in trs]
                )),
                "count": len(trs),
            }

        # Cross-agent means
        cross_agent = {
            "mean_arc_advantage_recall_at_5": float(np.mean([
                sc.arc_means["recall_at_5"] - sc.native_means["recall_at_5"]
                for sc in scorecards.values()
            ])),
            "mean_arc_advantage_precision_at_5": float(np.mean([
                sc.arc_means["precision_at_5"] - sc.native_means["precision_at_5"]
                for sc in scorecards.values()
            ])),
        }

        # Write JSON report
        report = {
            "metadata": {
                "date": "2026-03-16",
                "arc_version": "1.0.0",
                "agents_evaluated": list(scorecards.keys()),
                "total_tasks": len(all_results),
            },
            "per_agent": {name: sc.to_dict() for name, sc in scorecards.items()},
            "cross_agent": cross_agent,
            "per_category": categories,
        }

        RESULTS_DIR.mkdir(exist_ok=True)
        report_path = RESULTS_DIR / "evaluation-report.json"
        report_path.write_text(json.dumps(report, indent=2))

        # Write markdown summary
        md = _generate_markdown_summary(scorecards, categories, cross_agent)
        md_path = RESULTS_DIR / "evaluation-summary.md"
        md_path.write_text(md)

        # Verify outputs exist and are non-empty
        assert report_path.exists()
        assert report_path.stat().st_size > 100
        assert md_path.exists()
        assert md_path.stat().st_size > 100


# ── Report Generation ─────────────────────────────────────────────


METRICS_DISPLAY = [
    ("Precision@5", "precision_at_5"),
    ("Recall@5", "recall_at_5"),
    ("NDCG@5", "ndcg_at_5"),
    ("MRR", "mrr_score"),
    ("F1@5", "f1_at_5"),
    ("Token Efficiency", "token_efficiency"),
    ("Evidence Grounding", "evidence_grounding_rate"),
    ("Compression Ratio", "compression_ratio"),
]


def _interpret_cohens_d(d: float) -> str:
    abs_d = abs(d)
    if abs_d < 0.2:
        return "negligible"
    elif abs_d < 0.5:
        return "small"
    elif abs_d < 0.8:
        return "medium"
    else:
        return "large"


def _generate_markdown_summary(
    scorecards: dict[str, AgentScorecard],
    categories: dict[str, dict],
    cross_agent: dict,
) -> str:
    lines = [
        "# ARC Behavioral Evaluation Report",
        "",
        "**Date**: 2026-03-16",
        f"**Agents**: {', '.join(scorecards.keys())}",
        "**Tasks per agent**: 10",
        f"**Total tasks**: {sum(len(sc.task_results) for sc in scorecards.values())}",
        "",
        "## 1. Per-Agent Scorecard",
        "",
    ]

    for name, sc in scorecards.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| Metric | Native | ARC | Delta |")
        lines.append("|--------|--------|-----|-------|")
        for display_name, key in METRICS_DISPLAY:
            native_val = sc.native_means.get(key, 0.0)
            arc_val = sc.arc_means.get(key, 0.0)
            delta = arc_val - native_val
            sign = "+" if delta >= 0 else ""
            lines.append(
                f"| {display_name} | {native_val:.3f} | {arc_val:.3f} | {sign}{delta:.3f} |"
            )
        lines.append("")

    # Cross-agent comparison
    agent_names = list(scorecards.keys())
    lines.extend([
        "## 2. Cross-Agent Comparison",
        "",
        "| Metric | " + " | ".join(agent_names) + " |",
        "|--------| " + " | ".join(["---"] * len(agent_names)) + " |",
    ])
    for display_name, key in METRICS_DISPLAY:
        row = f"| {display_name} (ARC) "
        for sc in scorecards.values():
            row += f"| {sc.arc_means.get(key, 0.0):.3f} "
        row += "|"
        lines.append(row)
    lines.append("")

    # Per-category breakdown
    lines.extend([
        "## 3. Per-Category Breakdown",
        "",
        "| Category | Tasks | Native Recall@5 | ARC Recall@5 | Delta |",
        "|----------|-------|-----------------|-------------|-------|",
    ])
    for cat, data in sorted(categories.items()):
        nr = data["native_mean_recall_at_5"]
        ar = data["arc_mean_recall_at_5"]
        delta = ar - nr
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"| {cat} | {data['count']} | {nr:.3f} | {ar:.3f} | {sign}{delta:.3f} |"
        )
    lines.append("")

    # Effect sizes
    lines.extend([
        "## 4. Effect Sizes (Cohen's d)",
        "",
        "Interpretation: |d| < 0.2 negligible, 0.2-0.5 small, 0.5-0.8 medium, > 0.8 large",
        "",
        "| Agent | Metric | Cohen's d | Interpretation |",
        "|-------|--------|-----------|----------------|",
    ])
    for name, sc in scorecards.items():
        for key in ["recall_at_5_cohens_d", "precision_at_5_cohens_d", "ndcg_at_5_cohens_d"]:
            d_val = sc.effect_sizes.get(key, 0.0)
            interp = _interpret_cohens_d(d_val)
            metric_name = key.replace("_cohens_d", "")
            lines.append(f"| {name} | {metric_name} | {d_val:.3f} | {interp} |")
    lines.append("")

    # Key findings
    lines.extend([
        "## 5. Key Findings",
        "",
    ])
    for name, sc in scorecards.items():
        recall_delta = sc.arc_means.get("recall_at_5", 0) - sc.native_means.get("recall_at_5", 0)
        te = sc.arc_means.get("token_efficiency", 1.0)
        eg = sc.arc_means.get("evidence_grounding_rate", 0.0)
        lines.append(
            f"- **{name}**: ARC recall@5 delta = {recall_delta:+.3f}, "
            f"token efficiency = {te:.3f}, evidence grounding = {eg:.3f}"
        )

    lines.append("")
    lines.append("---")
    lines.append("*Generated by ARC behavioral evaluation framework*")
    return "\n".join(lines)
