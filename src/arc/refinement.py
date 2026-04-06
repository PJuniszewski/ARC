"""Post-retrieval refinement layer for hybrid chunk results.

Takes raw hybrid retrieval chunks and refines them by:
- Detecting query type and selecting refinement mode
- Keeping top-k raw chunks as passthrough (preserves recall)
- Classifying remaining chunks as code vs docs based on Resource.kind
- Extracting and deduplicating claims from doc chunks
- Keeping code chunks verbatim (extract_claims produces nothing for code)
- Merging with mode-specific weighted scoring
- Building an evidence map for full traceability
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .compressor import _count_tokens, deduplicate_claims
from .extractor import extract_claims
from .models import EvidencePointer, Resource, TextUnit, _generate_id
from .reasoning import has_reasoning


# Legacy constants (kept for backward compatibility; balanced mode uses same values)
CODE_WEIGHT = 1.5
DOCS_WEIGHT = 0.7
MAX_REFINED_ITEMS = 15
DEFAULT_TOKEN_BUDGET = 3700  # Target: >=30% below hybrid's ~5350 tokens
CROSS_FILE_TOKEN_BUDGET = 5000  # Cross-file tasks need more headroom (still 7% below hybrid)
MAX_ITEM_TOKENS = 800  # Truncate any single item beyond this

# Patterns indicating code content
_CODE_PATTERNS = re.compile(
    r"(?:^|\n)\s*(?:def |class |import |from .+ import |async def |@\w+|if __name__)",
)


@dataclass
class RefinementMode:
    """Controls refinement behavior based on query type."""

    name: str
    passthrough_k: int  # raw chunks to keep verbatim
    code_weight: float
    docs_weight: float
    max_item_tokens: int  # per-item truncation limit
    min_code_items: int  # floor for code items in output
    reasoning_boost: float = 0.0  # additive confidence boost for reasoning-bearing chunks


MODES = {
    "implementation": RefinementMode("implementation", 5, 2.0, 0.5, 1000, 2, 0.0),
    "decision": RefinementMode("decision", 4, 1.5, 0.7, 800, 1, 0.6),
    "cross_file": RefinementMode("cross_file", 6, 1.8, 0.6, 2000, 3, 0.3),
    "feature": RefinementMode("feature", 3, 1.5, 0.7, 800, 2, 0.0),
    "security": RefinementMode("security", 4, 1.5, 0.7, 800, 2, 0.3),
    "balanced": RefinementMode("balanced", 3, 1.5, 0.7, 800, 2, 0.0),
}

# Priority-ordered patterns for mode detection
_MODE_PATTERNS = [
    (re.compile(r"\b(where|locate|which\s+file|location)\b", re.IGNORECASE), "implementation"),
    (re.compile(r"\b(why|chose|instead|rather than)\b", re.IGNORECASE), "decision"),
    (re.compile(r"\b(flow|interact|propagat|across|between|chain|lifecycle|pipeline)\b", re.IGNORECASE), "cross_file"),
    (re.compile(r"\b(security|auth|oauth|cors|tls|permission|scope)\b", re.IGNORECASE), "security"),
    (re.compile(r"\bhow\s+does\b", re.IGNORECASE), "feature"),
]


def detect_mode(question: str) -> RefinementMode:
    """Detect refinement mode from question text using priority-ordered regex."""
    for pattern, mode_name in _MODE_PATTERNS:
        if pattern.search(question):
            return MODES[mode_name]
    return MODES["balanced"]


@dataclass
class RefinedItem:
    """A single item in the refinement output — either a claim or a code chunk."""

    id: str
    text: str
    source_type: str  # "code" or "docs"
    confidence: float = 1.0
    retrieval_score: float = 0.0
    evidence: list[EvidencePointer] = field(default_factory=list)


@dataclass
class RefinementResult:
    """Output of the refinement pipeline."""

    items: list[RefinedItem] = field(default_factory=list)
    tokens_before: int = 0
    tokens_after: int = 0
    evidence_map: dict[str, dict] = field(default_factory=dict)


@dataclass
class ChunkWithMeta:
    """A retrieval chunk enriched with metadata for refinement."""

    text: str
    chunk_id: str
    score: float
    text_unit: Optional[TextUnit] = None
    resource: Optional[Resource] = None
    source_type: str = "unknown"


def _detect_source_type(chunk: ChunkWithMeta) -> str:
    """Classify chunk as code or docs. Uses Resource.kind first, then heuristic."""
    if chunk.resource:
        if chunk.resource.kind == "file":
            ext = chunk.resource.metadata.get("extension", "")
            if ext in (".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".rb"):
                return "code"
            if ext in (".md", ".rst", ".txt", ".html"):
                return "docs"
        elif chunk.resource.kind == "document":
            return "docs"

    # Heuristic fallback: look for code patterns in the text
    if _CODE_PATTERNS.search(chunk.text):
        return "code"
    return "docs"


def _get_item_source_file(
    item: RefinedItem,
    text_units_by_id: dict[str, TextUnit],
    resources_by_id: dict[str, Resource],
) -> str:
    """Extract source file path from a RefinedItem's evidence chain."""
    if item.evidence:
        tu = text_units_by_id.get(item.evidence[0].source_unit_id)
        if tu:
            res = resources_by_id.get(tu.resource_id)
            if res:
                return res.locator
    return ""


