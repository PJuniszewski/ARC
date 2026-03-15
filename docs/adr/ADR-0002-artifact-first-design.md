# ADR-0002: Artifact-First Design

## Status
Accepted

## Context
Most agent memory systems are runtime-first. They persist state, but they do not create a portable artifact boundary.

## Decision
ARC will be designed artifact-first.

That means:
- the format is primary
- builders and loaders are separate concerns
- runtime integrations are secondary

## Consequences
This improves portability and trust, but forces more upfront schema discipline.

