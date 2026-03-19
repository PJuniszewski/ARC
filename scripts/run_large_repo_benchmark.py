#!/usr/bin/env python3
"""Large-repo benchmark: ARC vs baselines on a target repository.

Compares 6 retrieval systems on tasks across 6 categories.
Produces lexical metrics (free), and optionally RAGAS LLM-judged metrics.

Usage:
    python scripts/run_large_repo_benchmark.py --mode=smoke --repo=fastapi
    python scripts/run_large_repo_benchmark.py --mode=full --repo=django
    ANTHROPIC_API_KEY=... python scripts/run_large_repo_benchmark.py --mode=ragas --repo=fastapi
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from arc.builder import build_archive  # noqa: E402
from arc.compressor import _count_tokens  # noqa: E402
from arc.loader import load  # noqa: E402

from eval.baselines.common import RetrievalResult  # noqa: E402
from eval.baselines.tfidf_baseline import TfidfChunkRetriever  # noqa: E402
from eval.baselines.vector_baseline import VectorChunkRetriever  # noqa: E402
from eval.baselines.hybrid_baseline import HybridChunkRetriever  # noqa: E402
from eval.baselines.hybrid_refined import HybridRefinedRetriever  # noqa: E402
# scoped_refined is imported lazily — only needed when --systems includes scoped_arc

# ── Paths ─────────────────────────────────────────────────────────

REPORTS_DIR = PROJECT_ROOT / "reports"


def _repo_paths(repo_name: str) -> tuple[Path, Path, Path]:
    """Derive config, tasks, and snapshot paths from repo name."""
    tasks_dir = PROJECT_ROOT / "eval" / "large_repo_tasks" / repo_name
    config_path = tasks_dir / "REPO_CONFIG.json"
    tasks_path = tasks_dir / "tasks.json"
    config = json.loads(config_path.read_text())
    snapshot_dir = PROJECT_ROOT / config["snapshot_dir"]
    return config_path, tasks_path, snapshot_dir

SYSTEM_NAMES = ["tfidf", "vector", "hybrid", "arc", "hybrid_arc"]
# scoped_arc available via --systems scoped_arc but not in default runs

# ── Metric Functions ──────────────────────────────────────────────


_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "and", "or", "not", "no", "but", "if", "its", "it", "this", "that",
    "via", "into", "than", "has", "have", "had", "do", "does", "did",
    "then", "so", "up", "out", "all", "each", "every", "both", "more",
})


def _fact_terms(fact: str) -> list[str]:
    """Extract significant terms from a fact for matching against code text."""
    return [w for w in fact.lower().split() if len(w) > 2 and w not in _STOPWORDS]


def _term_in_text(term: str, text_lower: str) -> bool:
    """Check if term appears in text as substring (handles underscores, slashes)."""
    return term in text_lower


def _fact_coverage(fact: str, text_lower: str) -> float:
    """Fraction of a fact's significant terms found in text."""
    terms = _fact_terms(fact)
    if not terms:
        return 1.0
    return sum(1 for t in terms if _term_in_text(t, text_lower)) / len(terms)


# A fact is "found" if this fraction of its terms appear in the text
_FACT_THRESHOLD = 0.5


def _relevance_score(text: str, facts: list[str]) -> float:
    """Fraction of required_facts covered by text (partial term overlap)."""
    if not facts:
        return 0.0
    text_lower = text.lower()
    found = sum(1 for f in facts if _fact_coverage(f, text_lower) >= _FACT_THRESHOLD)
    return found / len(facts)


def precision_at_k(texts: list[str], facts: list[str], k: int) -> float:
    top = texts[:k]
    if not top:
        return 0.0
    return sum(1 for t in top if _relevance_score(t, facts) > 0) / len(top)


def recall_at_k(texts: list[str], facts: list[str], k: int) -> float:
    if not facts:
        return 0.0
    combined = " ".join(texts[:k]).lower()
    found = sum(1 for f in facts if _fact_coverage(f, combined) >= _FACT_THRESHOLD)
    return found / len(facts)


def context_precision_keywords(texts: list[str], keywords: list[str], k: int) -> float:
    """Fraction of top-k texts containing at least one relevant keyword."""
    top = texts[:k]
    if not top:
        return 0.0
    kw_lower = {kw.lower() for kw in keywords}
    relevant = 0
    for t in top:
        t_lower = t.lower()
        if any(kw in t_lower for kw in kw_lower):
            relevant += 1
    return relevant / len(top)


