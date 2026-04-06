"""LLM-assisted claim extraction — send full files for comprehensive claims."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Optional

from .models import Claim, EvidencePointer, Resource, TextUnit, _generate_id

logger = logging.getLogger(__name__)

_PROMPT = """\
You are extracting factual claims from source code for a verification system.
Given this source file, produce atomic claims — one specific, verifiable fact per line.

Focus on:
- What exceptions are caught and what happens (return values, error messages, status codes)
- What functions call what other functions
- What gets returned in error cases vs success cases
- What external libraries or modules are used and for what
- What data flows between functions
- What algorithms or data structures are used
- What configuration values or constants control behavior

Do NOT produce:
- General descriptions or summaries ("this is a Python file")
- Opinions about code quality
- Obvious statements from import lines alone

Format: one claim per line, prefixed with the line range it refers to.
Example:
[15-22] sha256_digest takes bytes input and returns SHA-256 hex digest using hashlib.sha256
[45-60] verify_archive catches DatabaseError and returns VerificationResult with valid=False
[80-95] load function returns rejected=True when archive file is not a valid SQLite database

File: {file_path} ({total_lines} lines)

```
{code}
```
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


def _call_llm(prompt: str, url: str, model: str, headers: dict, timeout: float = 15.0) -> Optional[str]:
    """Make one LLM API call. Returns response text or None."""
    if "anthropic" in url:
        body = json.dumps({
            "model": model,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
    else:
        body = json.dumps({
            "model": model,
            "max_tokens": 2000,
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
        logger.warning("LLM call failed for prompt (%d chars): %s", len(prompt), e)
        return None


def _parse_claims_with_lines(response: str) -> list[tuple[str, Optional[tuple[int, int]]]]:
    """Parse claims with optional line references from LLM response.

    Returns list of (claim_text, (start_line, end_line) or None).
    """
    results = []
    for line in response.strip().splitlines():
        line = line.strip()
        if not line or len(line) < 15:
            continue
        # Strip list markers
        line = re.sub(r"^[-*\d.)\]]+\s*", "", line)
        # Try to parse [start-end] prefix
        m = re.match(r"\[(\d+)[-–](\d+)\]\s*(.*)", line)
        if m:
            start, end, text = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            if text and len(text) > 10:
                results.append((text, (start, end)))
        else:
            # No line reference — keep as file-level claim
            if len(line) > 15:
                results.append((line, None))
    return results


def extract_claims_with_llm(
    text_units: list[TextUnit],
    resources: list[Resource],
    existing_claim_ids: set[str],
    timeout: float = 15.0,
    confirm: bool = True,
) -> list[Claim]:
    """Extract claims by sending full files to LLM.

    Sends each source file (not individual chunks) so the LLM can see
    error handling paths, cross-function data flow, and call chains.
    """
    api_config = _get_api_config()
    if api_config is None:
        raise RuntimeError(
            "No API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
        )

    url, key, model, headers = api_config

    # Group text units by resource to reconstruct files
    res_by_id = {r.id: r for r in resources}
    files_content: dict[str, tuple[str, str, list[TextUnit]]] = {}  # res_id → (path, content, units)

    for tu in text_units:
        if tu.kind not in ("function", "section", "paragraph"):
            continue
        res = res_by_id.get(tu.resource_id)
        if not res:
            continue
        loc = res.locator
        if not loc.endswith(".py"):  # extend for other langs as needed
            continue
        if tu.resource_id not in files_content:
            files_content[tu.resource_id] = (loc, "", [])
        _, _, units = files_content[tu.resource_id]
        units.append(tu)

    # Reconstruct file content from units (sorted by span)
    file_texts: list[tuple[str, str, list[TextUnit]]] = []
    for res_id, (loc, _, units) in files_content.items():
        units.sort(key=lambda u: u.span[0])
        content = "\n\n".join(u.content for u in units)
        total_lines = max((u.span[1] for u in units), default=0)
        file_texts.append((loc, content, units))

    est_calls = len(file_texts)
    provider = "Anthropic" if "anthropic" in url else "OpenAI"

    if confirm:
        print(f"\nLLM extraction: {est_calls} files to process", file=sys.stderr)
        print(f"  Provider: {provider} ({model})", file=sys.stderr)
        print(f"  Estimated cost: ${est_calls * 0.003:.2f}", file=sys.stderr)
        resp = input("  Continue? [y/n] ")
        if resp.lower() not in ("y", "yes"):
            print("  Skipped.", file=sys.stderr)
            return []

    claims: list[Claim] = []
    skipped = 0

    for i, (file_path, content, units) in enumerate(file_texts):
        total_lines = max((u.span[1] for u in units), default=0)

        # For files over 500 lines, split at class boundaries
        if total_lines > 500:
            sections = _split_at_classes(content, file_path)
        else:
            sections = [(content, file_path, 1, total_lines)]

        for section_content, section_path, sec_start, sec_end in sections:
            prompt = _PROMPT.format(
                file_path=section_path,
                total_lines=sec_end - sec_start + 1,
                code=section_content[:8000],
            )

            response = _call_llm(prompt, url, model, headers, timeout=timeout)
            if response is None:
                skipped += 1
                continue

            parsed = _parse_claims_with_lines(response)

            # Find the best matching text unit for each claim's line range
            for claim_text, line_span in parsed:
                # Find text unit containing the line span
                best_tu = None
                if line_span:
                    for tu in units:
                        if tu.span[0] <= line_span[0] and tu.span[1] >= line_span[1]:
                            best_tu = tu
                            break
                    if not best_tu:
                        # Closest unit
                        for tu in units:
                            if tu.span[0] <= line_span[0] <= tu.span[1]:
                                best_tu = tu
                                break
                if not best_tu and units:
                    best_tu = units[0]

                ev_span = line_span or (best_tu.span if best_tu else (1, total_lines))

                claims.append(Claim(
                    id=_generate_id(f"llm:{file_path}:{claim_text}"),
                    text=claim_text,
                    kind="fact",
                    claim_type="observation",
                    source="llm-extracted",
                    evidence=[EvidencePointer(
                        source_unit_id=best_tu.id if best_tu else "",
                        span=ev_span,
                        weight=1.0,
                    )],
                    confidence=0.75,
                    status="observed",
                    derived_from=best_tu.id if best_tu else "",
                ))

        if (i + 1) % 5 == 0:
            logger.info("LLM extraction: %d/%d files", i + 1, est_calls)

    if skipped:
        logger.warning("LLM extraction: %d/%d sections skipped", skipped, est_calls)

    logger.info("LLM extraction: %d claims from %d files", len(claims), est_calls)
    return claims


def _split_at_classes(content: str, file_path: str) -> list[tuple[str, str, int, int]]:
    """Split large file content at class boundaries."""
    lines = content.splitlines()
    sections = []
    current_start = 0
    current_lines = []

    for i, line in enumerate(lines):
        if re.match(r"^class\s+\w+", line) and current_lines:
            sections.append((
                "\n".join(current_lines),
                file_path,
                current_start + 1,
                current_start + len(current_lines),
            ))
            current_start = i
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((
            "\n".join(current_lines),
            file_path,
            current_start + 1,
            current_start + len(current_lines),
        ))

    return sections if sections else [(content, file_path, 1, len(lines))]
