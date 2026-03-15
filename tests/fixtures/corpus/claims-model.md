# Claims and Decisions Model

## Claims

A Claim is an atomic assertion extracted from one or more source units. Each claim has:
- A unique identifier
- The assertion text
- A kind (fact, assertion, requirement, definition)
- Evidence pointers linking back to source units
- A confidence score between 0 and 1
- A status: observed, derived, verified, deprecated, or contested

Claims must always have at least one evidence pointer. A claim without evidence is a violation of the archive contract.

## Decisions

A Decision records structured rationale for a choice. Each decision has:
- A title summarizing the decision
- Context explaining why the decision was needed
- Options that were considered
- The chosen decision
- Consequences of the decision
- Evidence pointers to supporting documents

Decision status can be: proposed, accepted, superseded, or rejected.

## Evidence Pointers

Evidence pointers create the traceability chain between claims/decisions and their source material. Each pointer references a source unit ID and optionally a line span within that unit. Weights can prioritize stronger evidence.

## Modeling Rules

The semantic model distinguishes between:
- Extracted facts (direct evidence, high confidence)
- Inferred summaries (derived, lower confidence)
- Accepted decisions (commitments with consequences)
- Unresolved hypotheses (proposed, pending verification)

This distinction is critical for agent reasoning — the agent should treat verified facts differently from contested claims.