def context_recall_keywords(texts: list[str], keywords: list[str], k: int) -> float:
    """Fraction of keywords found in combined top-k texts."""
    if not keywords:
        return 0.0
    combined = " ".join(texts[:k]).lower()
    return sum(1 for kw in keywords if kw.lower() in combined) / len(keywords)


def token_efficiency(loaded_tokens: int, total_tokens: int) -> float:
    if total_tokens == 0:
        return 1.0
    return 1.0 - loaded_tokens / total_tokens


def evidence_traceability(result: RetrievalResult) -> float:
    return 1.0 if result.has_provenance else 0.0


def evidence_usability(result: RetrievalResult) -> float:
    """Fraction of items with concrete file path + line span."""
    if not result.metadata:
        return 0.0
    return sum(
        1 for m in result.metadata if m.get("source_file") and m.get("source_span")
    ) / len(result.metadata)


def debuggability_score(result: RetrievalResult) -> float:
    """Composite: 0.4*evidence_usability + 0.3*file_diversity + 0.3*span_specificity."""
    if not result.metadata or not result.texts:
        return 0.0
    n = len(result.metadata)
    eu = evidence_usability(result)
    files = {m.get("source_file") for m in result.metadata if m.get("source_file")}
    file_div = len(files) / n
    spans = sum(1 for m in result.metadata if m.get("source_span"))
    return 0.4 * eu + 0.3 * file_div + 0.3 * (spans / n)


