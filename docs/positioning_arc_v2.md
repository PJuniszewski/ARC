# ARC v2 Positioning: Honest Assessment

## What ARC Is

ARC is a **post-retrieval trust and compression layer**. It sits between a retrieval system (hybrid vector + keyword search) and the consumer (LLM, agent, human). It takes raw retrieval chunks and produces:

1. **Structured items** with source_type classification (code vs docs)
2. **Evidence maps** linking every output item to source file + line span
3. **Compressed context** via claim extraction and deduplication
4. **Task-aware refinement** adapting to query type (implementation, decision, cross-file, etc.)

## What ARC Is Not

- **Not a replacement for hybrid retrieval.** Hybrid retrieval (vector + keyword + heading boost) remains the best system for raw recall. ARC refines its output, it does not replace it.
- **Not a vector database.** ARC uses embeddings for retrieval but its value is in the post-retrieval refinement, not the retrieval itself.
- **Not a memory system.** ARC packages context into verifiable artifacts. It does not store conversation history or session state.
- **Not magic compression.** Claim extraction is lossy for certain content types (reasoning prose, implicit design decisions). The compression/recall tradeoff is real.

## Where ARC Wins

### Traceability (1.000 vs 0.000)
Every item in ARC's output has a source file and line span. No other system provides this. When an agent cites "FastAPI uses Pydantic for validation", ARC can point to `docs/tutorial/body.md:12-15`. This enables:
- Audit trails for compliance
- "Show me the source" debugging
- Confidence calibration based on source quality

### Debuggability (0.817 vs 0.000)
ARC outputs include source_type, confidence scores, and evidence pointers. When something goes wrong, you can inspect the evidence chain. Other systems return opaque text chunks.

### Token Efficiency
ARC loads 73% fewer tokens than hybrid for equivalent tasks. On doc-heavy queries, reduction reaches 97% (feat-03: 14,977 → 412 tokens). This matters for:
- Cost (fewer input tokens = cheaper API calls)
- Latency (fewer tokens = faster processing)
- Context window management (more room for other context)

### Code-Heavy Tasks
ARC's code weighting (1.5-2.0x) surfaces implementation details that pure document retrieval underranks. On xfile-01, ARC achieves 0.80 recall vs hybrid's 0.40 by promoting code chunks containing `solve_dependencies` and `ModelField`.

## Where Hybrid Wins

### Raw Recall (0.663 vs 0.568)
Hybrid's 14.3% recall advantage comes from three sources:

1. **Reasoning prose** (decisions_constraints: 0.600 vs 0.350): "Why" questions need causal reasoning that claim extraction drops. "FastAPI chose Pydantic because..." is not a claim pattern.

2. **Implementation identifiers** (implementation_location: 0.550 vs 0.450): Specific function names and file paths in raw chunks get lost when claims are extracted.

3. **Multi-file diversity** (security_config: 0.700 vs 0.600): Security tasks need evidence from 3-4 files; compression sometimes reduces to single-source items.

### Simplicity
Hybrid is a simpler system: retrieve chunks, return chunks. No classification, no extraction, no evidence map construction. Fewer moving parts = fewer failure modes.

## Benchmark Evidence

### System Comparison (30 tasks, FastAPI 0.115.0)

| Metric | TF-IDF | Vector | Hybrid | ARC | Hybrid_ARC |
|--------|--------|--------|--------|-----|------------|
| Context recall | 0.282 | 0.597 | **0.663** | 0.388 | 0.568 |
| Token efficiency | 0.999 | 0.998 | 0.993 | 0.998 | **0.998** |
| Traceability | 0.000 | 0.000 | 0.000 | **1.000** | **1.000** |
| Debuggability | 0.000 | 0.000 | 0.000 | 0.000 | **0.817** |
| Avg tokens loaded | 646 | 1,133 | 5,350 | 345 | 1,420 |

### Per-Category Recall

| Category | Hybrid | Hybrid_ARC | Delta | Notes |
|----------|--------|-----------|-------|-------|
| feature_behavior | 0.750 | 0.750 | 0.0% | Tie |
| architecture | 0.700 | 0.650 | -7.1% | Code weighting partially compensates |
| cross_file_reasoning | 0.680 | 0.610 | -10.3% | Multi-file diversity loss |
| security_config | 0.700 | 0.600 | -14.3% | Evidence compression |
| implementation_location | 0.550 | 0.450 | -18.2% | Identifier loss |
| decisions_constraints | 0.600 | 0.350 | -41.7% | Reasoning not claim-extractable |

### Effect Sizes (Cohen's d)

| Comparison | d | Interpretation |
|-----------|---|---------------|
| hybrid_arc vs tfidf | +1.09 | Large improvement |
| hybrid_arc vs arc | +0.68 | Medium improvement |
| hybrid_arc vs vector | -0.11 | Negligible difference |
| hybrid_arc vs hybrid | -0.38 | Small disadvantage |

## Recommended Use

### Use Hybrid_ARC when:
- You need **audit trails** — every fact traceable to source
- You need **debuggable context** — inspect why the agent got specific information
- **Token budget matters** — 73% reduction frees context window for other uses
- **Code understanding** is the primary task — code weighting helps
- **Compliance** requires provenance for generated outputs

### Use Hybrid when:
- **Raw recall is the priority** and you don't need provenance
- **Decision/reasoning queries** are common ("why did we choose X?")
- **Simplicity** is valued over structure
- Token budget is not a concern

### Use both:
- Hybrid for retrieval, ARC for post-processing
- This is exactly what hybrid_arc does: hybrid retrieval → ARC refinement
- The combination gives you most of hybrid's recall with ARC's traceability

## Limitations

1. **Single benchmark repo**: All numbers are from FastAPI 0.115.0. Different codebases (different code/docs ratios, languages, documentation styles) may produce different results.
2. **Regex-based extraction**: Claim extraction uses pattern matching, not LLM. This is fast (~1ms/query) but misses nuanced content.
3. **30 tasks**: Small sample size. Per-category conclusions based on 5 tasks each. Statistical power is limited.
4. **English only**: All tasks and content are English. No multilingual evaluation.
5. **Lexical recall metric**: `recall_at_k` uses keyword matching against required_facts. Semantic equivalents that use different words are not captured.

See `docs/benchmark-limitations.md` for full limitations discussion.
