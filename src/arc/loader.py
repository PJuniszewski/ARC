"""Loader — verify, resolve, and selectively mount archive content."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


from .cas import VerificationResult, open_cas
from .embeddings import TfidfEmbedder, VectorStore, get_embedder
from .manifest import read_manifest_from_cas, validate_manifest
from .config import (
    BFS_EXPANSION_MIN,
    EXPANSION_MIN,
    HEADING_BOOST_WEIGHT,
    HEADING_MATCH_THRESHOLD,
    KEYWORD_BOOST_WEIGHT,
    KEYWORD_SEED_MIN_TOKENS,
    MAX_BFS_RESULTS,
    MAX_FILTERED_CLAIMS,
    MIN_SCORE,
    STOP_WORDS,
    TOP_K_BASE,
    TOP_K_RATIO,
)
from .models import Claim, Decision, Manifest, PolicyRule, Resource, TextUnit, ToolDeclaration, WorkflowStep


@dataclass
class LoadedArchive:
    """Typed access to loaded archive content."""

    manifest: Manifest
    resources: list[Resource] = field(default_factory=list)
    source_units: list[TextUnit] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    tools: list[ToolDeclaration] = field(default_factory=list)
    policies: list[PolicyRule] = field(default_factory=list)
    workflow: list[WorkflowStep] = field(default_factory=list)
    vector_store: Optional[VectorStore] = None
    archive_path: str = ""

    # For rejection tracking
    rejected: bool = False
    reason: str = ""

    def flat_search(self, query: str, top_k: int = 10) -> list[Claim]:
        """Simple text-match search over claims."""
        query_lower = query.lower()
        scored = []
        for claim in self.claims:
            # Simple word overlap scoring
            claim_words = set(claim.text.lower().split())
            query_words = set(query_lower.split())
            overlap = len(claim_words & query_words)
            if overlap > 0:
                scored.append((overlap / len(query_words), claim))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]

    def traverse_evidence_graph(self, query: str, hops: int = 2) -> list[Claim]:
        """Graph traversal: find claims related to query, then follow evidence links."""
        # Start with vector search if available
        _embedder = None
        score_by_id: dict[str, float] = {}
        if self.vector_store and self.vector_store.vectors is not None:
            _embedder = self.vector_store.restore_embedder()
            if _embedder is None:
                _embedder = TfidfEmbedder(dimensions=256)
                all_texts = [c.text for c in self.claims]
                if all_texts:
                    _embedder.fit(all_texts)
            query_vec = _embedder.embed(query)
            _claim_ids = {c.id for c in self.claims}
            _all_search = self.vector_store.search(query_vec, top_k=len(self.vector_store.ids))
            search_results = [(cid, s, t) for cid, s, t in _all_search if cid in _claim_ids][:TOP_K_BASE]
            seed_ids = {r[0] for r in search_results}
            # Keyword seeding: add claims sharing 3+ stemmed tokens with query
            query_tokens = set(_embedder._tokenize(query))
            for claim in self.claims:
                if claim.id not in seed_ids:
                    claim_tokens = set(_embedder._tokenize(claim.text))
                    if len(query_tokens & claim_tokens) >= KEYWORD_SEED_MIN_TOKENS:
                        seed_ids.add(claim.id)

            # Pre-compute hybrid scores for BFS gating (mirrors _filter_by_task)
            raw_results = [(cid, s, t) for cid, s, t in _all_search if cid in _claim_ids]
            for cid, vscore, text in raw_results:
                claim_tokens = set(_embedder._tokenize(text))
                overlap = len(query_tokens & claim_tokens)
                kw_boost = overlap / len(query_tokens) if query_tokens else 0.0
                score_by_id[cid] = vscore + KEYWORD_BOOST_WEIGHT * kw_boost
        else:
            # Fallback to text search
            seed_claims = self.flat_search(query, top_k=5)
            seed_ids = {c.id for c in seed_claims}

        # Build claim index and evidence graph
        claim_by_id = {c.id: c for c in self.claims}
        su_to_claims: dict[str, list[str]] = {}
        for claim in self.claims:
            for ev in claim.evidence:
                su_to_claims.setdefault(ev.source_unit_id, []).append(claim.id)

        # BFS traversal with hybrid relevance filter
        visited = set(seed_ids)
        frontier = set(seed_ids)
        _bfs_query_tokens = set(_embedder._tokenize(query)) if _embedder else set()

        for _ in range(hops):
            next_frontier: set[str] = set()
            for claim_id in frontier:
                claim = claim_by_id.get(claim_id)
                if not claim:
                    continue
                # Hybrid gate: pass if tokens overlap OR vector score is high enough.
                # If query tokens are empty (tokenizer failure), require vector relevance
                # to prevent the gate from being wide open.
                if _bfs_query_tokens:
                    claim_tokens = set(_embedder._tokenize(claim.text))
                    has_token_overlap = bool(_bfs_query_tokens & claim_tokens)
                    has_vector_relevance = score_by_id.get(claim_id, 0) >= BFS_EXPANSION_MIN
                    if not (has_token_overlap or has_vector_relevance):
                        continue
                elif score_by_id:
                    # No query tokens available — fall back to vector score only
                    if score_by_id.get(claim_id, 0) < BFS_EXPANSION_MIN:
                        continue
                # Follow evidence pointers to find co-located claims
                for ev in claim.evidence:
                    related = su_to_claims.get(ev.source_unit_id, [])
                    for related_id in related:
                        if related_id not in visited:
                            next_frontier.add(related_id)
                            visited.add(related_id)
            frontier = next_frontier

        # Safety cap: limit BFS results by hybrid score
        result_claims = [claim_by_id[cid] for cid in visited if cid in claim_by_id]
        if len(result_claims) > MAX_BFS_RESULTS and score_by_id:
            result_claims.sort(key=lambda c: score_by_id.get(c.id, 0), reverse=True)
            result_claims = result_claims[:MAX_BFS_RESULTS]
        return result_claims


def verify(archive_path: str | Path) -> VerificationResult:
    """Verify archive integrity — digests, schema, references."""
    try:
        cas = open_cas(Path(archive_path))
        return cas.verify_archive()
    except FileNotFoundError:
        return VerificationResult(valid=False, errors=[f"Archive not found: {archive_path}"])
    except (sqlite3.DatabaseError, sqlite3.OperationalError, json.JSONDecodeError, OSError) as e:
        return VerificationResult(valid=False, errors=[f"Cannot read archive: {e}"])


def load(
    archive_path: str | Path,
    layers: Optional[list[str]] = None,
    task: Optional[str] = None,
    expected_min_version: Optional[str] = None,
    claim_type: Optional[str] = None,
    source: Optional[str] = None,
    full: bool = False,
) -> LoadedArchive:
    """Load and optionally filter archive content.

    Args:
        archive_path: Path to archive directory
        layers: Specific layers to load (e.g., ["claims", "decisions"])
        task: Task description for selective loading via embeddings
        expected_min_version: Minimum version for rollback protection
        claim_type: Filter claims by type (observation/decision/uncertainty/dependency/conflict)
        source: Filter claims by source agent ID
    """
    archive_path = Path(archive_path)
    try:
        cas = open_cas(archive_path)
    except FileNotFoundError:
        result = LoadedArchive(manifest=Manifest(), archive_path=str(archive_path))
        result.rejected = True
        result.reason = f"Archive not found: {archive_path}"
        return result
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError) as e:
        result = LoadedArchive(manifest=Manifest(), archive_path=str(archive_path))
        result.rejected = True
        result.reason = f"Cannot read archive: {e}"
        return result

    # Read and validate manifest
    try:
        manifest = read_manifest_from_cas(cas)
    except (sqlite3.DatabaseError, sqlite3.OperationalError, json.JSONDecodeError, OSError) as e:
        result = LoadedArchive(manifest=Manifest(), archive_path=str(archive_path))
        result.rejected = True
        result.reason = f"Cannot read archive: {e}"
        return result
    if manifest is None:
        result = LoadedArchive(manifest=Manifest(), archive_path=str(archive_path))
        result.rejected = True
        result.reason = "Missing manifest"
        return result

    errors = validate_manifest(manifest)
    if errors:
        result = LoadedArchive(manifest=manifest, archive_path=str(archive_path))
        result.rejected = True
        result.reason = f"Invalid manifest: {'; '.join(errors)}"
        return result

    # Version check (rollback protection)
    if expected_min_version:
        if _version_lt(manifest.archive_version, expected_min_version):
            result = LoadedArchive(manifest=manifest, archive_path=str(archive_path))
            result.rejected = True
            result.reason = (
                f"Archive version {manifest.archive_version} is below "
                f"minimum expected version {expected_min_version} (rollback detected)"
            )
            return result

    # Determine which layers to load
    layers_to_load = set()
    if layers:
        layers_to_load = set(layers)
    else:
        layers_to_load = {l.name for l in manifest.layers}

    loaded = LoadedArchive(manifest=manifest, archive_path=str(archive_path))

    # Load each requested layer
    for layer in manifest.layers:
        if layer.name not in layers_to_load:
            continue

        blob_data = cas.retrieve_blob(layer.digest)
        if blob_data is None:
            if layer.required:
                loaded.rejected = True
                loaded.reason = f"Missing required blob for layer '{layer.name}'"
                return loaded
            continue

        # Verify blob integrity
        from .cas import sha256_digest
        if sha256_digest(blob_data) != layer.digest:
            loaded.rejected = True
            loaded.reason = f"Digest mismatch for layer '{layer.name}'"
            return loaded

        try:
            data = json.loads(blob_data)
        except json.JSONDecodeError as e:
            logger.error("corrupt JSON in layer '%s': %s", layer.name, e)
            loaded.rejected = True
            loaded.reason = f"Corrupt JSON in layer '{layer.name}': {e}"
            return loaded

        if layer.type == "semantic.resources":
            loaded.resources = [Resource.from_dict(d) for d in data]
        elif layer.type == "semantic.source_units":
            loaded.source_units = [TextUnit.from_dict(d) for d in data]
        elif layer.type == "semantic.claims":
            loaded.claims = [Claim.from_dict(d) for d in data]
        elif layer.type == "semantic.decisions":
            loaded.decisions = [Decision.from_dict(d) for d in data]
        elif layer.type == "index.embeddings":
            loaded.vector_store = VectorStore.from_dict(data)
        elif layer.type == "operational.tools":
            loaded.tools = [ToolDeclaration.from_dict(d) for d in data]
        elif layer.type == "operational.policy":
            loaded.policies = [PolicyRule.from_dict(d) for d in data]
        elif layer.type == "operational.workflow":
            loaded.workflow = [WorkflowStep.from_dict(d) for d in data]

    logger.info(
        "loaded archive=%s layers=%d claims=%d source_units=%d decisions=%d tools=%d policies=%d workflow=%d",
        loaded.manifest.archive_id,
        len(loaded.manifest.layers),
        len(loaded.claims),
        len(loaded.source_units),
        len(loaded.decisions),
        len(loaded.tools),
        len(loaded.policies),
        len(loaded.workflow),
    )

    # Task-based filtering: use embeddings to select relevant claims
    if task and loaded.vector_store and loaded.claims:
        total_before = len(loaded.claims)
        loaded.claims = _filter_by_task(loaded, task, full=full)
        logger.info(
            "filtered claims for task=%r: %d → %d",
            task[:80], total_before, len(loaded.claims),
        )

    # Filter by claim_type and/or source
    if claim_type and loaded.claims:
        loaded.claims = [c for c in loaded.claims if c.claim_type == claim_type]
    if source and loaded.claims:
        loaded.claims = [c for c in loaded.claims if c.source == source]
    # When filtering by type=decision, also surface Decision objects as claims
    if claim_type == "decision" and loaded.decisions:
        _dec_status_map = {
            "proposed": "observed", "accepted": "verified",
            "superseded": "deprecated", "rejected": "deprecated",
        }
        for d in loaded.decisions:
            if source and d.source != source:
                continue
            loaded.claims.append(Claim(
                id=d.id,
                text=f"{d.title}: {d.decision}" if d.decision else d.title,
                kind="assertion",
                claim_type="decision",
                source=d.source,
                timestamp=d.timestamp,
                evidence=list(d.evidence),
                confidence=1.0,
                status=_dec_status_map.get(d.status, "observed"),
            ))
    # Also filter decisions by source if requested
    if source and loaded.decisions:
        loaded.decisions = [d for d in loaded.decisions if d.source == source]

    return loaded


def _normalize_for_search(text: str) -> str:
    """Normalize text for search: split snake_case/camelCase, lowercase, strip symbols."""
    import re as _re
    # Split camelCase: "SqliteCAS" → "Sqlite CAS", "camelCase" → "camel Case"
    text = _re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    # Replace _ and - with spaces
    text = text.replace("_", " ").replace("-", " ")
    return text.lower()


def _substring_boost(query_tokens: set[str], claim_text: str) -> float:
    """Boost if query tokens appear as substrings in claim text (catches vocab mismatches)."""
    text_lower = claim_text.lower()
    hits = sum(1 for t in query_tokens if len(t) >= 3 and t in text_lower)
    return min(hits * 0.15, 0.4) if query_tokens else 0.0


def _filter_by_task(loaded: LoadedArchive, task: str, full: bool = False) -> list[Claim]:
    """Filter claims by task relevance using hybrid keyword + vector scoring."""
    if not loaded.vector_store or loaded.vector_store.vectors is None:
        return loaded.claims

    # Prefer restored embedder (aligned with build-time vocabulary)
    embedder = loaded.vector_store.restore_embedder()
    embedder_type = type(embedder).__name__ if embedder else "none"
    logger.debug("embedder restored: %s", embedder_type)
    if embedder is None:
        embedder = get_embedder(dimensions=256)
        all_texts = [c.text for c in loaded.claims]
        if all_texts:
            embedder.fit(all_texts)
    query_vec = embedder.embed(task)

    # Get vector similarity scores — search broadly to compensate for
    # non-claim entries (tools, workflows) in the vector store, then
    # filter to claim IDs only.
    claim_ids = {c.id for c in loaded.claims}
    search_k = len(loaded.vector_store.ids)  # search all, filter after
    all_results = loaded.vector_store.search(query_vec, top_k=search_k)
    raw_results = [(cid, s, t) for cid, s, t in all_results if cid in claim_ids]

    # Normalize query for better matching: split snake_case/camelCase
    norm_task = _normalize_for_search(task)
    query_tokens = set(embedder._tokenize(norm_task))
    # Also include tokens from original (un-normalized) query
    query_tokens |= set(embedder._tokenize(task))

    # Content query tokens (stop words removed) for heading matching
    content_query_tokens = query_tokens - STOP_WORDS
    # Normalized query tokens for substring matching
    norm_query_tokens = set(norm_task.split()) - STOP_WORDS

    scored: list[tuple[str, float, str]] = []
    for cid, vscore, text in raw_results:
        # Normalize claim text before tokenizing
        norm_text = _normalize_for_search(text)
        claim_tokens = set(embedder._tokenize(norm_text))
        # Also include original text tokens
        claim_tokens |= set(embedder._tokenize(text))
        overlap = len(query_tokens & claim_tokens)
        kw_boost = overlap / len(query_tokens) if query_tokens else 0.0

        # Substring boost: catches vocabulary mismatches
        sub_boost = _substring_boost(norm_query_tokens, norm_text)

        # Section heading boost: if the claim was enriched with a heading
        # prefix (e.g. "Archive Classes: ..."), and most heading words
        # appear in the query, this claim is likely a direct topical hit.
        heading_boost = 0.0
        if ": " in text:
            heading = text[:text.index(": ")]
            heading_tokens = set(embedder._tokenize(heading)) - STOP_WORDS
            if heading_tokens:
                heading_match = len(heading_tokens & content_query_tokens) / len(heading_tokens)
                if heading_match >= HEADING_MATCH_THRESHOLD:
                    heading_boost = HEADING_BOOST_WEIGHT * heading_match

        hybrid = vscore + KEYWORD_BOOST_WEIGHT * kw_boost + heading_boost + sub_boost
        scored.append((cid, hybrid, text))

    # Sort by hybrid score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # In --full mode: return everything above near-zero threshold
    # Default mode: dynamic limits based on archive size
    total = len(loaded.claims)
    min_threshold = 0.01 if full else MIN_SCORE
    if full or total < 500:
        results = [(cid, s, t) for cid, s, t in scored if s >= min_threshold]
    else:
        TOP_K = max(TOP_K_BASE, int(total * TOP_K_RATIO))
        results = [(cid, s, t) for cid, s, t in scored[:TOP_K] if s >= min_threshold]
    if not results and scored:
        results = scored[:3]

    relevant_ids = {r[0] for r in results}

    # Score lookup for expansion gating — every claim already has a
    # hybrid score from the vector+keyword pass above.
    score_by_id = {cid: s for cid, s, _ in scored}

    claim_by_id = {c.id: c for c in loaded.claims}
    selected = []
    seen = set()

    # Add hybrid-scored matches (primary selection)
    for cid in relevant_ids:
        if cid in claim_by_id and cid not in seen:
            selected.append(claim_by_id[cid])
            seen.add(cid)

    # Evidence graph expansion: include siblings from high-confidence
    # sources, but only if the sibling scored above EXPANSION_MIN in
    # the hybrid pass. This uses vector similarity to catch semantic
    # neighbors (e.g. "tamper" near "security") that token matching misses.
    high_conf_sources = {
        claim_by_id[cid].derived_from
        for cid in relevant_ids
        if cid in claim_by_id and claim_by_id[cid].derived_from
    }
    for claim in loaded.claims:
        if (claim.derived_from in high_conf_sources
                and claim.id not in seen
                and score_by_id.get(claim.id, 0) >= EXPANSION_MIN):
            selected.append(claim)
            seen.add(claim.id)

    # Source-level matching: find source units matching the query, then
    # include derived claims that scored above EXPANSION_MIN.
    content_query_tokens = query_tokens - STOP_WORDS
    if loaded.source_units and content_query_tokens:
        for tu in loaded.source_units:
            tu_tokens = set(embedder._tokenize(tu.content))
            if len(content_query_tokens & tu_tokens) >= KEYWORD_SEED_MIN_TOKENS:
                for claim in loaded.claims:
                    if (claim.derived_from == tu.id
                            and claim.id not in seen
                            and score_by_id.get(claim.id, 0) >= EXPANSION_MIN):
                        selected.append(claim)
                        seen.add(claim.id)

    # Add requirements that scored above EXPANSION_MIN
    for claim in loaded.claims:
        if (claim.kind == "requirement"
                and claim.id not in seen
                and score_by_id.get(claim.id, 0) >= EXPANSION_MIN):
            selected.append(claim)
            seen.add(claim.id)

    # Hard cap: in full mode, no cap at all. For large archives, apply limit.
    pre_cap = len(selected)
    if not full and total >= 500:
        MAX_TOTAL = max(MAX_FILTERED_CLAIMS, int(total * 0.3))
        if len(selected) > MAX_TOTAL:
            selected.sort(key=lambda c: score_by_id.get(c.id, 0), reverse=True)
            selected = selected[:MAX_TOTAL]

    if selected:
        top_score = max(score_by_id.get(c.id, 0) for c in selected)
        min_score = min(score_by_id.get(c.id, 0) for c in selected)
        logger.debug(
            "filter result: %d selected (capped from %d), "
            "score range [%.3f, %.3f], primary=%d expansion=%d",
            len(selected), pre_cap, min_score, top_score,
            len(relevant_ids), pre_cap - len(relevant_ids),
        )

    return selected


def restore_sources(
    archive_path: str | Path,
    output_dir: str | Path,
) -> dict:
    """Restore source files from archive (lossy reconstruction).

    Reads the source-units layer and reconstructs files by joining text
    units with double newlines. This is NOT lossless: original whitespace,
    line endings, and inter-section formatting are not preserved. The
    semantic content is intact but the byte-level original is lost.

    Returns:
        {restored_files: list[str], total_bytes: int}
    """
    archive_path = Path(archive_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cas = open_cas(archive_path)
    manifest = read_manifest_from_cas(cas)
    if manifest is None:
        return {"restored_files": [], "total_bytes": 0, "error": "Missing manifest"}

    # Load source-units layer to get resource locators and content digests
    loaded = load(archive_path, layers=["source-units"])
    if loaded.rejected:
        return {"restored_files": [], "total_bytes": 0, "error": loaded.reason}

    # Group text units by resource_id to reconstruct files
    # We need the Resource objects too — read provenance for locators
    provenance_data = cas.read_json("provenance.json", subdir="refs")
    if not provenance_data:
        return {"restored_files": [], "total_bytes": 0, "error": "Missing provenance"}

    # Build locator→digest map from provenance source_inventory
    source_inventory = provenance_data.get("source_inventory", [])
    locator_to_digest: dict[str, str] = {}
    for src in source_inventory:
        locator_to_digest[src["locator"]] = src["digest"]

    # Group text units by resource, ordered by span
    from collections import defaultdict
    units_by_resource: dict[str, list] = defaultdict(list)
    for tu in loaded.source_units:
        units_by_resource[tu.resource_id].append(tu)

    # Sort each group by span start
    for rid in units_by_resource:
        units_by_resource[rid].sort(key=lambda tu: tu.span[0])

    # For each resource in provenance, reconstruct the file from text units
    restored_files = []
    total_bytes = 0

    # We also need locator→resource_id map. Build it from the ingestion pattern:
    # resource_id = _generate_id(f"resource:{locator}")
    from .models import _generate_id as gen_id
    locator_to_resource_id: dict[str, str] = {}
    for locator in locator_to_digest:
        rid = gen_id(f"resource:{locator}")
        locator_to_resource_id[locator] = rid

    for locator, resource_id in locator_to_resource_id.items():
        units = units_by_resource.get(resource_id, [])
        if not units:
            continue

        # Reconstruct file content from text units
        content = "\n\n".join(tu.content for tu in units)

        # Write to output preserving relative path (with path traversal protection)
        out_path = (output_dir / locator).resolve()
        if not str(out_path).startswith(str(output_dir.resolve())):
            logger.warning("path traversal blocked: %s", locator)
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")

        restored_files.append(locator)
        total_bytes += len(content.encode("utf-8"))

    return {
        "restored_files": sorted(restored_files),
        "total_bytes": total_bytes,
    }


def _version_lt(a: str, b: str) -> bool:
    """Semantic version comparison (a < b).

    Handles pre-release suffixes like "1.0.0-rc1" by stripping them
    and comparing numeric parts only. Pre-release is considered less
    than the release (e.g. "1.0.0-rc1" < "1.0.0").
    """
    import re

    def _parse(v: str) -> tuple[tuple[int, ...], str]:
        # Split "1.0.0-rc1" into ("1.0.0", "rc1")
        match = re.match(r'^([\d.]+)(.*)', v)
        if not match:
            return ((), v)
        numeric = tuple(int(x) for x in match.group(1).split(".") if x)
        suffix = match.group(2).lstrip("-").lstrip("+")
        return (numeric, suffix)

    try:
        va_num, va_suffix = _parse(a)
        vb_num, vb_suffix = _parse(b)
        if va_num != vb_num:
            return va_num < vb_num
        # Same numeric part: pre-release (non-empty suffix) < release (empty suffix)
        if va_suffix and not vb_suffix:
            return True
        if not va_suffix and vb_suffix:
            return False
        return va_suffix < vb_suffix
    except (ValueError, AttributeError):
        return str(a) < str(b)
