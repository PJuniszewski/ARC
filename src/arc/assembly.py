"""Shared archive assembly — serialize layers to CAS blobs."""

from __future__ import annotations

import json
from typing import Optional

from .cas import ContentAddressedStore
from .embeddings import VectorStore, get_embedder
from .manifest import build_manifest, write_manifest_to_cas
from .models import Claim, Decision, Layer, Manifest, Resource, TextUnit, ToolDeclaration, PolicyRule, WorkflowStep


def assemble_archive(
    cas: ContentAddressedStore,
    claims: list[Claim],
    resources: list[Resource] | None = None,
    source_units: list[TextUnit] | None = None,
    decisions: list[Decision] | None = None,
    tools: list[ToolDeclaration] | None = None,
    policies: list[PolicyRule] | None = None,
    workflow: list[WorkflowStep] | None = None,
    archive_id: str = "",
    archive_version: str = "1.0.0",
    provenance: dict | None = None,
    parent_archive: str | None = None,
    force_tfidf: bool = True,
    import_graph_dict: dict | None = None,
) -> Manifest:
    """Assemble layers into CAS and write manifest.

    Shared by snapshot, merge, and the programmatic create_archive API.
    The caller is responsible for calling cas.initialize() first.
    """
    resources = resources or []
    source_units = source_units or []
    decisions = decisions or []
    tools = tools or []
    policies = policies or []
    workflow = workflow or []

    layers: list[Layer] = []

    # Resources layer
    if resources:
        data = json.dumps([r.to_dict() for r in resources], indent=2, sort_keys=True).encode()
        layers.append(Layer(name="resources", type="semantic.resources",
                            digest=cas.store_blob(data), required=True))

    # Source units layer
    if source_units:
        data = json.dumps([tu.to_dict() for tu in source_units], indent=2, sort_keys=True).encode()
        layers.append(Layer(name="source-units", type="semantic.source_units",
                            digest=cas.store_blob(data), required=True,
                            depends_on=["resources"] if resources else []))

    # Claims layer
    claims_data = json.dumps([c.to_dict() for c in claims], indent=2, sort_keys=True).encode()
    layers.append(Layer(name="claims", type="semantic.claims",
                        digest=cas.store_blob(claims_data), required=True,
                        depends_on=["source-units"] if source_units else []))

    # Decisions layer
    if decisions:
        data = json.dumps([d.to_dict() for d in decisions], indent=2, sort_keys=True).encode()
        layers.append(Layer(name="decisions", type="semantic.decisions",
                            digest=cas.store_blob(data), required=False,
                            depends_on=["source-units"] if source_units else []))

    # Embeddings
    embed_texts = [c.text for c in claims] + [f"{d.title} {d.context}" for d in decisions]
    if embed_texts:
        embedder = get_embedder(dimensions=256, force_tfidf=force_tfidf)
        embedder.fit(embed_texts)

        vs = VectorStore(index_info=embedder.get_index_info())
        if hasattr(embedder, "vocab") and hasattr(embedder, "idf"):
            vs.embedder_state = {
                "vocab": embedder.vocab,
                "idf": {k: round(v, 6) for k, v in embedder.idf.items()},
                "dimensions": embedder.dimensions,
            }
        for c in claims:
            vec = embedder.embed(c.text)
            vs.add(c.id, vec, c.text, {"kind": c.kind})
        for d in decisions:
            vec = embedder.embed(f"{d.title} {d.context}")
            vs.add(d.id, vec, d.title, {"kind": "decision"})

        emb_data = json.dumps(vs.to_dict(), sort_keys=True).encode()
        layers.append(Layer(name="embeddings", type="index.embeddings",
                            digest=cas.store_blob(emb_data), required=False,
                            depends_on=["claims"]))

    # Import graph
    if import_graph_dict:
        ig_data = json.dumps(import_graph_dict, sort_keys=True).encode()
        layers.append(Layer(name="import-graph", type="graph.imports",
                            digest=cas.store_blob(ig_data), required=False,
                            depends_on=["resources"]))

    # Operational layers
    if tools:
        data = json.dumps([t.to_dict() for t in tools], indent=2, sort_keys=True).encode()
        layers.append(Layer(name="tools", type="operational.tools",
                            digest=cas.store_blob(data), required=False))
    if policies:
        data = json.dumps([p.to_dict() for p in policies], indent=2, sort_keys=True).encode()
        layers.append(Layer(name="policy", type="operational.policy",
                            digest=cas.store_blob(data), required=False))
    if workflow:
        data = json.dumps([w.to_dict() for w in workflow], indent=2, sort_keys=True).encode()
        layers.append(Layer(name="workflow", type="operational.workflow",
                            digest=cas.store_blob(data), required=False))

    # Manifest
    manifest = build_manifest(
        layers=layers,
        archive_id=archive_id,
        archive_version=archive_version,
        provenance=provenance or {},
        parent_archive=parent_archive,
    )
    write_manifest_to_cas(manifest, cas)
    return manifest


def validate_evidence(claims: list[Claim], su_ids: set[str]) -> list[str]:
    """Check that all evidence pointers reference existing source units.

    Returns list of warnings for dangling pointers.
    """
    warnings: list[str] = []
    for c in claims:
        for ep in c.evidence:
            if ep.source_unit_id and ep.source_unit_id not in su_ids:
                warnings.append(
                    f"claim {c.id[:8]} references missing source unit {ep.source_unit_id[:8]}"
                )
        if c.derived_from and c.derived_from not in su_ids:
            warnings.append(
                f"claim {c.id[:8]} derived_from missing source unit {c.derived_from[:8]}"
            )
    return warnings