def cohens_d(group_a: list[float], group_b: list[float]) -> float:
    if len(group_a) < 2 or len(group_b) < 2:
        return 0.0
    import numpy as np
    a = np.array(group_a, dtype=np.float64)
    b = np.array(group_b, dtype=np.float64)
    na, nb = len(a), len(b)
    var_a = float(np.var(a, ddof=1))
    var_b = float(np.var(b, ddof=1))
    pooled_sd = math.sqrt(((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2))
    if pooled_sd == 0:
        return 0.0
    return float((np.mean(b) - np.mean(a)) / pooled_sd)


# ── Task Scoring ──────────────────────────────────────────────────


@dataclass
class TaskScore:
    task_id: str
    category: str
    difficulty: str
    requires_cross_file: bool
    system: str
    context_precision: float = 0.0
    context_recall: float = 0.0
    keyword_precision: float = 0.0
    keyword_recall: float = 0.0
    token_efficiency: float = 0.0
    evidence_traceability: float = 0.0
    loaded_tokens: int = 0
    total_tokens: int = 0
    evidence_usability: float = 0.0
    debuggability: float = 0.0
    # RAGAS scores (populated only in ragas mode)
    ragas_precision: float = 0.0
    ragas_recall: float = 0.0
    ragas_faithfulness: float = 0.0
    ragas_relevancy: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def score_result(
    task: dict, system_name: str, result: RetrievalResult, top_k: int = 10,
) -> TaskScore:
    """Score a retrieval result against task ground truth."""
    facts = task["required_facts"]
    keywords = task["relevant_keywords"]

    return TaskScore(
        task_id=task["id"],
        category=task["category"],
        difficulty=task["difficulty"],
        requires_cross_file=task["requires_cross_file"],
        system=system_name,
        context_precision=precision_at_k(result.texts, facts, top_k),
        context_recall=recall_at_k(result.texts, facts, top_k),
        keyword_precision=context_precision_keywords(result.texts, keywords, top_k),
        keyword_recall=context_recall_keywords(result.texts, keywords, top_k),
        token_efficiency=token_efficiency(result.loaded_tokens, result.total_tokens),
        evidence_traceability=evidence_traceability(result),
        evidence_usability=evidence_usability(result),
        debuggability=debuggability_score(result),
        loaded_tokens=result.loaded_tokens,
        total_tokens=result.total_tokens,
    )


# ── ARC Retrieval ─────────────────────────────────────────────────


class ArcRetriever:
    """Full ARC pipeline: build_archive -> load(task=question)."""

    def __init__(self, source_dir: Path, archive_dir: Path, repo_name: str = "fastapi"):
        # Scale up loader limits for large archives (default 12/8 tuned for small)
        import arc.config as arc_config
        arc_config.MAX_FILTERED_CLAIMS = 50
        arc_config.TOP_K_BASE = 30

        print("  Building ARC archive...")
        self.result = build_archive(
            source_dir=source_dir,
            output_dir=archive_dir,
            archive_id=f"arc://benchmark/{repo_name}",
        )
        assert self.result.valid, f"ARC build failed: {self.result.errors}"
        self.archive_path = archive_dir

        # Compute total tokens from all claims
        full_load = load(self.archive_path)
        self.total_tokens = sum(_count_tokens(c.text) for c in full_load.claims)
        self._full_load = full_load

    def query(self, question: str, top_k: int = 10) -> RetrievalResult:
        """Load archive with task-based filtering."""
        loaded = load(self.archive_path, task=question)
        if loaded.rejected:
            return RetrievalResult(total_tokens=self.total_tokens)

        texts = [c.text for c in loaded.claims]
        ids = [c.id for c in loaded.claims]
        # Evidence traceability: claims have evidence pointers
        su_ids = {su.id for su in self._full_load.source_units}
        has_prov = all(
            any(ev.source_unit_id in su_ids for ev in c.evidence)
            for c in loaded.claims
            if c.evidence
        )
        loaded_tokens = sum(_count_tokens(t) for t in texts)

        return RetrievalResult(
            texts=texts,
            ids=ids,
            scores=[],  # ARC doesn't expose per-item scores
            loaded_tokens=loaded_tokens,
            total_tokens=self.total_tokens,
            has_provenance=has_prov,
        )


# ── RAGAS Scoring ─────────────────────────────────────────────────


def _score_ragas(scores: list[TaskScore], tasks: list[dict], results_by_task: dict):
    """Add RAGAS LLM-judged scores to existing TaskScore objects."""
    try:
        from ragas.llms import llm_factory
    except ImportError:
        print("ERROR: ragas not installed. Run: pip install arc-context[eval]")
        return

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    from anthropic import AsyncAnthropic
    import inspect

    # Import metrics (handle multiple ragas versions)
    try:
        from ragas.metrics.collections import (
            AnswerRelevancy as ResponseRelevancy,
            ContextPrecisionWithReference,
            ContextRecall,
            Faithfulness,
        )
    except ImportError:
        from ragas.metrics import (
            Faithfulness,
            LLMContextPrecisionWithReference as ContextPrecisionWithReference,
            LLMContextRecall as ContextRecall,
            ResponseRelevancy,
        )

    # Create LLM (same pattern as test_ragas_eval.py)
    client = AsyncAnthropic()
    llm = llm_factory("claude-haiku-4-5-20251001", provider="anthropic", client=client)
    llm.model_args.pop("top_p", None)
    llm.model_args["max_tokens"] = 4096

    # Optional embeddings
    embeddings = None
    try:
        from ragas.embeddings import HuggingFaceEmbeddings
        embeddings = HuggingFaceEmbeddings(model="sentence-transformers/all-MiniLM-L6-v2")
    except Exception:
        pass

    metrics = {
        "precision": ContextPrecisionWithReference(llm=llm),
        "recall": ContextRecall(llm=llm),
        "faithfulness": Faithfulness(llm=llm),
    }
    if embeddings:
        metrics["relevancy"] = ResponseRelevancy(llm=llm, embeddings=embeddings)

    task_by_id = {t["id"]: t for t in tasks}

    for ts in scores:
        task = task_by_id.get(ts.task_id)
        if not task:
            continue

        result = results_by_task.get((ts.task_id, ts.system))
        if not result or not result.texts:
            continue

        sample = {
            "user_input": task["question"],
            "retrieved_contexts": result.texts,
            "response": " ".join(result.texts[:3]),
            "reference": task["answer"],
        }

        for name, metric in metrics.items():
            try:
                accepted = set(inspect.signature(metric.ascore).parameters.keys()) - {"self"}
                kwargs = {k: v for k, v in sample.items() if k in accepted}
                result_val = metric.score(**kwargs)
                val = result_val.value if hasattr(result_val, "value") else float(result_val)
            except Exception as e:
                print(f"  RAGAS {name} failed for {ts.task_id}/{ts.system}: {e}")
                val = 0.0

            if name == "precision":
                ts.ragas_precision = val
            elif name == "recall":
                ts.ragas_recall = val
            elif name == "faithfulness":
                ts.ragas_faithfulness = val
            elif name == "relevancy":
                ts.ragas_relevancy = val


# ── Report Generation ─────────────────────────────────────────────


def _generate_report(scores: list[TaskScore], mode: str, repo_name: str = "fastapi") -> tuple[dict, str]:
    """Generate JSON report and markdown summary."""
    # Group by system
    by_system: dict[str, list[TaskScore]] = {}
    for s in scores:
        by_system.setdefault(s.system, []).append(s)

    # Per-system means
    system_means = {}
    for sys_name, sys_scores in by_system.items():
        system_means[sys_name] = {
            "context_precision": mean([s.context_precision for s in sys_scores]),
            "context_recall": mean([s.context_recall for s in sys_scores]),
            "keyword_precision": mean([s.keyword_precision for s in sys_scores]),
            "keyword_recall": mean([s.keyword_recall for s in sys_scores]),
            "token_efficiency": mean([s.token_efficiency for s in sys_scores]),
            "evidence_traceability": mean([s.evidence_traceability for s in sys_scores]),
            "evidence_usability": mean([s.evidence_usability for s in sys_scores]),
            "debuggability": mean([s.debuggability for s in sys_scores]),
            "mean_loaded_tokens": mean([s.loaded_tokens for s in sys_scores]),
            "tasks_evaluated": len(sys_scores),
        }
        if mode == "ragas":
            system_means[sys_name].update({
                "ragas_precision": mean([s.ragas_precision for s in sys_scores]),
                "ragas_recall": mean([s.ragas_recall for s in sys_scores]),
                "ragas_faithfulness": mean([s.ragas_faithfulness for s in sys_scores]),
                "ragas_relevancy": mean([s.ragas_relevancy for s in sys_scores]),
            })

    # Per-category breakdown
    by_category: dict[str, dict[str, list[TaskScore]]] = {}
    for s in scores:
        by_category.setdefault(s.category, {}).setdefault(s.system, []).append(s)

    category_means = {}
    for cat, sys_map in by_category.items():
        category_means[cat] = {}
        for sys_name, sys_scores in sys_map.items():
            category_means[cat][sys_name] = {
                "context_recall": mean([s.context_recall for s in sys_scores]),
                "token_efficiency": mean([s.token_efficiency for s in sys_scores]),
                "count": len(sys_scores),
            }

    # Per-difficulty breakdown
    by_difficulty: dict[str, dict[str, list[TaskScore]]] = {}
    for s in scores:
        by_difficulty.setdefault(s.difficulty, {}).setdefault(s.system, []).append(s)

    # Effect sizes: ARC vs each baseline
    effect_sizes = {}
    if "arc" in by_system:
        arc_recalls = [s.context_recall for s in by_system["arc"]]
        for baseline in ["tfidf", "vector", "hybrid"]:
            if baseline in by_system:
                base_recalls = [s.context_recall for s in by_system[baseline]]
                effect_sizes[f"arc_vs_{baseline}_recall"] = cohens_d(base_recalls, arc_recalls)
        # Cross-file subset
        arc_xf = [s.context_recall for s in by_system["arc"] if s.requires_cross_file]
        for baseline in ["tfidf", "vector", "hybrid"]:
            if baseline in by_system:
                base_xf = [s.context_recall for s in by_system[baseline] if s.requires_cross_file]
                effect_sizes[f"arc_vs_{baseline}_crossfile"] = cohens_d(base_xf, arc_xf)

    # Effect sizes: hybrid_arc vs each baseline
    if "hybrid_arc" in by_system:
        harc_recalls = [s.context_recall for s in by_system["hybrid_arc"]]
        for baseline in ["tfidf", "vector", "hybrid", "arc"]:
            if baseline in by_system:
                base_recalls = [s.context_recall for s in by_system[baseline]]
                effect_sizes[f"hybrid_arc_vs_{baseline}_recall"] = cohens_d(base_recalls, harc_recalls)
        # Cross-file subset
        harc_xf = [s.context_recall for s in by_system["hybrid_arc"] if s.requires_cross_file]
        for baseline in ["tfidf", "vector", "hybrid", "arc"]:
            if baseline in by_system:
                base_xf = [s.context_recall for s in by_system[baseline] if s.requires_cross_file]
                effect_sizes[f"hybrid_arc_vs_{baseline}_crossfile"] = cohens_d(base_xf, harc_xf)

    # Effect sizes: scoped_arc vs each baseline
    if "scoped_arc" in by_system:
        sarc_recalls = [s.context_recall for s in by_system["scoped_arc"]]
        for baseline in ["tfidf", "vector", "hybrid", "arc", "hybrid_arc"]:
            if baseline in by_system:
                base_recalls = [s.context_recall for s in by_system[baseline]]
                effect_sizes[f"scoped_arc_vs_{baseline}_recall"] = cohens_d(base_recalls, sarc_recalls)
        # Cross-file subset
        sarc_xf = [s.context_recall for s in by_system["scoped_arc"] if s.requires_cross_file]
        for baseline in ["tfidf", "vector", "hybrid", "arc", "hybrid_arc"]:
            if baseline in by_system:
                base_xf = [s.context_recall for s in by_system[baseline] if s.requires_cross_file]
                effect_sizes[f"scoped_arc_vs_{baseline}_crossfile"] = cohens_d(base_xf, sarc_xf)

    report = {
        "metadata": {
            "mode": mode,
            "tasks_evaluated": len(set(s.task_id for s in scores)),
            "systems": list(by_system.keys()),
        },
        "per_system": system_means,
        "per_category": category_means,
        "effect_sizes": effect_sizes,
        "per_task": [s.to_dict() for s in scores],
    }

    # Markdown summary
    md = _generate_markdown(system_means, category_means, effect_sizes, mode, repo_name=repo_name)
    return report, md


def _generate_markdown(
    system_means: dict, category_means: dict, effect_sizes: dict, mode: str,
    repo_name: str = "fastapi",
) -> str:
    lines = [
        f"# Large-Repo Benchmark Results: {repo_name}",
        "",
        f"**Mode**: {mode}",
        f"**Systems**: {', '.join(system_means.keys())}",
        "",
        "## System Comparison",
        "",
        "| System | Context Precision | Context Recall | Keyword Recall | Token Efficiency | Evidence Traceability | Evidence Usability | Debuggability |",
        "|--------|------------------|----------------|----------------|-----------------|---------------------|-------------------|--------------|",
    ]
    for sys_name, means in system_means.items():
        lines.append(
            f"| {sys_name} | {means['context_precision']:.3f} | {means['context_recall']:.3f} "
            f"| {means['keyword_recall']:.3f} | {means['token_efficiency']:.3f} "
            f"| {means['evidence_traceability']:.3f} "
            f"| {means['evidence_usability']:.3f} "
            f"| {means['debuggability']:.3f} |"
        )

    if mode == "ragas":
        lines.extend([
            "",
            "## RAGAS Scores (LLM-Judged)",
            "",
            "| System | Precision | Recall | Faithfulness | Relevancy |",
            "|--------|-----------|--------|-------------|-----------|",
        ])
        for sys_name, means in system_means.items():
            lines.append(
                f"| {sys_name} | {means.get('ragas_precision', 0):.3f} "
                f"| {means.get('ragas_recall', 0):.3f} "
                f"| {means.get('ragas_faithfulness', 0):.3f} "
                f"| {means.get('ragas_relevancy', 0):.3f} |"
            )

    lines.extend([
        "",
        "## Per-Category Breakdown (Context Recall)",
        "",
        "| Category | " + " | ".join(system_means.keys()) + " |",
        "|----------|" + "|".join(["------"] * len(system_means)) + "|",
    ])
    for cat, sys_map in sorted(category_means.items()):
        row = f"| {cat} "
        for sys_name in system_means:
            val = sys_map.get(sys_name, {}).get("context_recall", 0.0)
            row += f"| {val:.3f} "
        row += "|"
        lines.append(row)

    if effect_sizes:
        lines.extend([
            "",
            "## Effect Sizes (Cohen's d: ARC vs Baselines)",
            "",
            "| Comparison | Cohen's d | Interpretation |",
            "|-----------|-----------|---------------|",
        ])
        for name, d in effect_sizes.items():
            interp = (
                "negligible" if abs(d) < 0.2
                else "small" if abs(d) < 0.5
                else "medium" if abs(d) < 0.8
                else "large"
            )
            lines.append(f"| {name} | {d:.3f} | {interp} |")

    lines.extend(["", "---", "*Generated by ARC large-repo benchmark*"])
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Large-repo benchmark: ARC vs baselines"
    )
    parser.add_argument(
        "--mode", choices=["smoke", "full", "ragas"], default="smoke",
        help="smoke=5 tasks lexical, full=30 tasks lexical, ragas=30 tasks + LLM judge",
    )
    parser.add_argument(
        "--repo", default="fastapi",
        help="Repository to benchmark (e.g., fastapi, django)",
    )
    parser.add_argument(
        "--systems", nargs="+", default=SYSTEM_NAMES,
        help="Which systems to benchmark (default: all)",
    )
    parser.add_argument(
        "--top-k", type=int, default=10,
        help="Top-k results to evaluate (default: 10)",
    )
    parser.add_argument(
        "--categories", nargs="+", default=None,
        help="Filter to specific task categories",
    )
    args = parser.parse_args()

    repo_config_path, tasks_path, snapshot_dir = _repo_paths(args.repo)

    # 1. Ensure snapshot exists
    if not snapshot_dir.exists():
        print(f"{args.repo} snapshot not found. Running setup...")
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "setup_fastapi_snapshot.py"),
             "--config", str(repo_config_path)],
            check=True,
        )
    if not snapshot_dir.exists():
        print("ERROR: Snapshot setup failed")
        sys.exit(1)

    # 2. Load tasks
    tasks_data = json.loads(tasks_path.read_text())
    tasks = tasks_data["tasks"]
    if args.mode == "smoke":
        tasks = [t for t in tasks if t.get("smoke_task")]
        print(f"Smoke mode: {len(tasks)} tasks")
    else:
        print(f"Full mode: {len(tasks)} tasks")

    if args.categories:
        tasks = [t for t in tasks if t["category"] in args.categories]
        print(f"Category filter: {len(tasks)} tasks in {args.categories}")

    # 3. Build retrieval systems
    print("\nBuilding retrieval indices...")
    systems: dict[str, object] = {}
    t0 = time.time()

    if "tfidf" in args.systems:
        print("  [A] TF-IDF chunks...")
        systems["tfidf"] = TfidfChunkRetriever(snapshot_dir)

    if "vector" in args.systems:
        print("  [B] Vector chunks...")
        systems["vector"] = VectorChunkRetriever(snapshot_dir)

    if "hybrid" in args.systems:
        print("  [C] Hybrid chunks...")
        systems["hybrid"] = HybridChunkRetriever(snapshot_dir)

    if "arc" in args.systems:
        print("  [D] Full ARC...")
        arc_dir = REPORTS_DIR / f"{args.repo}.arc"
        arc_dir.mkdir(parents=True, exist_ok=True)
        systems["arc"] = ArcRetriever(snapshot_dir, arc_dir, repo_name=args.repo)

    if "hybrid_arc" in args.systems:
        print("  [E] Hybrid + ARC refinement...")
        systems["hybrid_arc"] = HybridRefinedRetriever(snapshot_dir, retrieval_k=30)

    if "scoped_arc" in args.systems:
        from eval.baselines.scoped_refined import ScopedRefinedRetriever  # noqa: E402
        print("  [F] Scoped + ARC refinement...")
        systems["scoped_arc"] = ScopedRefinedRetriever(snapshot_dir)

    build_time = time.time() - t0
    print(f"  Index build time: {build_time:.1f}s")

    # 4. Run evaluations
    print(f"\nEvaluating {len(tasks)} tasks x {len(systems)} systems...")
    all_scores: list[TaskScore] = []
    results_by_task: dict[tuple[str, str], RetrievalResult] = {}

    for i, task in enumerate(tasks):
        print(f"  [{i+1}/{len(tasks)}] {task['id']}: {task['question'][:60]}...")
        for sys_name, system in systems.items():
            result = system.query(task["question"], top_k=args.top_k)
            results_by_task[(task["id"], sys_name)] = result
            ts = score_result(task, sys_name, result, top_k=args.top_k)
            all_scores.append(ts)

    # 5. RAGAS scoring if requested
    if args.mode == "ragas":
        print("\nRunning RAGAS evaluation (this may take a few minutes)...")
        _score_ragas(all_scores, tasks, results_by_task)

    # 6. Generate reports
    print("\nGenerating reports...")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report, md = _generate_report(all_scores, args.mode, repo_name=args.repo)
    report["metadata"]["build_time_seconds"] = round(build_time, 1)
    report["metadata"]["repo"] = args.repo

    json_path = REPORTS_DIR / f"large-repo-results-{args.repo}.json"
    json_path.write_text(json.dumps(report, indent=2))

    md_path = REPORTS_DIR / f"large-repo-summary-{args.repo}.md"
    md_path.write_text(md)

    print("\nResults written to:")
    print(f"  {json_path}")
    print(f"  {md_path}")

    # Print summary
    print(f"\n{'='*60}")
    print(md)


if __name__ == "__main__":
    main()
