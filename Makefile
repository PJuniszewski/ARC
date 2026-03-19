# ARC (Agent Reasoning Context) — Makefile for development and benchmarks

.PHONY: test lint benchmark-setup benchmark-setup-django benchmark-smoke benchmark-smoke-django benchmark-full benchmark-full-django benchmark-ragas clean

# ── Development ───────────────────────────────────────────────────

test:
	pytest tests/ -x -q --ignore=tests/test_external_retrieval.py --ignore=tests/test_fidelity_metrics.py -m "not ml and not llm and not eval"

lint:
	ruff check src/ tests/ eval/ scripts/

# ── Large-Repo Benchmark ─────────────────────────────────────────
# Default systems: tfidf, vector, hybrid, arc, hybrid_arc
# scoped_arc excluded (experimental) — use --systems scoped_arc explicitly

benchmark-setup:
	python scripts/setup_fastapi_snapshot.py

benchmark-setup-django:
	python scripts/setup_fastapi_snapshot.py --config eval/large_repo_tasks/django/REPO_CONFIG.json

benchmark-smoke: benchmark-setup
	python scripts/run_large_repo_benchmark.py --mode=smoke --repo=fastapi

benchmark-smoke-django: benchmark-setup-django
	python scripts/run_large_repo_benchmark.py --mode=smoke --repo=django

benchmark-full: benchmark-setup
	python scripts/run_large_repo_benchmark.py --mode=full --repo=fastapi

benchmark-full-django: benchmark-setup-django
	python scripts/run_large_repo_benchmark.py --mode=full --repo=django

benchmark-ragas: benchmark-setup
	python scripts/run_large_repo_benchmark.py --mode=ragas --repo=fastapi

# ── Cleanup ───────────────────────────────────────────────────────

clean:
	rm -rf eval/large_repo_data/fastapi/ eval/large_repo_data/django/
	rm -rf reports/fastapi.arc/ reports/django.arc/
	rm -f reports/large-repo-results-*.json reports/large-repo-summary-*.md
