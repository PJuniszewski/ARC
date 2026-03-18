# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-18

### Added
- Reasoning detection module (`src/arc/reasoning.py`) for boosting reasoning-bearing chunks in refinement
- `reasoning_boost` field on `RefinementMode` — additive confidence boost for decision/security/cross_file modes
- `--categories` flag on benchmark runner for targeted evaluation
- Large-repo benchmark infrastructure: 30 tasks x 5 systems, lexical + RAGAS metrics
- Hybrid+ARC post-retrieval refinement system (hybrid_arc)
- Task-aware refinement modes: implementation/decision/cross_file/feature/security/balanced

### Changed
- decisions_constraints recall improved 0.400 → 0.500 via reasoning boost
- hybrid_arc overall recall 0.660 (Cohen's d = -0.014 vs hybrid, negligible)
- 65% token reduction vs hybrid with full evidence traceability
- security mode passthrough_k 3 → 4 for multi-file diversity

### Fixed
- Reasoning sentences ("because", "chose", "rather than") no longer dropped from refinement output

## [0.1.0-alpha] - 2026-03-17

### Added
- Content-addressed storage (CAS) with SHA-256 blob addressing
- 8-stage builder pipeline: ingest, normalize, chunk, extract, deduplicate, index, assemble, validate
- Manifest-driven archive composition with layer dependencies
- Semantic model: source units, claims, decisions with evidence pointers
- Claim deduplication and contested claim exclusion
- Hybrid vector + keyword selective loading with evidence graph expansion
- TF-IDF embedder (zero external deps) with optional sentence-transformers upgrade
- Operational layers: tools, policies, workflow steps (declarative storage)
- Archive verification with full Merkle integrity checking
- Archive diffing between versions
- Source file restoration from archives
- CLI commands: build, inspect, verify, load, diff, restore
- Rollback protection via version comparison
- Provenance metadata recording
- Structured logging throughout builder and loader
- Public API exports from `arc` package
- Comprehensive test suite (211+ tests)

### Current limitations
- Signatures and attestations: metadata model only, no cryptographic implementation
- Operational layers (tools, policies, workflows): stored but not enforced at load time
- Incremental builds: API exists but not tested at scale
- Single-file archive packaging: not yet implemented
