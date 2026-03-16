"""Loader — verify, resolve, and selectively mount archive content."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .cas import ContentAddressedStore, VerificationResult
from .embeddings import TfidfEmbedder, VectorStore, get_embedder
from .manifest import read_manifest_from_cas, validate_manifest
from .models import Claim, Decision, Manifest, TextUnit


@dataclass
class LoadedArchive:
    """Typed access to loaded archive content."""

    manifest: Manifest
    source_units: list[TextUnit] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
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
        if self.vector_store and self.vector_store.vectors is not None:
            _embedder = self.vector_store.restore_embedder()
            if _embedder is None:
                _embedder = TfidfEmbedder(dimensions=256)
                all_texts = [c.text for c in self.claims]
                if all_texts:
                    _embedder.fit(all_texts)
            query_vec = _embedder.embed(query)
            search_results = self.vector_store.search(query_vec, top_k=8)
            seed_ids = {r[0] for r in search_results}
            # Keyword seeding: add claims sharing 3+ stemmed tokens with query
            query_tokens = set(_embedder._tokenize(query))
            for claim in self.claims:
                if claim.id not in seed_ids:
                    claim_tokens = set(_embedder._tokenize(claim.text))
                    if len(query_tokens & claim_tokens) >= 3:
                        seed_ids.add(claim.id)
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

        # BFS traversal with relevance filter
        visited = set(seed_ids)
        frontier = set(seed_ids)
        _bfs_query_tokens = set(_embedder._tokenize(query)) if _embedder else set()

        for _ in range(hops):
            next_frontier: set[str] = set()
            for claim_id in frontier:
                claim = claim_by_id.get(claim_id)
                if not claim:
                    continue
                # Skip expansion from claims sharing zero query tokens
                if _bfs_query_tokens:
                    claim_tokens = set(_embedder._tokenize(claim.text))
                    if not (_bfs_query_tokens & claim_tokens):
                        continue
                # Follow evidence pointers to find co-located claims
                for ev in claim.evidence:
                    related = su_to_claims.get(ev.source_unit_id, [])
                    for related_id in related:
                        if related_id not in visited:
                            next_frontier.add(related_id)
                            visited.add(related_id)
            frontier = next_frontier

        return [claim_by_id[cid] for cid in visited if cid in claim_by_id]


def verify(archive_path: str | Path) -> VerificationResult:
    """Verify archive integrity — digests, schema, references."""
    cas = ContentAddressedStore(Path(archive_path))
    return cas.verify_archive()


def load(
    archive_path: str | Path,
    layers: Optional[list[str]] = None,
    task: Optional[str] = None,
    expected_min_version: Optional[str] = None,
) -> LoadedArchive:
    """Load and optionally filter archive content.

    Args:
        archive_path: Path to archive directory
        layers: Specific layers to load (e.g., ["claims", "decisions"])
        task: Task description for selective loading via embeddings
        expected_min_version: Minimum version for rollback protection
    """
    archive_path = Path(archive_path)
    cas = ContentAddressedStore(archive_path)

    # Read and validate manifest
    manifest = read_manifest_from_cas(cas)
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

        data = json.loads(blob_data)

        if layer.type == "semantic.source_units":
            loaded.source_units = [TextUnit.from_dict(d) for d in data]
        elif layer.type == "semantic.claims":
            loaded.claims = [Claim.from_dict(d) for d in data]
        elif layer.type == "semantic.decisions":
            loaded.decisions = [Decision.from_dict(d) for d in data]
        elif layer.type == "index.embeddings":
            loaded.vector_store = VectorStore.from_dict(data)

    # Task-based filtering: use embeddings to select relevant claims
    if task and loaded.vector_store and loaded.claims:
        loaded.claims = _filter_by_task(loaded, task)

    return loaded


def _filter_by_task(loaded: LoadedArchive, task: str) -> list[Claim]:
    """Filter claims by task relevance using hybrid keyword + vector scoring."""
    if not loaded.vector_store or loaded.vector_store.vectors is None:
        return loaded.claims

    # Prefer restored embedder (aligned with build-time vocabulary)
    embedder = loaded.vector_store.restore_embedder()
    if embedder is None:
        embedder = get_embedder(dimensions=256)
        all_texts = [c.text for c in loaded.claims]
        if all_texts:
            embedder.fit(all_texts)
    query_vec = embedder.embed(task)

    # Get vector similarity scores for all claims
    raw_results = loaded.vector_store.search(query_vec, top_k=len(loaded.claims))

    # Compute keyword overlap boost using stemmed tokens
    query_tokens = set(embedder._tokenize(task))

    scored: list[tuple[str, float, str]] = []
    for cid, vscore, text in raw_results:
        claim_tokens = set(embedder._tokenize(text))
        overlap = len(query_tokens & claim_tokens)
        # Keyword boost: fraction of query terms found in claim
        kw_boost = overlap / len(query_tokens) if query_tokens else 0.0
        # Hybrid score: vector similarity + keyword overlap (weighted)
        hybrid = vscore + 0.3 * kw_boost
        scored.append((cid, hybrid, text))

    # Sort by hybrid score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Take top-k with minimum score threshold
    MIN_SCORE = 0.15
    TOP_K = min(8, max(3, len(loaded.claims) // 10))
    results = [(cid, s, t) for cid, s, t in scored[:TOP_K] if s >= MIN_SCORE]
    if not results and scored:
        results = scored[:3]

    relevant_ids = {r[0] for r in results}

    # Score lookup for expansion gating — every claim already has a
    # hybrid score from the vector+keyword pass above.
    score_by_id = {cid: s for cid, s, _ in scored}
    EXPANSION_MIN = 0.10  # softer than primary MIN_SCORE

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
    _STOP_WORDS = {
        'the', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 'to', 'for',
        'of', 'and', 'or', 'an', 'be', 'by', 'it', 'do', 'no', 'not',
        'what', 'how', 'which', 'who', 'when', 'where', 'why', 'that',
        'this', 'with', 'from', 'has', 'have', 'does', 'did', 'will',
        'can', 'should', 'would', 'could', 'may', 'use', 'used',
    }
    content_query_tokens = query_tokens - _STOP_WORDS
    if loaded.source_units and content_query_tokens:
        for tu in loaded.source_units:
            tu_tokens = set(embedder._tokenize(tu.content))
            if len(content_query_tokens & tu_tokens) >= 3:
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

    return selected


def restore_sources(
    archive_path: str | Path,
    output_dir: str | Path,
) -> dict:
    """Restore original source files from archive.

    Reads the source-units layer, retrieves content blobs, and writes
    files to output_dir preserving relative paths from resource locators.

    Returns:
        {restored_files: list[str], total_bytes: int}
    """
    archive_path = Path(archive_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cas = ContentAddressedStore(archive_path)
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

        # Write to output preserving relative path
        out_path = output_dir / locator
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")

        restored_files.append(locator)
        total_bytes += len(content.encode("utf-8"))

    return {
        "restored_files": sorted(restored_files),
        "total_bytes": total_bytes,
    }


def _version_lt(a: str, b: str) -> bool:
    """Simple semantic version comparison (a < b)."""
    try:
        va = tuple(int(x) for x in a.split("."))
        vb = tuple(int(x) for x in b.split("."))
        return va < vb
    except (ValueError, AttributeError):
        return a < b
