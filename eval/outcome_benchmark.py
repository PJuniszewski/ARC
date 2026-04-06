#!/usr/bin/env python3
"""Outcome benchmark: does ARC context improve agent answer quality?

Compares two retrieval strategies on 15 code understanding tasks:
  - WITH ARC: arc load --task "question" → typed claims with evidence
  - WITHOUT ARC: naive file search (grep + read) → raw text chunks

Measures:
  - Fact recall: fraction of ground-truth facts found in context
  - Noise ratio: fraction of context that's irrelevant
  - Token count: how much context each strategy produces
  - Hallucination proxy: does context contain contradictory/misleading info

Optional (with ANTHROPIC_API_KEY):
  - LLM judge: ask Claude to answer each question with each context, score correctness

Usage:
  python3 eval/outcome_benchmark.py              # deterministic mode
  ANTHROPIC_API_KEY=... python3 eval/outcome_benchmark.py  # + LLM judge
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Task definitions: question + ground truth facts + relevant files
# ---------------------------------------------------------------------------

# Facts are simple strings describing what must be conveyed.
# With API key: LLM judges semantically ("does context contain this fact?")
# Without API key: substring matching (first item in list = canonical, rest = variants)
TASKS = [
    {
        "id": "hash-algo",
        "question": "What hash algorithm does the content-addressed storage use?",
        "facts": [
            "The system uses SHA-256 hashing",
            "hashlib.sha256 is used for computing digests",
        ],
        "files": ["cas.py"],
    },
    {
        "id": "conflict-detect",
        "question": "How does arc merge detect conflicting decisions between agents?",
        "facts": [
            "Cosine similarity is used to compare decisions",
            "TF-IDF embeddings are used for conflict detection",
            "There is a similarity threshold for flagging conflicts",
        ],
        "files": ["merge.py"],
    },
    {
        "id": "claim-types",
        "question": "What claim types does ARC support?",
        "facts": [
            "observation type exists",
            "decision type exists",
            "uncertainty type exists",
            "dependency type exists",
            "conflict type exists",
        ],
        "files": ["models.py"],
    },
    {
        "id": "project-detect",
        "question": "How does arc init detect what kind of project it's scanning?",
        "facts": [
            "Checks for pyproject.toml to detect Python projects",
            "Checks for package.json to detect JavaScript projects",
            "Checks for Cargo.toml to detect Rust projects",
            "Uses marker files to determine project type",
        ],
        "files": ["init.py"],
    },
    {
        "id": "archive-format",
        "question": "What file format does a .arc archive use internally?",
        "facts": [
            "Archives use SQLite as the storage format",
            "There is a blobs table for content-addressed data",
            "There is a meta table for manifest and metadata",
        ],
        "files": ["cas.py"],
    },
    {
        "id": "merge-dedup",
        "question": "How are duplicate claims handled when merging two archives?",
        "facts": [
            "Claims are compared by text content for deduplication",
            "Claims from different sources with same text are kept as confirmations",
        ],
        "files": ["merge.py"],
    },
    {
        "id": "corrupt-handling",
        "question": "What happens when you try to load a corrupt .arc file?",
        "facts": [
            "Loading a corrupt file results in a rejected archive",
            "DatabaseError or similar exception is caught",
            "The verification result indicates the archive is not valid",
        ],
        "files": ["loader.py"],
    },
    {
        "id": "snapshot-select",
        "question": "How does arc snapshot select which claims to include?",
        "facts": [
            "Takes the last N claims",
            "Claims are sorted by timestamp",
            "Claims can be filtered by type or source",
        ],
        "files": ["snapshot.py"],
    },
    {
        "id": "embedder-models",
        "question": "What embedding models does ARC support?",
        "facts": [
            "Supports sentence-transformers for neural embeddings",
            "Supports TF-IDF as a fallback embedder",
            "Falls back to TF-IDF when sentence-transformers is not available",
        ],
        "files": ["embeddings.py"],
    },
    {
        "id": "merkle-root",
        "question": "How is the manifest root digest computed?",
        "facts": [
            "Uses SHA-256 to hash the manifest content",
            "The root_digest field is excluded from its own computation",
            "JSON is serialized with sorted keys for determinism",
        ],
        "files": ["models.py", "cas.py"],
    },
    {
        "id": "evidence-trace",
        "question": "How does a claim trace back to source code?",
        "facts": [
            "Claims have EvidencePointer objects linking to source units",
            "Evidence includes source_unit_id to identify the code chunk",
            "Evidence includes line span information",
            "Source units link to resources via resource_id",
        ],
        "files": ["models.py"],
    },
    {
        "id": "init-json",
        "question": "What does arc init --json output?",
        "facts": [
            "JSON output includes top claims from the archive",
            "JSON output includes the project name",
            "Output is structured JSON for agent consumption",
        ],
        "files": ["cli.py", "init.py"],
    },
    {
        "id": "builder-stages",
        "question": "What are the stages of the ARC build pipeline?",
        "facts": [
            "Pipeline includes ingestion of source files",
            "Pipeline includes chunking into text units",
            "Pipeline includes claim extraction",
            "Pipeline includes deduplication",
            "Pipeline includes embedding and indexing",
            "Pipeline includes assembly into archive format",
        ],
        "files": ["builder.py"],
    },
    {
        "id": "selective-load",
        "question": "How does arc load filter claims by type and source?",
        "facts": [
            "Can filter claims by claim_type",
            "Can filter claims by source agent",
            "Supports task-based semantic filtering",
        ],
        "files": ["loader.py", "cli.py"],
    },
    {
        "id": "arcconfig",
        "question": "What does .arcconfig contain and how is it used?",
        "facts": [
            "Config file uses TOML format",
            "Contains project name and type",
            "Contains build settings like scan directories",
            "Contains embeddings configuration",
        ],
        "files": ["init.py", "cli.py"],
    },
]


# ---------------------------------------------------------------------------
# Retrieval strategies
# ---------------------------------------------------------------------------

def retrieve_with_arc(archive_path: str, question: str) -> tuple[str, int]:
    """Retrieve context using ARC claims. Returns (context_text, claim_count)."""
    from arc.loader import load
    loaded = load(archive_path, task=question)
    if loaded.rejected:
        return "", 0

    parts = []
    for c in loaded.claims:
        source_hint = ""
        if c.evidence:
            su_id = c.evidence[0].source_unit_id
            su = next((s for s in loaded.source_units if s.id == su_id), None)
            if su:
                res = next((r for r in loaded.resources if r.id == su.resource_id), None)
                if res:
                    source_hint = f" [{res.locator}:{su.span[0]}-{su.span[1]}]"
        parts.append(f"[{c.claim_type.upper()}]{source_hint} {c.text}")

    context = "\n".join(parts)
    claim_texts = [c.text for c in loaded.claims]
    return context, len(loaded.claims), claim_texts


def retrieve_with_arc_raw(archive_path: str, question: str) -> tuple[str, int]:
    """Retrieve context using ARC source-unit search (vector-indexed chunks).

    This uses ARC's embedding index on raw source code, not extracted claims.
    Shows the value of ARC's retrieval infrastructure even without claim extraction.
    """
    from arc.loader import load
    from arc.embeddings import get_embedder, VectorStore

    loaded = load(archive_path)
    if loaded.rejected or not loaded.vector_store:
        return "", 0

    # Build vector index over source units
    source_units = loaded.source_units
    if not source_units:
        return "", 0

    embedder = get_embedder(dimensions=256, force_tfidf=True)
    texts = [tu.content for tu in source_units]
    embedder.fit(texts)

    store = VectorStore(index_info=embedder.get_index_info())
    for tu in source_units:
        vec = embedder.embed(tu.content)
        store.add(tu.id, vec, tu.content, {"resource_id": tu.resource_id})

    query_vec = embedder.embed(question)
    results = store.search(query_vec, top_k=10)

    su_by_id = {tu.id: tu for tu in source_units}
    res_by_id = {r.id: r for r in loaded.resources}
    parts = []
    for tu_id, score, _ in results:
        tu = su_by_id.get(tu_id)
        if not tu:
            continue
        res = res_by_id.get(tu.resource_id)
        loc = res.locator if res else "?"
        parts.append(f"[{loc}:{tu.span[0]}-{tu.span[1]}]\n{tu.content}")

    context = "\n\n".join(parts)
    return context, len(results)


def retrieve_without_arc(source_dir: str, question: str, relevant_files: list[str]) -> tuple[str, int]:
    """Retrieve context via naive grep. Returns (context_text, chunk_count)."""
    # Extract keywords from question
    stop = {"what", "how", "does", "the", "is", "are", "when", "which", "that", "this",
            "from", "with", "for", "and", "use", "used", "using"}
    words = [w.lower() for w in re.findall(r"\b\w{3,}\b", question.lower()) if w.lower() not in stop]

    src = Path(source_dir)
    chunks = []
    for f in src.rglob("*.py"):
        try:
            content = f.read_text(errors="replace")
        except OSError:
            continue
        lines = content.splitlines()
        # Search for keyword matches in chunks of 20 lines
        for i in range(0, len(lines), 10):
            chunk = "\n".join(lines[i:i + 20])
            chunk_lower = chunk.lower()
            hits = sum(1 for w in words if w in chunk_lower)
            if hits >= 2:
                rel_path = f.relative_to(src)
                chunks.append((hits, f"[{rel_path}:{i+1}-{i+20}]\n{chunk}"))

    # Sort by relevance, take top 12 (same as ARC's default)
    chunks.sort(key=lambda x: -x[0])
    chunks = chunks[:12]

    context = "\n\n".join(text for _, text in chunks)
    return context, len(chunks)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    task_id: str
    question: str
    # Claims-based ARC
    arc_fact_recall: float = 0.0
    arc_tokens: int = 0
    arc_claims: int = 0
    arc_noise_ratio: float = 0.0
    # ARC vector search on source chunks
    arc_raw_fact_recall: float = 0.0
    arc_raw_tokens: int = 0
    arc_raw_chunks: int = 0
    # Naive grep (no ARC)
    raw_fact_recall: float = 0.0
    raw_tokens: int = 0
    raw_chunks: int = 0
    raw_noise_ratio: float = 0.0
    # LLM judge (optional)
    arc_correct: bool | None = None
    raw_correct: bool | None = None
    arc_hallucinations: int | None = None
    raw_hallucinations: int | None = None


def score_fact_recall(context: str, facts: list, claim_texts: list[str] | None = None) -> float:
    """Fraction of ground-truth facts found in context.

    Two modes:
    - With ANTHROPIC_API_KEY: LLM judge per fact. Semantic matching.
    - Without: substring matching. Deterministic fallback.

    Args:
        context: Full context as single string (for substring fallback).
        facts: List of fact descriptions.
        claim_texts: Individual claim texts (for LLM judge pre-filtering).
    """
    if not facts:
        return 0.0
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key and claim_texts:
        return _score_with_llm_judge(claim_texts, facts, api_key)
    return _score_with_substring(context, facts)


def _score_with_substring(context: str, facts: list) -> float:
    """Substring matching with variant lists. Deterministic fallback."""
    ctx_lower = context.lower()
    found = 0
    for fact in facts:
        if isinstance(fact, list):
            if any(v.lower() in ctx_lower for v in fact):
                found += 1
        else:
            if fact.lower() in ctx_lower:
                found += 1
    return found / len(facts)


_JUDGE_CACHE: dict[tuple[str, str], bool] = {}


def _score_with_llm_judge(claim_texts: list[str], facts: list, api_key: str) -> float:
    """LLM judge: pre-filter to top 10 claims per fact, then judge semantically."""
    import urllib.request

    found = 0
    for fact in facts:
        fact_desc = fact[0] if isinstance(fact, list) else fact

        # Pre-filter: keyword overlap + substring matching
        fact_lower = fact_desc.lower()
        # Extract meaningful tokens (keep hyphenated and dotted terms intact)
        fact_tokens = set(re.findall(r"[\w][\w.-]+", fact_lower))
        fact_tokens = {t for t in fact_tokens if len(t) > 2}

        scored_claims = []
        for claim in claim_texts:
            claim_lower = claim.lower()
            # Word-level overlap
            word_hits = sum(1 for t in fact_tokens if t in claim_lower)
            # Substring match for multi-word terms
            substr_hits = sum(1 for t in fact_tokens if len(t) > 4 and t in claim_lower)
            score = word_hits + substr_hits * 2
            if score > 0:
                scored_claims.append((score, claim))
        scored_claims.sort(key=lambda x: -x[0])
        top_claims = [c for _, c in scored_claims[:15]]

        if not top_claims:
            continue

        # Cache
        cache_key = (fact_desc, str(hash("|".join(top_claims))))
        if cache_key in _JUDGE_CACHE:
            if _JUDGE_CACHE[cache_key]:
                found += 1
            continue

        relevant_context = "\n".join(f"- {c}" for c in top_claims)
        prompt = (
            f"Does any of these claims contain or convey this fact?\n\n"
            f"Fact: {fact_desc}\n\n"
            f"Claims:\n{relevant_context}\n\n"
            f"Answer YES or NO."
        )

        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 5,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                answer = data.get("content", [{}])[0].get("text", "").strip().upper()
                hit = answer.startswith("YES")
                _JUDGE_CACHE[cache_key] = hit
                if hit:
                    found += 1
        except Exception:
            # Fallback: check if any top claim contains the fact description
            hit = any(fact_desc.lower() in c.lower() for c in top_claims)
            _JUDGE_CACHE[cache_key] = hit
            if hit:
                found += 1

    return found / len(facts)


def score_noise_ratio(context: str, relevant_files: list[str]) -> float:
    """Fraction of context lines that don't reference relevant files."""
    if not context.strip():
        return 1.0
    lines = context.strip().splitlines()
    relevant = 0
    for line in lines:
        for f in relevant_files:
            if f in line:
                relevant += 1
                break
    return 1.0 - (relevant / len(lines)) if lines else 1.0


