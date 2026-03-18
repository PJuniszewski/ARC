# ARC — Makefile for benchmark and development tasks

.PHONY: test lint benchmark-setup benchmark-smoke benchmark-full benchmark-ragas clean

# ── Development ───────────────────────────────────────────────────

test:
	pytest tests/ -x -q --ignore=tests/test_external_retrieval.py --ignore=tests/test_fidelity_metrics.py -m "not ml and not llm and not eval"

lint:
	ruff check src/ tests/ eval/ scripts/

# ── Large-Repo Benchmark ─────────────────────────────────────────

benchmark-setup:
	python scripts/setup_fastapi_snapshot.py

benchmark-smoke: benchmark-setup
	python scripts/run_large_repo_benchmark.py --mode=smoke

benchmark-full: benchmark-setup
	python scripts/run_large_repo_benchmark.py --mode=full

benchmark-ragas: benchmark-setup
	python scripts/run_large_repo_benchmark.py --mode=ragas

# ── Cleanup ───────────────────────────────────────────────────────

clean:
	rm -rf eval/large_repo_data/fastapi/
	rm -rf reports/fastapi.arc/
	rm -f reports/large-repo-results.json reports/large-repo-summary.md
