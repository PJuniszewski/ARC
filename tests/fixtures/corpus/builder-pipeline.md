# Builder Pipeline

## Overview

The ARC builder pipeline transforms raw source materials into a structured, verifiable archive through eight sequential stages.

## Pipeline Stages

### Stage 1: Source Ingestion

The builder scans the source directory and creates Resource objects for each supported file type. Supported formats include Markdown, Python, JavaScript, JSON, YAML, and plain text. Hidden directories are excluded.

### Stage 2: Normalization

Raw content is normalized into a consistent internal representation. Markdown files are split into sections by headers. Python files are split by top-level definitions. Other files are split by paragraph breaks.

### Stage 3: Chunking

Normalized content is divided into TextUnit objects. Each TextUnit maintains provenance — it knows which Resource it came from and what line range it covers. This provenance chain is essential for evidence tracing.

### Stage 4: Semantic Extraction

Claims and decisions are extracted from TextUnit content using pattern matching. Claims are identified by assertion patterns (statements containing "is", "should", "must", "requires"). Decisions are identified by ADR-style document structure (Context/Decision/Consequences sections).

### Stage 5: Semantic Compression

Extracted claims are ranked by TF-IDF importance and deduplicated. The compression budget controls what fraction of claims to retain. Requirements and definitions receive a ranking boost to ensure they survive compression.

### Stage 6: Embedding Index

TF-IDF or sentence-transformer embeddings are generated for all retained claims and decisions. These embeddings enable task-aware selective loading at runtime.

### Stage 7: Assembly

All content is written as content-addressed blobs. Layer objects are created pointing to blob digests. The manifest is assembled with all layers, provenance, and metadata.

### Stage 8: Validation

The builder validates all references — every evidence pointer must reference a valid source unit, every layer digest must correspond to an existing blob, and the manifest must pass schema validation. No orphan blobs or evidence-less claims are allowed.

## Anti-Patterns

The builder must never:
- Silently drop provenance information
- Generate claims without evidence pointers
- Mutate existing archive blobs in place
- Mix trusted and untrusted inputs without marking
