# Evaluation Plan

## What must be proven

ARC is only worth building if it measurably improves one or more of these:

- context quality
- fidelity under compression
- agent reliability
- security and trust
- cost / latency efficiency

---

## Evaluation categories

### 1. Format correctness

Questions:
- can archives be parsed deterministically?
- can manifests be validated?
- can missing / tampered blobs be detected?

### 2. Compression fidelity

Questions:
- do claims preserve meaning?
- do summaries omit critical facts?
- does semantic compression degrade task performance?

### 3. Retrieval and task usefulness

Questions:
- does selective mount outperform naive full-context stuffing?
- does mounted context improve precision/recall of relevant evidence?

### 4. Trust and security

Questions:
- is tampering detected?
- are stale versions rejected?
- are poisoned inputs traceable?
- can prompt injection in sources be contained?

### 5. Developer ergonomics

Questions:
- can builders produce archives without pain?
- can operators inspect and diff archives easily?
- is the model simple enough to debug?

---

## Suggested benchmarks

### Long-context question answering
Use long-context tasks to compare:
- raw retrieval baseline
- compressed ARC claims only
- ARC claims + evidence
- ARC claims + evidence + selective mount hints

### Multi-hop reasoning
Test whether graph or claim structures help more than plain retrieval.

### Repo-level code tasks
Evaluate whether repo-focused ARC archives help code understanding and change analysis.

### Trust tests
- tamper single blob
- change manifest digest
- downgrade archive version
- inject malicious policy data

---

## Metrics to capture

### Functional
- task success rate
- evidence grounding rate
- hallucination rate relative to archive evidence

### Retrieval
- context precision
- context recall
- top-k evidence hit rate

### Fidelity
- semantic similarity to reference
- factual consistency against source evidence
- contradiction count in claims

### Cost / performance
- build time
- load time
- token count reduction
- average mounted bytes per task

### Security
- tamper detection rate
- rollback detection rate
- poisoned-source detection or containment rate

---

## Minimal evaluation harness for MVP

Run these first:

1. build archive from a fixed fixture corpus
2. verify archive integrity
3. diff old/new archive after one fixture change
4. task with raw retrieval baseline
5. same task with ARC selective load
6. tamper test
7. stale-version test

---

## Anti-bullshit rule

Do not report vague “felt better” results.
Report before/after numbers or do not report a win.

