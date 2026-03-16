"""Builder pipeline — 8-stage: ingest → normalize → chunk → extract → deduplicate → index → assemble → validate."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .cas import ContentAddressedStore, sha256_digest
from .compressor import DeduplicationResult, deduplicate_claims
from .embeddings import TfidfEmbedder, VectorStore, get_embedder
from .extractor import extract_claims, extract_decisions
from .manifest import build_manifest, validate_manifest, write_manifest_to_cas
from .models import (
    Claim,
    Decision,
    EvidencePointer,
    Layer,
    Manifest,
    Resource,
    TextUnit,
    _generate_id,
    _sha256,
)
from .provenance import BuildProvenance


@dataclass
class BuildResult:
    """Result of building an archive."""

    archive_path: str
    manifest: Manifest
    resources: list[Resource]
    text_units: list[TextUnit]
    claims: list[Claim]
    decisions: list[Decision]
    deduplication: Optional[DeduplicationResult] = None
    errors: list[str] = field(default_factory=list)
    valid: bool = True


def build_archive(
    source_dir: str | Path,
    output_dir: str | Path,
    archive_id: Optional[str] = None,
    archive_version: str = "0.1.0",
    parent_archive: Optional[str | Path] = None,
) -> BuildResult:
    """Build an ARC archive from source directory.

    8-stage pipeline:
    1. Ingest: scan source directory, create Resource objects
    2. Normalize: detect file types, extract structure
    3. Chunk: produce TextUnit objects with provenance
    4. Extract: claims and decisions
    5. Deduplicate: remove duplicate claims, exclude contested
    6. Index: generate embeddings
    7. Assemble: write blobs to CAS, build manifest
    8. Validate: verify all references
    """
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)

    if not archive_id:
        archive_id = f"arc://{source_dir.name}"

    # Initialize CAS
    cas = ContentAddressedStore(output_dir)
    cas.initialize()

    # Load parent CAS for incremental builds
    parent_cas = None
    if parent_archive:
        parent_cas = ContentAddressedStore(Path(parent_archive))

    # Initialize provenance
    provenance = BuildProvenance(parameters={
        "source_dir": str(source_dir),
    })

    # === Stage 1: Ingest ===
    resources = _ingest(source_dir, provenance)

    # === Stage 2 & 3: Normalize + Chunk ===
    text_units = _chunk(resources, source_dir)

    # === Stage 4: Extract ===
    claims = extract_claims(text_units)
    decisions = extract_decisions(text_units)

    # === Stage 5: Deduplicate ===
    dedup = deduplicate_claims(claims)
    deduped_claims = dedup.claims

    # === Stage 6: Index (embeddings) ===
    embedder = get_embedder(dimensions=256)
    all_texts = [tu.content for tu in text_units] + [c.text for c in deduped_claims]
    if all_texts:
        embedder.fit(all_texts)

    vector_store = VectorStore(index_info=embedder.get_index_info())
    if hasattr(embedder, 'vocab') and hasattr(embedder, 'idf'):
        vector_store.embedder_state = {
            "vocab": embedder.vocab,
            "idf": {k: round(v, 6) for k, v in embedder.idf.items()},
            "dimensions": embedder.dimensions,
        }
    for claim in deduped_claims:
        vec = embedder.embed(claim.text)
        vector_store.add(claim.id, vec, claim.text, {"kind": claim.kind})

    for decision in decisions:
        vec = embedder.embed(f"{decision.title} {decision.context}")
        vector_store.add(decision.id, vec, decision.title, {"kind": "decision"})

    # === Stage 7: Assemble ===
    layers = []

    # Source units layer
    su_data = json.dumps([tu.to_dict() for tu in text_units], indent=2, sort_keys=True).encode()
    su_digest = cas.store_blob(su_data)
    layers.append(Layer(
        name="source-units",
        type="semantic.source_units",
        digest=su_digest,
        required=True,
    ))

    # Claims layer (deduplicated)
    claims_data = json.dumps(
        [c.to_dict() for c in deduped_claims], indent=2, sort_keys=True
    ).encode()
    claims_digest = cas.store_blob(claims_data)
    layers.append(Layer(
        name="claims",
        type="semantic.claims",
        digest=claims_digest,
        required=True,
        depends_on=["source-units"],
    ))

    # Decisions layer
    if decisions:
        decisions_data = json.dumps(
            [d.to_dict() for d in decisions], indent=2, sort_keys=True
        ).encode()
        decisions_digest = cas.store_blob(decisions_data)
        layers.append(Layer(
            name="decisions",
            type="semantic.decisions",
            digest=decisions_digest,
            required=False,
            depends_on=["source-units"],
        ))

    # Embeddings layer
    embeddings_data = json.dumps(vector_store.to_dict(), sort_keys=True).encode()
    embeddings_digest = cas.store_blob(embeddings_data)
    layers.append(Layer(
        name="embeddings",
        type="index.embeddings",
        digest=embeddings_digest,
        required=False,
        depends_on=["claims"],
    ))

    # Provenance
    prov_data = json.dumps(provenance.to_dict(), indent=2, sort_keys=True).encode()
    cas.store_json(provenance.to_dict(), "provenance.json")

    # Parent reference for incremental builds
    parent_ref = None
    if parent_cas:
        parent_manifest = parent_cas.read_manifest()
        if parent_manifest:
            parent_ref = parent_manifest.get("root_digest")

    # Build manifest
    manifest = build_manifest(
        archive_id=archive_id,
        archive_version=archive_version,
        layers=layers,
        provenance=provenance.to_dict(),
        parent_archive=parent_ref,
    )

    # === Stage 8: Validate ===
    errors = validate_manifest(manifest)

    # Check all blob references exist
    for layer in layers:
        if not cas.has_blob(layer.digest):
            errors.append(f"Missing blob for layer '{layer.name}': {layer.digest}")

    # Check all evidence pointers reference valid source units
    su_ids = {tu.id for tu in text_units}
    for claim in deduped_claims:
        for ev in claim.evidence:
            if ev.source_unit_id not in su_ids:
                errors.append(f"Claim '{claim.id}' references unknown source unit '{ev.source_unit_id}'")

    if errors:
        return BuildResult(
            archive_path=str(output_dir),
            manifest=manifest,
            resources=resources,
            text_units=text_units,
            claims=deduped_claims,
            decisions=decisions,
            deduplication=dedup,
            errors=errors,
            valid=False,
        )

    # Write manifest
    write_manifest_to_cas(manifest, cas)

    return BuildResult(
        archive_path=str(output_dir),
        manifest=manifest,
        resources=resources,
        text_units=text_units,
        claims=deduped_claims,
        decisions=decisions,
        deduplication=dedup,
        valid=True,
    )


def _ingest(source_dir: Path, provenance: BuildProvenance) -> list[Resource]:
    """Stage 1: Scan source directory and create Resource objects."""
    resources = []
    extensions = {".md", ".txt", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml"}

    for root, _dirs, files in os.walk(source_dir):
        # Skip hidden directories
        root_path = Path(root)
        if any(part.startswith(".") for part in root_path.relative_to(source_dir).parts):
            continue

        for fname in sorted(files):
            fpath = root_path / fname
            if fpath.suffix not in extensions:
                continue

            content = fpath.read_bytes()
            digest = sha256_digest(content)

            kind = "document" if fpath.suffix in {".md", ".txt"} else "file"
            locator = str(fpath.relative_to(source_dir))
            resource = Resource(
                id=_generate_id(f"resource:{locator}"),
                kind=kind,
                locator=locator,
                content_digest=digest,
                metadata={"size": len(content), "extension": fpath.suffix},
            )
            resources.append(resource)
            provenance.add_source(resource.locator, digest, kind)

    return resources


def _chunk(resources: list[Resource], source_dir: Path) -> list[TextUnit]:
    """Stage 2 & 3: Normalize files and produce TextUnit objects."""
    text_units = []

    for resource in resources:
        fpath = source_dir / resource.locator
        if not fpath.exists():
            continue

        content = fpath.read_text(encoding="utf-8", errors="replace")
        ext = resource.metadata.get("extension", "")

        if ext in (".md", ".txt"):
            units = _chunk_markdown(content, resource.id)
        elif ext in (".py",):
            units = _chunk_python(content, resource.id)
        else:
            units = _chunk_generic(content, resource.id)

        text_units.extend(units)

    return text_units


def _chunk_markdown(content: str, resource_id: str) -> list[TextUnit]:
    """Chunk markdown by sections (## headers)."""
    units = []
    lines = content.split("\n")

    # Detect frontmatter
    if lines and lines[0].strip() == "---":
        end_idx = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx > 0:
            fm_content = "\n".join(lines[:end_idx + 1])
            units.append(TextUnit(
                id=_generate_id(),
                resource_id=resource_id,
                kind="frontmatter",
                content=fm_content,
                span=(1, end_idx + 1),
            ))
            lines = lines[end_idx + 1:]

    # Split by headers
    current_section: list[str] = []
    section_start = 1
    for i, line in enumerate(lines, start=1):
        if re.match(r'^#{1,3}\s+', line) and current_section:
            section_content = "\n".join(current_section).strip()
            if section_content and len(section_content) > 10:
                units.append(TextUnit(
                    id=_generate_id(),
                    resource_id=resource_id,
                    kind="section",
                    content=section_content,
                    span=(section_start, section_start + len(current_section) - 1),
                ))
            current_section = [line]
            section_start = i
        else:
            current_section.append(line)

    # Last section
    if current_section:
        section_content = "\n".join(current_section).strip()
        if section_content and len(section_content) > 10:
            units.append(TextUnit(
                id=_generate_id(),
                resource_id=resource_id,
                kind="section",
                content=section_content,
                span=(section_start, section_start + len(current_section) - 1),
            ))

    return units


def _chunk_python(content: str, resource_id: str) -> list[TextUnit]:
    """Chunk Python by top-level functions and classes."""
    units = []
    lines = content.split("\n")

    # Module docstring
    if content.strip().startswith('"""') or content.strip().startswith("'''"):
        quote = '"""' if content.strip().startswith('"""') else "'''"
        end = content.find(quote, content.find(quote) + 3)
        if end > 0:
            doc = content[:end + 3]
            units.append(TextUnit(
                id=_generate_id(),
                resource_id=resource_id,
                kind="docstring",
                content=doc,
                span=(1, doc.count("\n") + 1),
            ))

    # Top-level defs
    current_block: list[str] = []
    block_start = 1
    for i, line in enumerate(lines, start=1):
        if re.match(r'^(def |class |@)', line) and current_block:
            block_content = "\n".join(current_block).strip()
            if block_content and len(block_content) > 20:
                kind = "function" if any(l.startswith("def ") for l in current_block) else "section"
                units.append(TextUnit(
                    id=_generate_id(),
                    resource_id=resource_id,
                    kind=kind,
                    content=block_content,
                    span=(block_start, i - 1),
                ))
            current_block = [line]
            block_start = i
        else:
            current_block.append(line)

    if current_block:
        block_content = "\n".join(current_block).strip()
        if block_content and len(block_content) > 20:
            units.append(TextUnit(
                id=_generate_id(),
                resource_id=resource_id,
                kind="section",
                content=block_content,
                span=(block_start, block_start + len(current_block) - 1),
            ))

    return units


def _chunk_generic(content: str, resource_id: str) -> list[TextUnit]:
    """Chunk generic files by paragraph breaks."""
    paragraphs = re.split(r'\n\s*\n', content)
    units = []
    line_offset = 1
    for para in paragraphs:
        para = para.strip()
        if para and len(para) > 10:
            n_lines = para.count("\n") + 1
            units.append(TextUnit(
                id=_generate_id(),
                resource_id=resource_id,
                kind="paragraph",
                content=para,
                span=(line_offset, line_offset + n_lines - 1),
            ))
            line_offset += n_lines + 1
        else:
            line_offset += para.count("\n") + 2

    return units
