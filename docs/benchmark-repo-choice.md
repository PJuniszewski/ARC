# Benchmark Repo Choice: Why FastAPI

## Selection Criteria

The benchmark repo must:

1. Be fully ingestible (~10-20K LOC, not >100K)
2. Be 100% covered by ARC's chunkers (markdown + Python)
3. Have rich cross-file architecture (multi-hop reasoning opportunities)
4. Have documented design decisions (tests *why*, not just *how*)
5. Be stable and well-known (reproducible results)

## Candidates Evaluated

| Repo | LOC | Languages | Cross-file depth | Decision docs | Verdict |
|------|-----|-----------|-----------------|---------------|---------|
| **FastAPI** | ~15K | Python + MD | High (DI → routing → OpenAPI) | Extensive docs/ | **Selected** |
| Django | ~300K | Python | Very high | Good | **Added** — scaling target for scoped retrieval |
| LangChain | ~50K | Python + TS | Medium | Sparse | Too unstable — API changes weekly |
| nanoclaw | ~500 | Python | Low | None | Too small — trivial retrieval |
| Flask | ~8K | Python | Medium | Moderate | Viable but less architectural depth |
| httpx | ~12K | Python | Medium | Moderate | Viable but less well-documented |

## Why FastAPI Wins

### Size

~15K LOC Python is fully ingestible without sampling. Every file goes through ARC's pipeline. This means results reflect the complete archive, not a subset.

### Chunker Coverage

FastAPI is Python source + Markdown documentation — the exact file types ARC's `_chunk_python` and `_chunk_markdown` handle. No JS/TS/YAML edge cases that would confuse results.

### Cross-File Architecture

FastAPI has deep cross-file chains:

- Dependency injection: `params.py` → `dependencies/utils.py` → `dependencies/models.py` → `routing.py`
- OpenAPI generation: `routing.py` → `openapi/utils.py` → `openapi/models.py` → `_compat.py`
- Security: `security/oauth2.py` → `dependencies/utils.py` → `routing.py` → `openapi/utils.py`
- Response lifecycle: `routing.py` → `encoders.py` → `responses.py` → middleware stack

These chains require multi-hop reasoning — exactly where ARC's evidence graph should shine.

### Design Documentation

FastAPI's documentation explicitly explains *why* design choices were made:

- Why Starlette as the ASGI base
- Why Pydantic for validation
- Why OpenAPI 3.1.0 instead of 3.0.x
- Why declaration-order route matching

This enables "decisions/constraints" category tasks with verifiable ground truth.

## Django as Scaling Target

Django (~300K LOC) was added as the second benchmark repo to validate scoped retrieval at 20x FastAPI scale.

### Why Django

- **Clear directory boundaries**: `django/db/`, `django/template/`, `django/contrib/auth/` etc. — ideal for scope inference testing
- **Deep cross-file chains**: ORM (query.py → sql/query.py → sql/compiler.py → lookups.py), auth (views.py → __init__.py → backends.py → middleware.py → sessions)
- **Rich design decisions**: Active Record pattern, template engine philosophy, WSGI-first with incremental async, migration system design
- **Stable release**: Tag 5.1 provides a reproducible snapshot
- **Known quantity**: Widely understood architecture enables task validation

### Django Benchmark Tasks

30 tasks across 6 categories: architecture (5), feature_behavior (5), implementation_location (5), cross_file_reasoning (5), decisions_constraints (5), security_config (5).

- Cross-file: 22/30 (73%)
- Hard: 15, Medium: 12, Easy: 3
- Smoke tasks: 5 (one per non-security category)

### Django Benchmark Constraints

- **Not in CI**: Django snapshot is too large for PR smoke tests. Manual runs only.
- **Embedding build time**: Expected ~10x longer than FastAPI due to corpus size. Cache module helps for repeated runs.
- **Task file paths**: Validated against Django 5.1 source structure. Must be re-checked if tag changes.

## Snapshot Strategy

- Pin to tag `0.115.0` (stable release, September 2024)
- Exclude `tests/` (repetitive test cases would pollute claims)
- Exclude `docs_src/` (example code duplicates concepts in the source)
- Clone via `scripts/setup_fastapi_snapshot.py`
- Snapshot stored in `eval/large_repo_data/fastapi/` (gitignored)
