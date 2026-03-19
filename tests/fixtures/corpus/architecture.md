# Architecture Overview

## System Model

The ARC system uses a five-layer architecture that separates concerns between source ingestion, building, artifact storage, loading, and runtime execution.

The builder layer is responsible for ingesting raw sources, normalizing content, extracting semantic units, and producing content-addressed blobs. Each blob is immutable and identified by its SHA-256 hash.

The loader layer handles verification of archive integrity, resolution of layer dependencies, and selective mounting of task-relevant content. The loader must fail loudly on any integrity violation.

## Content Addressing

All blobs in ARC archives are content-addressed using SHA-256 digests. This provides natural tamper evidence — any modification to a blob changes its digest and invalidates the manifest. The architecture uses a Merkle DAG-like structure where the root manifest hash covers all layer digests.

## Selective Loading

The runtime should not load all archive content for every task. Instead, ARC supports selective mounting where only task-relevant layers and claims are loaded. This reduces context pollution and improves agent performance by providing focused, relevant information.

## Security Model

ARC treats security as a core requirement, not an afterthought. The threat model includes prompt injection through source materials, archive poisoning, rollback attacks, and stale context issues. Every blob must be verifiable, and the manifest provides a single root of trust.