def estimate_tokens(text: str) -> int:
    """Rough token estimate (1 token ≈ 4 chars)."""
    return len(text) // 4


# ---------------------------------------------------------------------------
# LLM judge (optional)
# ---------------------------------------------------------------------------

def llm_judge(question: str, context: str, facts: list[str], api_key: str) -> tuple[bool, int]:
    """Ask LLM to answer based on context, check correctness and hallucinations.

    Returns (is_correct, hallucination_count).
    """
    import urllib.request
    import urllib.error

    prompt = (
        f"Based ONLY on the context below, answer this question:\n\n"
        f"Question: {question}\n\n"
        f"Context:\n{context[:3000]}\n\n"
        f"Answer concisely. If the context doesn't contain enough information, say 'insufficient context'."
    )

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            answer = data.get("content", [{}])[0].get("text", "")
    except Exception:
        return None, None

    # Check correctness: does the answer contain the key facts?
    answer_lower = answer.lower()
    fact_hits = sum(1 for f in facts if f.lower() in answer_lower)
    is_correct = fact_hits >= len(facts) * 0.5  # at least half the facts

    # Check hallucinations: claims not supported by context
    # Simple heuristic: sentences in answer not grounded in context
    hallucinations = 0
    for sentence in re.split(r"[.!?]\s", answer):
        sentence = sentence.strip()
        if len(sentence) < 15:
            continue
        # Check if any key phrase from sentence appears in context
        key_words = [w for w in sentence.lower().split() if len(w) > 4]
        if key_words:
            grounded = any(w in context.lower() for w in key_words[:3])
            if not grounded:
                hallucinations += 1

    return is_correct, hallucinations


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_benchmark() -> list[TaskResult]:
    from arc.builder import build_archive

    source_dir = Path(__file__).parent.parent / "src" / "arc"
    if not source_dir.is_dir():
        print(f"ERROR: source directory not found: {source_dir}", file=sys.stderr)
        sys.exit(1)

    # Build ARC archive
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = os.path.join(tmp, "arc.arc")
        print("Building ARC archive from src/arc/ ...", file=sys.stderr)
        t0 = time.monotonic()
        result = build_archive(
            source_dir=str(source_dir),
            output_dir=archive_path,
            archive_id="arc://benchmark",
            force_tfidf=True,
            output_format="sqlite",
        )
        build_time = time.monotonic() - t0
        print(f"  Built: {len(result.claims)} claims, {len(result.resources)} files in {build_time:.1f}s",
              file=sys.stderr)

        if not result.valid:
            print(f"ERROR: build failed: {result.errors}", file=sys.stderr)
            sys.exit(1)

        # Run tasks
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        use_llm = bool(api_key)
        if use_llm:
            print("  LLM judge: enabled (ANTHROPIC_API_KEY found)", file=sys.stderr)
        else:
            print("  LLM judge: disabled (no ANTHROPIC_API_KEY)", file=sys.stderr)

        results = []
        for i, task in enumerate(TASKS, 1):
            print(f"  [{i}/{len(TASKS)}] {task['id']}...", file=sys.stderr, end="", flush=True)

            # Strategy 1: ARC claims
            arc_ctx, arc_claims, arc_claim_texts = retrieve_with_arc(archive_path, task["question"])
            arc_recall = score_fact_recall(arc_ctx, task["facts"], claim_texts=arc_claim_texts)
            arc_noise = score_noise_ratio(arc_ctx, task["files"])
            arc_tokens = estimate_tokens(arc_ctx)

            # Strategy 2: ARC vector search on source chunks
            arc_raw_ctx, arc_raw_chunks = retrieve_with_arc_raw(archive_path, task["question"])
            arc_raw_recall = score_fact_recall(arc_raw_ctx, task["facts"])
            arc_raw_tokens = estimate_tokens(arc_raw_ctx)

            # Strategy 3: Naive grep (no ARC)
            raw_ctx, raw_chunks = retrieve_without_arc(str(source_dir), task["question"], task["files"])
            raw_recall = score_fact_recall(raw_ctx, task["facts"])
            raw_noise = score_noise_ratio(raw_ctx, task["files"])
            raw_tokens = estimate_tokens(raw_ctx)

            tr = TaskResult(
                task_id=task["id"],
                question=task["question"],
                arc_fact_recall=arc_recall,
                arc_tokens=arc_tokens,
                arc_claims=arc_claims,
                arc_noise_ratio=arc_noise,
                arc_raw_fact_recall=arc_raw_recall,
                arc_raw_tokens=arc_raw_tokens,
                arc_raw_chunks=arc_raw_chunks,
                raw_fact_recall=raw_recall,
                raw_tokens=raw_tokens,
                raw_chunks=raw_chunks,
                raw_noise_ratio=raw_noise,
            )

            # Optional LLM judge
            if use_llm and arc_ctx and raw_ctx:
                arc_correct, arc_hall = llm_judge(task["question"], arc_ctx, task["facts"], api_key)
                raw_correct, raw_hall = llm_judge(task["question"], raw_ctx, task["facts"], api_key)
                tr.arc_correct = arc_correct
                tr.raw_correct = raw_correct
                tr.arc_hallucinations = arc_hall
                tr.raw_hallucinations = raw_hall

            results.append(tr)
            print(f" claims={arc_recall:.0%} search={arc_raw_recall:.0%} grep={raw_recall:.0%}",
                  file=sys.stderr)

    return results


