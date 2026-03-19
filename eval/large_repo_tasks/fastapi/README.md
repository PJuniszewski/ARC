# Large-Repo Benchmark Tasks

## Overview

30 hand-authored tasks for evaluating ARC's retrieval pipeline on FastAPI (~15K LOC).

## Task Schema

Each task includes:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (category prefix + number) |
| `category` | string | One of 6 categories (see below) |
| `question` | string | The query to evaluate |
| `answer` | string | Ground-truth answer (2-5 sentences) |
| `relevant_keywords` | string[] | Keywords that should appear in retrieved context |
| `relevant_files` | string[] | Source files containing the answer |
| `required_facts` | string[] | Atomic facts the retrieval must surface |
| `difficulty` | string | easy, medium, or hard |
| `requires_cross_file` | boolean | Whether the answer spans multiple files |
| `smoke_task` | boolean | Included in CI smoke run (5 tasks) |

## Categories (6)

| Category | Count | Focus | Cross-file |
|----------|-------|-------|------------|
| architecture | 5 | System design, dependency injection, lifecycle | 4/5 |
| feature_behavior | 5 | Runtime behavior of specific features | 2/5 |
| implementation_location | 5 | Where specific logic lives in the codebase | 2/5 |
| cross_file_reasoning | 5 | Multi-hop chains spanning 3+ files | 5/5 |
| decisions_constraints | 5 | Design rationale and tradeoffs | 3/5 |
| security_config | 5 | Security and configuration patterns | 3/5 |

## Difficulty Distribution

- **easy** / **easy-medium**: 4 tasks — single-file location questions
- **medium**: 12 tasks — feature behavior, some cross-file
- **hard**: 14 tasks — cross-file architecture, security chains

## Smoke Tasks (5)

One per non-security category, selected for diversity:

1. `arch-04`: Middleware stack integration (architecture)
2. `feat-02`: response_model filtering (feature behavior)
3. `loc-01`: OpenAPI schema generation location (implementation)
4. `xfile-02`: Exception handler + middleware interaction (cross-file)
5. `dec-04`: OpenAPI 3.1.0 choice rationale (decisions)

## Authoring Methodology

Tasks were authored by:

1. Reading FastAPI 0.115.0 source code
2. Identifying architectural questions that require understanding code structure
3. Writing ground-truth answers verified against actual source files
4. Selecting `relevant_files` that contain the answer
5. Extracting `required_facts` as atomic claims that must appear in retrieval
6. Classifying difficulty based on number of files and reasoning hops required

## Constraints Met

- 19 of 30 tasks require cross-file reasoning (>= 10 required)
- 14 tasks are "hard" difficulty (>= 10 required)
- 5 tasks marked as smoke tasks for CI
- All `relevant_files` paths verified against FastAPI 0.115.0 source tree
