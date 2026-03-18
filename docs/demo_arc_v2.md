# ARC v2 Demo: Post-Retrieval Refinement

Side-by-side comparison showing how hybrid_arc transforms raw hybrid retrieval output.

---

## Task 1: xfile-01 — "How do Pydantic models flow from request parsing to validation?"

**Recall: hybrid 0.40 → hybrid_arc 0.80** (refinement wins)

### Hybrid raw output

- 8 chunks, 4530 tokens loaded
- Mix of markdown docs and code, no structure
- No provenance — can't trace which file or line produced each chunk

```
Chunk 1: "FastAPI uses Pydantic models for all data validation..."  (docs)
Chunk 2: "class Body(BaseModel): ..."  (code, mixed with docs)
Chunk 3: "## Request Body\n\nWhen you need to send..."  (docs)
...
```

### Hybrid_ARC refined output

- 6 items, 3105 tokens loaded (31% fewer)
- Code chunks preserved verbatim with 1.5x ranking boost
- Doc chunks compressed to claims
- Every item has source file + line span

```
Item 1 [code]: "async def solve_dependencies(...): ..."
  → source: fastapi/dependencies/utils.py:258-340
  → type: code, confidence: 1.50

Item 2 [code]: "class ModelField: ..."
  → source: fastapi/params.py:15-89
  → type: code, confidence: 1.50

Item 3 [claim]: "FastAPI uses Pydantic models for all data validation
  and serialization of request and response bodies."
  → source: docs/tutorial/body.md:12-15
  → type: docs, confidence: 0.56

Item 4 [claim]: "Request body parameters are automatically validated
  against the Pydantic model schema."
  → source: docs/tutorial/body.md:45-48
  → type: docs, confidence: 0.56
```

**Why it works**: Code weighting (1.5x) surfaces the actual implementation (solve_dependencies, ModelField) that hybrid underranked behind documentation.

---

## Task 2: feat-03 — "How does BackgroundTasks execute tasks after the response?"

**Recall: hybrid 1.00 → hybrid_arc 1.00** (tie, but 94% fewer tokens)

### Hybrid raw output

- 8 chunks, 14977 tokens loaded
- Contains entire files and large doc sections
- Most tokens are noise (imports, unrelated methods)

### Hybrid_ARC refined output

- 2 items, 412 tokens loaded (97% fewer!)
- One code chunk (BackgroundTasks class, truncated to key methods)
- One claim about post-response execution

```
Item 1 [code]: "class BackgroundTasks(BackgroundTask):
    def add_task(self, func, *args, **kwargs): ..."
  → source: starlette/background.py:1-35
  → type: code, confidence: 1.50

Item 2 [claim]: "BackgroundTasks provides a way to run functions
  after the response has been sent to the client."
  → source: docs/tutorial/background-tasks.md:5-8
  → type: docs, confidence: 0.56
```

**Why it works**: Same recall, 97% fewer tokens. The claim + code chunk capture the essential information without the noise.

---

## Task 3: dec-02 — "Why does FastAPI require Pydantic for request/response models?"

**Recall: hybrid 0.50 → hybrid_arc 0.00** (refinement fails)

### Hybrid raw output

- 8 chunks, 3250 tokens
- Contains reasoning paragraphs about Pydantic choice

### Hybrid_ARC refined output

- 3 items, 253 tokens
- Only extracted claims about Pydantic features, not the *reasoning*

```
Item 1 [claim]: "Pydantic provides data validation using Python type
  annotations."
  → source: docs/features.md:20-22

Item 2 [claim]: "FastAPI uses Pydantic models for request body parsing."
  → source: docs/tutorial/body.md:5-7
```

**Why it fails**: The question asks *why* (design reasoning). `extract_claims()` captures factual assertions ("uses", "provides") but misses reasoning sentences like "Pydantic was chosen because it offers native Python type hint support with zero learning curve for existing Python developers."

**Fix needed**: Extend claim extraction patterns to match reasoning connectives (because, since, therefore, chosen over).

---

## Summary

| Metric | Task 1 (xfile-01) | Task 2 (feat-03) | Task 3 (dec-02) |
|--------|-------------------|-------------------|------------------|
| Hybrid recall | 0.40 | 1.00 | 0.50 |
| Hybrid_ARC recall | 0.80 | 1.00 | 0.00 |
| Hybrid tokens | 4,530 | 14,977 | 3,250 |
| Hybrid_ARC tokens | 3,105 | 412 | 253 |
| Token reduction | 31% | 97% | 92% |
| Traceable | No → Yes | No → Yes | No → Yes |
| Debuggable | No → Yes | No → Yes | No → Yes |

**Takeaway**: hybrid_arc excels at code-heavy tasks and compresses doc-heavy tasks dramatically. It struggles with "why" questions where reasoning doesn't match claim patterns. All outputs are fully traceable to source files and line spans.
