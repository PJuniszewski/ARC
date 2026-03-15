# Provenance and Trust

## Build Provenance

Every ARC archive records who built it, when, and from what sources. The provenance record includes:
- Builder version and identifier
- Build timestamp
- Complete source inventory with digests
- Build parameters used

Provenance enables consumers to verify that the archive was built according to expected standards and from trusted sources.

## Attestation Model

Attestations provide cryptographic proof of build properties. The recommended format follows in-toto conventions where predicates describe specific properties of the build process. This allows third parties to verify claims about the archive without trusting the builder.

## Trust Chain

The trust chain flows from source to consumer:
1. Sources are ingested and their digests recorded
2. The builder processes sources and records its parameters
3. The archive manifest covers all content with a root digest
4. Signatures attest to the manifest's authenticity
5. The loader verifies all signatures and digests before mounting

Breaking any link in this chain should produce a clear verification failure.
