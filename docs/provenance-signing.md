# Provenance and Signing

## Goal

A consumer of an ARC archive should be able to answer:

- who built this?
- from what inputs?
- with what builder version and policy?
- has it been tampered with?
- is it the expected version?

If those answers are fuzzy, the trust model is weak.

---

## Trust chain model

### Build provenance
Describes:
- builder identity
- builder version
- build time
- source digests or source references
- configuration profile

### Artifact integrity
Describes:
- manifest digest
- blob digests
- relationship of manifest to blobs

### Signature layer
Describes:
- who signed the archive
- what exactly was signed
- when it was signed

### Update policy layer
Describes:
- whether this version is current enough
- whether downgrade is allowed
- whether key rotation is recognized

---

## Recommended v0 design

Sign the root manifest digest.

Why:
- stable trust anchor
- indirect coverage of all blobs referenced by manifest
- simpler verification model

Do not require every semantic object to be individually signed in v0.
That adds pain before it adds much value.

---

## Provenance record fields

Suggested minimum:

- build id
- builder name
- builder version
- source inventory
- build timestamp
- profile / mode
- extraction configuration reference
- semantic compression configuration reference

---

## Verification modes

### Integrity only
Checks digests and internal references.

### Signed archive
Checks integrity plus signature validity.

### Trusted provenance
Checks integrity, signature, provenance attestations, and update policy.

---

## Update safety

Need protection against:

- replay of older valid archive
- substitution of archive from wrong trust domain
- silent downgrade of signing or provenance policy

The loader should support policy such as:

- minimum accepted archive version
- minimum build timestamp
- required trust domain / signer set
- required attestation presence

---

## Design rule

Provenance is not just metadata.
It changes whether the archive should be trusted at all.

