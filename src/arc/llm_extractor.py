"""LLM-assisted claim extraction — optional, for code chunks that rule-based extraction misses."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Optional

from .models import Claim, EvidencePointer, TextUnit, _generate_id

logger = logging.getLogger(__name__)

_PROMPT = """\
Given this code chunk from file {file_path}, lines {start}-{end}, produce 1-3 factual claims about what this code does.

Each claim must be a complete, self-contained sentence. Include:
- What it handles, catches, returns
- Class names, exception types, return formats
- Key dependencies and algorithms used
- Side effects if any

Be specific. Use actual names from the code.

Code:
```
{code}
```

Return claims as a JSON array of strings. Example:
["sha256_digest takes bytes and returns SHA-256 hex digest", "verify_blob recomputes hash"]
"""


def _get_api_config() -> Optional[tuple[str, str, str, dict]]:
    """Detect available API. Returns (url, key, model, headers) or None."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return (
            "https://api.anthropic.com/v1/messages",
            key,
            "claude-haiku-4-5-20251001",
            {
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
        )
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return (
            "https://api.openai.com/v1/chat/completions",
            key,
            "gpt-4o-mini",
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
    return None


def _call_llm(prompt: str, url: str, model: str, headers: dict, timeout: float = 5.0) -> Optional[str]:
    """Make one LLM API call. Returns response text or None on failure."""
    if "anthropic" in url:
        body = json.dumps({
            "model": model,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
    else:
        body = json.dumps({
            "model": model,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            if "anthropic" in url:
                return data.get("content", [{}])[0].get("text", "")
            else:
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return None


def _parse_claims(response: str) -> list[str]:
    """Parse JSON array of claim strings from LLM response."""
    # Try direct JSON parse
    try:
        arr = json.loads(response)
        if isinstance(arr, list):
            return [s for s in arr if isinstance(s, str) and len(s) > 10]
    except json.JSONDecodeError:
        pass
    # Try to find JSON array in response
    m = re.search(r"\[.*\]", response, re.DOTALL)
    if m:
        try:
            arr = json.loads(m.group())
            if isinstance(arr, list):
                return [s for s in arr if isinstance(s, str) and len(s) > 10]
        except json.JSONDecodeError:
            pass
    # Fallback: split by newlines, treat each as a claim
    lines = [l.strip().lstrip("0123456789.-) ") for l in response.strip().splitlines()]
    return [l for l in lines if len(l) > 15]


def extract_claims_with_llm(
    text_units: list[TextUnit],
    resources: list,
    existing_claim_ids: set[str],
    timeout: float = 5.0,
    confirm: bool = True,
) -> list[Claim]:
    """Extract claims from code chunks using LLM.

    Only processes chunks that produced zero or only signature claims
    from rule-based extraction. Returns new claims tagged source="llm-extracted".

    Args:
        text_units: All text units from the build.
        resources: Resources for file path resolution.
        existing_claim_ids: Set of source_unit_ids that already have claims.
        timeout: Per-call timeout in seconds.
        confirm: If True, print cost estimate and ask for confirmation.

    Returns:
        List of LLM-extracted Claim objects.
    """
    api_config = _get_api_config()
    if api_config is None:
        raise RuntimeError(
            "No API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY. "
            "LLM extraction requires an API key."
        )

    url, key, model, headers = api_config

    # Find chunks that need LLM help (function chunks with few/no rule-extracted claims)
    chunks_to_process = []
    for tu in text_units:
        if tu.kind != "function":
            continue
        if tu.id in existing_claim_ids:
            continue  # already has claims
        chunks_to_process.append(tu)

    if not chunks_to_process:
        logger.info("All chunks have rule-extracted claims. No LLM extraction needed.")
        return []

    # Build resource lookup for file paths
    res_by_id = {r.id: r for r in resources}

    # Cost estimate
    est_calls = len(chunks_to_process)
    est_cost = est_calls * 0.001  # rough: $0.001 per haiku call
    provider = "Anthropic" if "anthropic" in url else "OpenAI"

    if confirm:
        import sys
        print(f"\nLLM extraction: {est_calls} chunks to process", file=sys.stderr)
        print(f"  Provider: {provider} ({model})", file=sys.stderr)
        print(f"  Estimated cost: ${est_cost:.2f}", file=sys.stderr)
        print(f"  Timeout: {timeout}s per chunk", file=sys.stderr)
        resp = input("  Continue? [y/n] ")
        if resp.lower() not in ("y", "yes"):
            print("  Skipped.", file=sys.stderr)
            return []

    claims: list[Claim] = []
    skipped = 0

    for i, tu in enumerate(chunks_to_process):
        res = res_by_id.get(tu.resource_id)
        file_path = res.locator if res else "unknown"

        prompt = _PROMPT.format(
            file_path=file_path,
            start=tu.span[0],
            end=tu.span[1],
            code=tu.content[:2000],  # limit prompt size
        )

        response = _call_llm(prompt, url, model, headers, timeout=timeout)
        if response is None:
            skipped += 1
            continue

        parsed = _parse_claims(response)
        for claim_text in parsed[:3]:
            claims.append(Claim(
                id=_generate_id(f"llm:{tu.id}:{claim_text}"),
                text=claim_text,
                kind="fact",
                claim_type="observation",
                source="llm-extracted",
                evidence=[EvidencePointer(source_unit_id=tu.id, span=tu.span, weight=1.0)],
                confidence=0.75,
                status="observed",
                derived_from=tu.id,
            ))

        if (i + 1) % 10 == 0:
            logger.info("LLM extraction: %d/%d chunks processed", i + 1, est_calls)

    if skipped:
        logger.warning("LLM extraction: %d/%d chunks skipped (timeout/error)", skipped, est_calls)

    logger.info("LLM extraction: %d claims from %d chunks", len(claims), est_calls - skipped)
    return claims