def print_results(results: list[TaskResult]) -> None:
    """Print results table."""
    use_llm = results[0].arc_correct is not None

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0

    arc_recalls = [r.arc_fact_recall for r in results]
    arc_raw_recalls = [r.arc_raw_fact_recall for r in results]
    raw_recalls = [r.raw_fact_recall for r in results]
    arc_tokens = [r.arc_tokens for r in results]
    arc_raw_tokens = [r.arc_raw_tokens for r in results]
    raw_tokens_list = [r.raw_tokens for r in results if r.raw_tokens > 0]

    print("\n" + "=" * 78)
    print("OUTCOME BENCHMARK: ARC vs Raw Retrieval")
    print("=" * 78)
    print(f"Tasks: {len(results)}")
    print(f"Source: src/arc/ ({sum(1 for _ in Path('src/arc').rglob('*.py'))} Python files)")
    print()
    print("Three strategies:")
    print("  ARC claims  = extracted typed claims with evidence (arc load --task)")
    print("  ARC search  = vector search on source chunks (ARC infra, raw text)")
    print("  Naive grep  = keyword grep on files, no ARC")

    print(f"\n{'Metric':<25} {'ARC claims':>11} {'ARC search':>11} {'Naive grep':>11}")
    print("-" * 60)
    print(f"{'Avg fact recall':<25} {avg(arc_recalls):>10.0%} {avg(arc_raw_recalls):>10.0%} {avg(raw_recalls):>10.0%}")
    print(f"{'Avg tokens':<25} {avg(arc_tokens):>10.0f} {avg(arc_raw_tokens):>10.0f} {avg(raw_tokens_list):>10.0f}")

    if use_llm:
        arc_correct = sum(1 for r in results if r.arc_correct) / len(results)
        raw_correct = sum(1 for r in results if r.raw_correct) / len(results)
        arc_hall = avg([r.arc_hallucinations for r in results if r.arc_hallucinations is not None])
        raw_hall = avg([r.raw_hallucinations for r in results if r.raw_hallucinations is not None])
        print(f"{'LLM correctness':<25} {arc_correct:>10.0%} {'—':>11} {raw_correct:>10.0%}")
        print(f"{'LLM hallucinations':<25} {arc_hall:>10.1f} {'—':>11} {raw_hall:>10.1f}")

    # Per-task
    print(f"\n{'Task':<20} {'Claims':>7} {'Search':>7} {'Grep':>7} {'C tok':>6} {'S tok':>6} {'G tok':>6}")
    print("-" * 62)

    for r in results:
        print(f"{r.task_id:<20} {r.arc_fact_recall:>6.0%} {r.arc_raw_fact_recall:>6.0%} {r.raw_fact_recall:>6.0%}"
              f" {r.arc_tokens:>6} {r.arc_raw_tokens:>6} {r.raw_tokens:>6}")

    # Summary
    claims_wins = sum(
        1 for r in results
        if r.arc_fact_recall >= r.raw_fact_recall
        and r.arc_fact_recall >= r.arc_raw_fact_recall
    )
    search_wins = sum(
        1 for r in results
        if r.arc_raw_fact_recall >= r.raw_fact_recall
        and r.arc_raw_fact_recall >= r.arc_fact_recall
    )
    grep_wins = sum(
        1 for r in results
        if r.raw_fact_recall > r.arc_fact_recall
        and r.raw_fact_recall > r.arc_raw_fact_recall
    )

    print(f"\nBest strategy per task: Claims={claims_wins}, Search={search_wins}, Grep={grep_wins}")

    if avg(raw_tokens_list) > 0:
        claims_saving = 1 - (avg(arc_tokens) / avg(raw_tokens_list))
        search_saving = 1 - (avg(arc_raw_tokens) / avg(raw_tokens_list))
        print(f"Token reduction vs grep: Claims={claims_saving:.0%}, Search={search_saving:.0%}")


if __name__ == "__main__":
    results = run_benchmark()
    print_results(results)