def refine(
    chunks: list[ChunkWithMeta],
    text_units_by_id: dict[str, TextUnit],
    resources_by_id: dict[str, Resource],
    max_items: int = MAX_REFINED_ITEMS,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    question: str = "",
) -> RefinementResult:
    """Refine hybrid retrieval chunks into structured, traceable items.

    Pipeline:
    1. Detect refinement mode from question
    2. Classify each chunk as code vs docs
    3. Keep top-k raw chunks as passthrough (preserves recall)
    4. For remaining docs: extract claims, deduplicate, apply docs_weight
    5. For remaining code: wrap verbatim, apply code_weight
    6. Guarantee minimum code items in output
    7. Merge and rank by confidence * retrieval_score
    8. Cap to max_items and token_budget (whichever hits first)
    9. Build evidence map
    """
    if not chunks:
        return RefinementResult()

    tokens_before = sum(_count_tokens(c.text) for c in chunks)

    # Step 1: Detect mode
    mode = detect_mode(question)

    # Cross-file tasks get expanded token budget
    if mode.name == "cross_file":
        token_budget = max(token_budget, CROSS_FILE_TOKEN_BUDGET)

    # Scale budget by input file diversity (all modes).
    # When retrieval surfaces chunks from many files, a tight budget
    # forces the output to drop entire files, losing cross-file facts.
    input_files = {c.resource.locator for c in chunks if c.resource}
    if len(input_files) >= 6:
        token_budget = max(token_budget, 7000)
    elif len(input_files) >= 4:
        token_budget = max(token_budget, 6000)
    elif len(input_files) >= 3:
        token_budget = max(token_budget, 5000)

    # Step 2: Classify and resolve metadata
    for chunk in chunks:
        if chunk.text_unit is None and chunk.chunk_id in text_units_by_id:
            chunk.text_unit = text_units_by_id[chunk.chunk_id]
        if chunk.text_unit and chunk.resource is None:
            chunk.resource = resources_by_id.get(chunk.text_unit.resource_id)
        chunk.source_type = _detect_source_type(chunk)

    # Step 3: Passthrough — keep top-k raw chunks by retrieval score
    # These are the exact chunks that give hybrid its recall advantage.
    passthrough_ids: set[str] = set()
    passthrough_items: list[RefinedItem] = []
    for chunk in chunks[: mode.passthrough_k]:
        passthrough_ids.add(chunk.chunk_id)
        evidence = []
        if chunk.text_unit:
            evidence.append(
                EvidencePointer(
                    source_unit_id=chunk.text_unit.id,
                    span=chunk.text_unit.span,
                    weight=1.0,
                )
            )
        passthrough_items.append(
            RefinedItem(
                id=_generate_id(f"passthrough:{chunk.chunk_id}"),
                text=chunk.text,
                source_type=chunk.source_type,
                confidence=2.0,  # highest priority
                retrieval_score=chunk.score,
                evidence=evidence,
            )
        )

    # Step 3b: Neighboring-file boost for cross_file mode
    if mode.name == "cross_file":
        passthrough_files: set[str] = set()
        for item in passthrough_items:
            if item.evidence:
                tu = text_units_by_id.get(item.evidence[0].source_unit_id)
                if tu:
                    res = resources_by_id.get(tu.resource_id)
                    if res:
                        passthrough_files.add(res.locator)

        # Boost chunks from same directory as passthrough files
        passthrough_dirs = {str(Path(f).parent) for f in passthrough_files}
        for chunk in chunks:
            if chunk.chunk_id in passthrough_ids:
                continue
            if chunk.resource:
                chunk_dir = str(Path(chunk.resource.locator).parent)
                if chunk_dir in passthrough_dirs:
                    chunk.score = max(chunk.score, 0.5)  # floor score for neighbors

    # Step 4: Classify remaining chunks (exclude passthrough)
    remaining_chunks = [c for c in chunks if c.chunk_id not in passthrough_ids]
    code_chunks = [c for c in remaining_chunks if c.source_type == "code"]
    docs_chunks = [c for c in remaining_chunks if c.source_type != "code"]

    items: list[RefinedItem] = list(passthrough_items)

    # Step 5: Process docs chunks — extract and deduplicate claims
    if docs_chunks:
        doc_text_units = []
        doc_score_by_tu_id: dict[str, float] = {}
        tu_id_to_chunk: dict[str, ChunkWithMeta] = {}
        for chunk in docs_chunks:
            if chunk.text_unit:
                doc_text_units.append(chunk.text_unit)
                doc_score_by_tu_id[chunk.text_unit.id] = chunk.score
                tu_id_to_chunk[chunk.text_unit.id] = chunk
            else:
                # No text unit — create a synthetic one for extraction
                tu = TextUnit(
                    content=chunk.text,
                    resource_id=chunk.resource.id if chunk.resource else "",
                )
                doc_text_units.append(tu)
                doc_score_by_tu_id[tu.id] = chunk.score
                tu_id_to_chunk[tu.id] = chunk

        raw_claims = extract_claims(doc_text_units)
        dedup_result = deduplicate_claims(raw_claims)

        # Track which doc TUs produced claims
        tus_with_claims: set[str] = set()
        for claim in dedup_result.claims:
            # Find the retrieval score from the source text unit
            retrieval_score = 0.0
            if claim.derived_from and claim.derived_from in doc_score_by_tu_id:
                retrieval_score = doc_score_by_tu_id[claim.derived_from]
                tus_with_claims.add(claim.derived_from)
            elif claim.evidence:
                for ev in claim.evidence:
                    if ev.source_unit_id in doc_score_by_tu_id:
                        retrieval_score = max(
                            retrieval_score, doc_score_by_tu_id[ev.source_unit_id]
                        )
                        tus_with_claims.add(ev.source_unit_id)

            confidence = claim.confidence * mode.docs_weight
            if mode.reasoning_boost > 0 and has_reasoning(claim.text):
                confidence += mode.reasoning_boost

            items.append(
                RefinedItem(
                    id=claim.id,
                    text=claim.text,
                    source_type="docs",
                    confidence=confidence,
                    retrieval_score=retrieval_score,
                    evidence=claim.evidence,
                )
            )

        # Fallback: doc chunks that produced zero claims — keep verbatim
        # (prevents info loss from extraction failures on non-prose docs)
        for tu_id, chunk in tu_id_to_chunk.items():
            if tu_id not in tus_with_claims:
                evidence = []
                if chunk.text_unit:
                    evidence.append(
                        EvidencePointer(
                            source_unit_id=chunk.text_unit.id,
                            span=chunk.text_unit.span,
                            weight=1.0,
                        )
                    )
                confidence = mode.docs_weight * 0.5  # lower than extracted claims
                if mode.reasoning_boost > 0 and has_reasoning(chunk.text):
                    confidence += mode.reasoning_boost

                items.append(
                    RefinedItem(
                        id=_generate_id(f"docs-raw:{chunk.chunk_id}"),
                        text=chunk.text,
                        source_type="docs",
                        confidence=confidence,
                        retrieval_score=chunk.score,
                        evidence=evidence,
                    )
                )

    # Step 6: Process remaining code chunks — keep verbatim
    for chunk in code_chunks:
        item_id = _generate_id(f"code:{chunk.chunk_id}")
        evidence = []
        if chunk.text_unit:
            evidence.append(
                EvidencePointer(
                    source_unit_id=chunk.text_unit.id,
                    span=chunk.text_unit.span,
                    weight=1.0,
                )
            )

        items.append(
            RefinedItem(
                id=item_id,
                text=chunk.text,
                source_type="code",
                confidence=mode.code_weight,  # mode-specific code weight
                retrieval_score=chunk.score,
                evidence=evidence,
            )
        )

    # Step 7: Code minimum guarantee — boost code items if underrepresented
    code_in_output = sum(1 for item in items if item.source_type == "code")
    if code_in_output < mode.min_code_items:
        all_code = [i for i in items if i.source_type == "code"]
        all_code.sort(key=lambda x: x.retrieval_score, reverse=True)
        for code_item in all_code[: mode.min_code_items]:
            code_item.confidence = max(code_item.confidence, 1.9)  # just below passthrough

    # Step 8: Merge and rank by confidence * retrieval_score
    items.sort(key=lambda x: x.confidence * x.retrieval_score, reverse=True)

    # Step 9: Truncate oversized items.
    # Passthrough items (confidence=2.0) get a higher limit — they are raw
    # hybrid-scored chunks kept precisely to preserve recall.  Truncating
    # them to 800 tokens destroys the content they were selected for.
    passthrough_limit = max(mode.max_item_tokens, token_budget // 2)
    for item in items:
        limit = passthrough_limit if item.confidence >= 2.0 else mode.max_item_tokens
        item_tokens = _count_tokens(item.text)
        if item_tokens > limit:
            words = item.text.split()
            item.text = " ".join(words[:limit])

    # Step 10: Cap by token_budget using skip-and-pack for all modes.
    #
    # Passthrough items (confidence >= 2.0) are the recall insurance — they
    # were selected specifically to preserve the facts hybrid retrieval found.
    # They MUST be included before diversity filling, otherwise the diversity
    # mechanism fills all slots with one-per-file small chunks and pushes
    # large, information-rich passthrough items into the remainder.
    passthrough_final: list[RefinedItem] = []
    non_passthrough: list[RefinedItem] = []
    seen_files: set[str] = set()
    for item in items:
        if item.confidence >= 2.0:
            passthrough_final.append(item)
            src = _get_item_source_file(item, text_units_by_id, resources_by_id)
            if src:
                seen_files.add(src)
        else:
            non_passthrough.append(item)

    # File-diversity from non-passthrough items (new files only).
    # Prioritise files that share a directory with passthrough files —
    # they are likely part of the same call chain.
    passthrough_dirs = {str(Path(f).parent) for f in seen_files}
    diversity_items: list[RefinedItem] = []
    remainder_items: list[RefinedItem] = []
    for item in non_passthrough:
        src = _get_item_source_file(item, text_units_by_id, resources_by_id)
        if src and src not in seen_files:
            seen_files.add(src)
            diversity_items.append(item)
        else:
            remainder_items.append(item)

    # Sort diversity: same-directory-as-passthrough files first, then rest.
    # Within each group, keep existing ranking order (confidence * score).
    nearby_div: list[RefinedItem] = []
    faraway_div: list[RefinedItem] = []
    for item in diversity_items:
        src = _get_item_source_file(item, text_units_by_id, resources_by_id)
        if src and str(Path(src).parent) in passthrough_dirs:
            nearby_div.append(item)
        else:
            faraway_div.append(item)
    diversity_items = nearby_div + faraway_div

    # Fill budget — passthrough first, then diversity, then remainder.
    # Use `continue` not `break` — skip large items, keep packing small ones.
    budget_items: list[RefinedItem] = []
    running_tokens = 0
    for item in passthrough_final + diversity_items + remainder_items:
        item_tokens = _count_tokens(item.text)
        if budget_items and running_tokens + item_tokens > token_budget:
            continue  # skip this item, try smaller ones
        budget_items.append(item)
        running_tokens += item_tokens
        if len(budget_items) >= max_items:
            break
    items = budget_items

    # Empty extraction fallback
    if not items:
        # Return raw chunks as unrefined items
        for chunk in chunks[:max_items]:
            chunk_tokens = _count_tokens(chunk.text)
            if items and running_tokens + chunk_tokens > token_budget:
                break
            items.append(
                RefinedItem(
                    id=chunk.chunk_id,
                    text=chunk.text,
                    source_type=chunk.source_type,
                    confidence=0.5,
                    retrieval_score=chunk.score,
                )
            )
            running_tokens += chunk_tokens

    tokens_after = sum(_count_tokens(item.text) for item in items)

    # Step 11: Build evidence map
    evidence_map: dict[str, dict] = {}
    for item in items:
        source_file = ""
        source_span = None
        if item.evidence:
            ev = item.evidence[0]
            tu = text_units_by_id.get(ev.source_unit_id)
            if tu:
                resource = resources_by_id.get(tu.resource_id)
                if resource:
                    source_file = resource.locator
                source_span = tu.span

        evidence_map[item.id] = {
            "source_file": source_file,
            "source_span": list(source_span) if source_span else None,
            "source_type": item.source_type,
        }

    return RefinementResult(
        items=items,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        evidence_map=evidence_map,
    )
