"""Shared LLM evaluation module — Anthropic Claude as RAGAS judge.

Provides LLM-based scoring for answer relevancy and context precision,
falling back gracefully when the anthropic SDK or API key is unavailable.

Results are cached in results/.llm_cache.json to avoid redundant API calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

_CACHE_PATH = Path(__file__).parent.parent / "results" / ".llm_cache.json"


def _cache_key(func_name: str, question: str, texts: list[str]) -> str:
    """Deterministic hash of function name + inputs.

    Sorts texts so that different orderings of the same claim set produce
    the same key (loader scoring may reorder claims between runs).
    """
    payload = json.dumps(
        {"f": func_name, "q": question, "t": sorted(texts[:20])},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2) + "\n")


def _try_anthropic():
    """Try to import anthropic SDK and verify ANTHROPIC_API_KEY is set.

    Returns an anthropic.Anthropic client or None.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None


def llm_answer_relevancy(
    retrieved_texts: list[str],
    question: str,
    *,
    client=None,
    model: str = "claude-haiku-4-5-20251001",
) -> Optional[float]:
    """Rate how well retrieved context enables answering the question.

    Uses Claude to judge semantic equivalence (e.g. 'hash function' covers
    'algorithm', 'pipeline phases' covers 'stages').

    Returns a float 0.0-1.0, or None if the LLM call fails.
    """
    # Check cache first
    key = _cache_key("relevancy", question, retrieved_texts)
    cache = _load_cache()
    if key in cache:
        return cache[key]

    if client is None:
        client = _try_anthropic()
    if client is None:
        return None

    context_block = "\n---\n".join(retrieved_texts[:20])
    prompt = (
        "You are an evaluation judge. Given retrieved context and a question, "
        "rate from 0.0 to 1.0 how well the context enables answering the question.\n\n"
        "Consider semantic equivalence — for example:\n"
        "- 'hash function' covers 'algorithm'\n"
        "- 'pipeline phases' covers 'stages'\n"
        "- 'content-addressed storage' covers 'CAS'\n\n"
        "A score of 1.0 means the context fully answers the question. "
        "A score of 0.0 means the context is completely irrelevant.\n\n"
        f"Question: {question}\n\n"
        f"Retrieved context:\n{context_block}\n\n"
        "Return ONLY a decimal number between 0.0 and 1.0, nothing else."
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=16,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        match = re.search(r"(\d+\.?\d*)", text)
        score = float(match.group(1)) if match else 0.5
        score = max(0.0, min(1.0, score))

        cache[key] = score
        _save_cache(cache)
        return score
    except Exception:
        return None


def llm_context_precision(
    retrieved_texts: list[str],
    question: str,
    *,
    client=None,
    model: str = "claude-haiku-4-5-20251001",
) -> Optional[float]:
    """LLM-judged context precision: ranked average precision of retrieved claims.

    For each retrieved claim, asks Claude whether it is relevant to answering
    the question. Computes ranked average precision from Yes/No judgments.

    Returns a float 0.0-1.0, or None if the LLM call fails.
    """
    # Check cache first
    key = _cache_key("precision", question, retrieved_texts)
    cache = _load_cache()
    if key in cache:
        return cache[key]

    if client is None:
        client = _try_anthropic()
    if client is None:
        return None

    if not retrieved_texts:
        return 0.0

    claims_block = "\n".join(
        f"{i+1}. {text[:300]}" for i, text in enumerate(retrieved_texts[:20])
    )
    prompt = (
        "You are an evaluation judge. For each numbered claim below, determine "
        "if it is relevant to answering the given question.\n\n"
        "Consider semantic equivalence — a claim about 'hash functions' is relevant "
        "to a question about 'algorithms used', etc.\n\n"
        f"Question: {question}\n\n"
        f"Claims:\n{claims_block}\n\n"
        "For each claim, respond with its number followed by Yes or No. "
        "Format: one per line, e.g.:\n1. Yes\n2. No\n3. Yes"
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=256,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        judgments = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            is_yes = bool(re.search(r"\byes\b", line, re.IGNORECASE))
            judgments.append(1.0 if is_yes else 0.0)

        n = min(len(retrieved_texts), 20)
        while len(judgments) < n:
            judgments.append(0.0)
        judgments = judgments[:n]

        cumulative = 0.0
        num_relevant = 0
        avg_precision = 0.0
        for i, rel in enumerate(judgments):
            if rel > 0:
                num_relevant += 1
                cumulative += rel
                precision_at_i = cumulative / (i + 1)
                avg_precision += precision_at_i

        score = avg_precision / max(num_relevant, 1)

        cache[key] = score
        _save_cache(cache)
        return score
    except Exception:
        return None
