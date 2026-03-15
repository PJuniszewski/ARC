# Security Model

## Threat Categories

The ARC security model addresses four primary threat categories:

1. **Prompt injection**: Malicious content in source documents that could be interpreted as instructions by the agent. ARC mitigates this by treating all source content as data, not instructions.

2. **Archive poisoning**: Insertion of false claims or corrupted embeddings into the archive. ARC detects this through content-addressed storage and manifest verification.

3. **Rollback attacks**: Forcing the agent to use an outdated archive version. ARC prevents this through version tracking and minimum version enforcement.

4. **Stale context**: Using outdated information that no longer reflects reality. ARC addresses this through freshness metadata and provenance timestamps.

## Integrity Verification

Archive integrity is verified at multiple levels:
- Individual blob digests are checked against SHA-256 hashes
- The manifest root digest covers all layer references
- Provenance records track the complete build chain
- Signatures can attest to builder identity and build parameters

## Trust Boundaries

Trust must be evaluated at each transition in the pipeline:
- Source → Builder: Was the source trustworthy?
- Builder → Archive: Was the build policy-compliant?
- Archive → Loader: Was the archive tampered with?
- Loader → Runtime: Was the mounted subset complete and current?

Each boundary requires explicit verification rather than implicit trust.
