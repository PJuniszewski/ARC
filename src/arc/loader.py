"""Loader — verify, resolve, and selectively mount archive content."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .cas import ContentAddressedStore, VerificationResult
from .embeddings import TfidfEmbedder, VectorStore
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
        if self.vector_store and self.vector_store.vectors is not None:
            embedder = TfidfEmbedder(dimensions=256)
            all_texts = [c.text for c in self.claims]
            if all_texts:
                embedder.fit(all_texts)
            query_vec = embedder.embed(query)
            search_results = self.vector_store.search(query_vec, top_k=5)
            seed_ids = {r[0] for r in search_results}
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

        # BFS traversal
        visited = set(seed_ids)
        frontier = set(seed_ids)

        for _ in range(hops):
            next_frontier: set[str] = set()
            for claim_id in frontier:
                claim = claim_by_id.get(claim_id)
                if not claim:
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

    # Build embedder from loaded claims
    embedder = TfidfEmbedder(dimensions=256)
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
    MIN_SCORE = 0.10
    top_k = max(3, len(loaded.claims) // 5)  # ~20% not 33%
    results = [(cid, s, t) for cid, s, t in scored[:top_k] if s >= MIN_SCORE]
    if not results and scored:
        results = scored[:3]

    relevant_ids = {r[0] for r in results}

    # Include claims found by search + any high-confidence claims
    claim_by_id = {c.id: c for c in loaded.claims}
    selected = []
    seen = set()

    # Add hybrid-scored matches
    for cid in relevant_ids:
        if cid in claim_by_id and cid not in seen:
            selected.append(claim_by_id[cid])
            seen.add(cid)

    # Add requirements (always relevant)
    for claim in loaded.claims:
        if claim.kind == "requirement" and claim.id not in seen:
            selected.append(claim)
            seen.add(claim.id)

    return selected


def _version_lt(a: str, b: str) -> bool:
    """Simple semantic version comparison (a < b)."""
    try:
        va = tuple(int(x) for x in a.split("."))
        vb = tuple(int(x) for x in b.split("."))
        return va < vb
    except (ValueError, AttributeError):
        return a < b
