# MCP Benchmark Results

| Scenario | Result | Duration | Details |
|----------|--------|----------|---------|
| Sequential handoff (A → B) | PASS | 0.1s | 8 checks |
| Parallel merge (C + D) | PASS | 0.0s | 7 checks |
| Conflict detection (E vs F) | PASS | 0.0s | 4 checks |
| Chain handoff (G → H → I) | PASS | 0.0s | 5 checks |
| Performance | PASS | 0.1s | 19 checks |

## Sequential handoff (A → B)

- [+] build succeeds: claims=212
- [+] load returns claims: got 48 claims
- [+] snapshot A created: claims=3
- [+] snapshot A verifies: 
- [+] B can load A's snapshot: 
- [+] decision type preserved: found 1 decisions
- [+] source preserved: sources={'agent-a'}
- [+] snapshot B created: 

## Parallel merge (C + D)

- [+] snapshot C created: 
- [+] snapshot D created: 
- [+] merge succeeds: 
- [+] no data loss: merged=6, expected >=5 (3+3, dedup overlap)
- [+] both agents' decisions present: sources={'agent-c', 'agent-d'}
- [+] merged verifies: 
- [+] diff shows additions: new_claims=2

## Conflict detection (E vs F)

- [+] conflict detected: conflicts=1
- [+] conflict references both decisions: refs=['0aee3d963cc44a94', '0f64b367c475478c']
- [+] both observations preserved: observations=2
- [+] conflict loadable: 

## Chain handoff (G → H → I)

- [+] H loads G's findings: 
- [+] I loads H's artifact: 
- [+] G's observation survives in H's artifact: searched 4 claims
- [+] 3-hop traceability (G→H→I): searched 4 claims
- [+] claims grow across hops: I has 4 claims

## Performance

- [+] snapshot 10 claims: 0.00s
- [+] load 10 claims: 0.00s
- [+] verify 10 claims: 0.00s
- [+] size 10 claims: 40 KB
- [+] snapshot 50 claims: 0.01s
- [+] load 50 claims: 0.00s
- [+] verify 50 claims: 0.00s
- [+] size 50 claims: 108 KB
- [+] snapshot 100 claims: 0.01s
- [+] load 100 claims: 0.00s
- [+] verify 100 claims: 0.00s
- [+] size 100 claims: 200 KB
- [+] snapshot 500 claims: 0.03s
- [+] load 500 claims: 0.02s
- [+] verify 500 claims: 0.00s
- [+] size 500 claims: 920 KB
- [+] snapshot 100 under 2s: checked above
- [+] verify under 500ms: checked above
- [+] merge 10+50: 0.01s
