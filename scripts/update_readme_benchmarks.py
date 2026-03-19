#!/usr/bin/env python3
"""Update README.md benchmark tables and coverage badge from reports/*.json.

Reads reports/large-repo-results-{repo}.json, generates markdown tables,
and replaces content between <!-- BENCHMARK-START --> and <!-- BENCHMARK-END -->.
Optionally updates coverage badge between <!-- COVERAGE-BADGE-START/END -->.

Usage:
    python scripts/update_readme_benchmarks.py
    python scripts/update_readme_benchmarks.py --coverage 63
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
README_PATH = PROJECT_ROOT / "README.md"

REPOS = {
    "fastapi": {"label": "FastAPI", "loc": "15K", "files": "130"},
    "django": {"label": "Django", "loc": "155K", "files": "879"},
}

DISPLAY_ORDER = ["hybrid", "hybrid_arc", "vector", "arc", "tfidf"]
METRICS = ["context_recall", "evidence_traceability", "debuggability", "token_efficiency"]
HEADERS = ["Context Recall", "Traceability", "Debuggability", "Token Efficiency"]


def interpret_d(d: float) -> str:
    ad = abs(d)
    if ad < 0.2:
        return "negligible"
    if ad < 0.5:
        return "small"
    if ad < 0.8:
        return "medium"
    return "large"


def load_results(repo: str) -> dict | None:
    path = REPORTS_DIR / f"large-repo-results-{repo}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def build_table(repo: str, info: dict, data: dict) -> str:
    systems = data.get("per_system", {})
    effect_sizes = data.get("effect_sizes", {})
    lines = []
    lines.append(f"### {info['label']} ({info['loc']} LOC, {info['files']} files)")
    lines.append("")
    lines.append(f"| System | {' | '.join(HEADERS)} |")
    lines.append(f"|--------| {' | '.join(['-------------'] * len(HEADERS))} |")

    for sys_name in DISPLAY_ORDER:
        if sys_name not in systems:
            continue
        s = systems[sys_name]
        vals = [f"{s.get(m, 0):.3f}" for m in METRICS]
        if sys_name == "hybrid_arc":
            row = f"| **hybrid_arc** | {' | '.join(f'**{v}**' for v in vals)} |"
        else:
            row = f"| {sys_name} | {' | '.join(vals)} |"
        lines.append(row)

    # Effect size: hybrid_arc vs hybrid (from pre-computed effect_sizes)
    d = effect_sizes.get("hybrid_arc_vs_hybrid_recall")
    if d is not None:
        lines.append("")
        lines.append(f"hybrid_arc vs hybrid: d = {d:+.3f} ({interpret_d(d)})")

    return "\n".join(lines)


def generate_section() -> str:
    parts = []
    parts.append("30 tasks per repo, 6 categories. Context recall = fraction of required facts found.")

    for repo, info in REPOS.items():
        data = load_results(repo)
        if data is None:
            continue
        parts.append("")
        parts.append(build_table(repo, info, data))

    parts.append("")
    parts.append("Full analysis: [`docs/benchmark-fastapi-vs-django.md`](docs/benchmark-fastapi-vs-django.md)")

    return "\n".join(parts)


def _badge_color(pct: int) -> str:
    if pct >= 80:
        return "brightgreen"
    if pct >= 60:
        return "yellow"
    if pct >= 40:
        return "orange"
    return "red"


def update_coverage_badge(readme: str, coverage_pct: int) -> str:
    pattern = r"<!-- COVERAGE-BADGE-START -->\n.*?\n<!-- COVERAGE-BADGE-END -->"
    color = _badge_color(coverage_pct)
    badge = f"[![Tested](https://img.shields.io/badge/tested-{coverage_pct}%25%20coverage-{color})](tests/)"
    new_section = f"<!-- COVERAGE-BADGE-START -->\n{badge}\n<!-- COVERAGE-BADGE-END -->"
    return re.sub(pattern, new_section, readme, flags=re.DOTALL)


def update_readme(coverage_pct: int | None = None) -> bool:
    readme = README_PATH.read_text()
    changed = False

    # Update benchmarks
    pattern = r"<!-- BENCHMARK-START -->\n.*?\n<!-- BENCHMARK-END -->"
    match = re.search(pattern, readme, re.DOTALL)
    if match:
        new_section = f"<!-- BENCHMARK-START -->\n{generate_section()}\n<!-- BENCHMARK-END -->"
        if match.group(0) != new_section:
            readme = readme[:match.start()] + new_section + readme[match.end():]
            changed = True
            print("README benchmarks updated.")
        else:
            print("README benchmarks already up to date.")
    else:
        print("WARNING: <!-- BENCHMARK-START/END --> markers not found", file=sys.stderr)

    # Update coverage badge
    if coverage_pct is not None:
        old = readme
        readme = update_coverage_badge(readme, coverage_pct)
        if readme != old:
            changed = True
            print(f"README coverage badge updated to {coverage_pct}%.")

    if changed:
        README_PATH.write_text(readme)

    return changed


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", type=int, default=None, help="Coverage percentage to set")
    args = parser.parse_args()
    update_readme(coverage_pct=args.coverage)
