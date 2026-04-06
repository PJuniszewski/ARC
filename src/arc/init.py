"""arc init — detect project type, generate config, build first archive."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

# Marker files → project type
_MARKERS = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "package.json": "javascript",
    "tsconfig.json": "typescript",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "kotlin",
    "Gemfile": "ruby",
    "mix.exs": "elixir",
    "CMakeLists.txt": "cpp",
    "Makefile": "generic",
}

# Default scan directories per project type
_SCAN_DEFAULTS = {
    "python": ["src", "lib", "docs", "tests"],
    "javascript": ["src", "lib", "docs", "test"],
    "typescript": ["src", "lib", "docs", "test"],
    "go": ["cmd", "pkg", "internal", "docs"],
    "rust": ["src", "docs", "tests"],
    "java": ["src", "docs"],
    "kotlin": ["src", "docs"],
    "ruby": ["lib", "app", "docs", "spec"],
    "elixir": ["lib", "docs", "test"],
    "cpp": ["src", "include", "docs"],
    "generic": ["src", "docs"],
}

# Directories to always ignore
_IGNORE = [
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".gradle",
    "build", "dist", "out", "target",
    ".venv", "venv", "env", ".env",
    ".tox", ".mypy_cache", ".pytest_cache",
    "vendor", "Pods", "DerivedData",
    ".egg-info", "*.egg-info",
]

# Directories to skip when counting LOC (from builder.py)
_SKIP_DIRS = {
    "build", "dist", "out", "target",
    "node_modules", "__pycache__", ".gradle",
    "Pods", "DerivedData",
    "intermediates", "generated", "tmp", "outputs",
    ".git", ".hg", ".svn",
    "vendor", "venv", ".venv", "env",
}


def detect_project(path: Path) -> dict:
    """Detect project type from marker files.

    Returns dict with keys: type, name, markers.
    """
    path = Path(path)
    markers = []
    project_type = "generic"

    for filename, ptype in _MARKERS.items():
        if (path / filename).exists():
            markers.append(filename)
            if project_type == "generic":
                project_type = ptype

    # Try to extract project name
    name = path.name
    if (path / "pyproject.toml").exists():
        name = _extract_name_from_pyproject(path / "pyproject.toml") or name
    elif (path / "package.json").exists():
        name = _extract_name_from_package_json(path / "package.json") or name
    elif (path / "Cargo.toml").exists():
        name = _extract_name_from_cargo(path / "Cargo.toml") or name

    return {"type": project_type, "name": name, "markers": markers}


def _extract_name_from_pyproject(path: Path) -> Optional[str]:
    """Extract project name from pyproject.toml (simple regex, no TOML parser)."""
    try:
        text = path.read_text()
        m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        return m.group(1) if m else None
    except OSError:
        return None


def _extract_name_from_package_json(path: Path) -> Optional[str]:
    """Extract project name from package.json."""
    import json
    try:
        data = json.loads(path.read_text())
        return data.get("name")
    except (OSError, json.JSONDecodeError):
        return None


def _extract_name_from_cargo(path: Path) -> Optional[str]:
    """Extract project name from Cargo.toml."""
    try:
        text = path.read_text()
        m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        return m.group(1) if m else None
    except OSError:
        return None


def estimate_size(path: Path) -> dict:
    """Estimate project size: file count and LOC.

    Returns dict with keys: files, lines, bytes.
    """
    path = Path(path)
    files = 0
    lines = 0
    total_bytes = 0

    for root, dirs, filenames in os.walk(path):
        # Skip ignored directories
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]

        for f in filenames:
            if f.startswith("."):
                continue
            fpath = Path(root) / f
            try:
                size = fpath.stat().st_size
                if size > 10_000_000:  # skip files > 10MB
                    continue
                total_bytes += size
                files += 1
                # Count lines for text files
                if fpath.suffix in {".py", ".js", ".ts", ".go", ".rs", ".java", ".kt",
                                     ".rb", ".ex", ".c", ".cpp", ".h", ".hpp", ".md", ".txt"}:
                    lines += fpath.read_text(errors="replace").count("\n")
            except (OSError, UnicodeDecodeError):
                continue

    return {"files": files, "lines": lines, "bytes": total_bytes}


def pick_defaults(project_type: str, size: dict, project_dir: Path) -> dict:
    """Pick build defaults based on project type and size."""
    scan_dirs = _SCAN_DEFAULTS.get(project_type, ["src", "docs"])
    # Only include directories that actually exist
    existing = [d for d in scan_dirs if (project_dir / d).is_dir()]
    if not existing:
        existing = ["."]  # scan everything if no standard dirs found

    # Check if sentence-transformers is available
    try:
        from .embeddings import try_load_sentence_transformer
        has_neural = try_load_sentence_transformer() is not None
    except (ImportError, OSError, RuntimeError):
        has_neural = False

    # Use TF-IDF for large projects (faster) or when neural not available
    embeddings = "tfidf"
    if has_neural and size.get("lines", 0) < 100_000:
        embeddings = "neural"

    return {
        "scan": existing,
        "ignore": list(_IGNORE),
        "embeddings": embeddings,
    }


def write_arcconfig(config: dict, path: Path) -> None:
    """Write .arcconfig in TOML format."""
    lines = ["# Generated by arc init", ""]
    lines.append("[project]")
    lines.append(f'name = "{config["name"]}"')
    lines.append(f'type = "{config["type"]}"')
    lines.append("")
    lines.append("[build]")
    scan_items = ", ".join('"' + d + '"' for d in config["scan"])
    lines.append(f"scan = [{scan_items}]")
    ignore_items = ", ".join('"' + p + '"' for p in config["ignore"][:8])
    lines.append(f"ignore = [{ignore_items}]")
    lines.append(f'embeddings = "{config["embeddings"]}"')
    lines.append("")
    lines.append("[output]")
    lines.append(f'path = "{config["name"]}.arc"')
    lines.append("")
    path.write_text("\n".join(lines) + "\n")


def read_arcconfig(path: Path) -> dict:
    """Read .arcconfig (simple TOML subset parser)."""
    config: dict = {}
    current_section = ""

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Section header
        m = re.match(r"^\[(\w+)\]$", line)
        if m:
            current_section = m.group(1)
            config.setdefault(current_section, {})
            continue
        # Key = value
        m = re.match(r'^(\w+)\s*=\s*(.+)$', line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            # Parse value
            if val.startswith("["):
                # Array of strings
                items = re.findall(r'"([^"]*)"', val)
                val = items
            elif val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val in ("true", "false"):
                val = val == "true"
            elif val.isdigit():
                val = int(val)
            if current_section:
                config[current_section][key] = val
            else:
                config[key] = val

    return config


def _resolve_source_file(
    claim: object, su_by_id: dict, res_by_id: dict
) -> str:
    """Resolve a claim's evidence to an actual file path."""
    evidence = getattr(claim, "evidence", [])
    derived = getattr(claim, "derived_from", "")

    su_id = ""
    if evidence:
        su_id = getattr(evidence[0], "source_unit_id", "")
    elif derived:
        su_id = derived

    if su_id and su_id in su_by_id:
        su = su_by_id[su_id]
        res_id = getattr(su, "resource_id", "")
        if res_id in res_by_id:
            return getattr(res_by_id[res_id], "locator", "")

    return ""


def extract_top_claims(
    claims: list,
    n: int = 10,
    source_units: list | None = None,
    resources: list | None = None,
) -> list[dict]:
    """Extract the top N most informative claims as dicts for structured output.

    Prefers high-confidence claims with evidence, diverse by source file.
    When source_units and resources are provided, resolves actual file paths.
    """
    # Build lookup tables for file path resolution
    su_by_id: dict[str, object] = {}
    res_by_id: dict[str, object] = {}
    if source_units:
        su_by_id = {getattr(s, "id", ""): s for s in source_units}
    if resources:
        res_by_id = {getattr(r, "id", ""): r for r in resources}

    scored = []
    for c in claims:
        text = getattr(c, "text", str(c))
        if len(text) < 20:
            continue
        conf = getattr(c, "confidence", 0.5)
        has_evidence = bool(getattr(c, "evidence", []))
        ctype = getattr(c, "claim_type", "observation")
        # Score: prefer high confidence, with evidence, non-trivial length
        score = conf + (0.2 if has_evidence else 0) + min(len(text) / 200, 0.3)
        # Boost decisions and dependencies (more interesting than observations)
        if ctype in ("decision", "dependency"):
            score += 0.15

        # Resolve source file path
        source_file = _resolve_source_file(c, su_by_id, res_by_id)

        scored.append((score, {
            "type": ctype,
            "text": text[:200],
            "confidence": round(conf, 2),
            "source_file": source_file,
        }))

    scored.sort(key=lambda x: -x[0])

    # Deduplicate by keeping diverse source files
    seen_prefixes: set[str] = set()
    result = []
    for _, item in scored:
        prefix = item["text"][:40].lower()
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        result.append(item)
        if len(result) >= n:
            break

    return result


def _extract_names_from_claims(claims: list) -> list[str]:
    """Extract class and function names mentioned in claims."""
    names: dict[str, int] = {}
    # Match CamelCase class names and snake_case function names
    for c in claims[:100]:
        text = getattr(c, "text", str(c))
        # CamelCase: ContentAddressedStore, BuildResult, etc.
        for m in re.findall(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b", text):
            names[m] = names.get(m, 0) + 1
        # snake_case functions: build_archive, extract_claims, etc.
        for m in re.findall(r"\b([a-z]+_[a-z_]+)\b", text):
            if len(m) > 5 and m not in {"source_unit", "claim_type", "archive_path",
                                          "text_unit", "derived_from", "source_ref"}:
                names[m] = names.get(m, 0) + 1

    return [name for name, _ in sorted(names.items(), key=lambda x: -x[1])[:10]]


def generate_heuristic_queries(claims: list, archive_name: str = "*.arc") -> list[str]:
    """Mode 3: generate queries from class/function names in claims."""
    names = _extract_names_from_claims(claims)
    queries = []

    for name in names[:3]:
        if name[0].isupper():
            queries.append(f'arc load {archive_name} --task "How does {name} work"')
        else:
            readable = name.replace("_", " ")
            queries.append(f'arc load {archive_name} --task "What does {readable} do"')

    while len(queries) < 3:
        queries.append(f'arc load {archive_name} --task "project architecture overview"')

    return queries[:3]


def generate_llm_queries(
    claims: list, archive_name: str = "*.arc", timeout: float = 5.0
) -> Optional[list[str]]:
    """Mode 2: use cheap LLM API call to generate queries. Returns None on failure."""
    top = extract_top_claims(claims, n=15)
    if not top:
        return None

    facts = "\n".join(f"- [{c['type']}] {c['text']}" for c in top)
    prompt = (
        "Given these facts extracted from a codebase, suggest exactly 3 specific "
        "questions a developer would ask. Concrete, answerable from the code, not "
        "about setup or installation. Return only the 3 questions, one per line.\n\n"
        f"Facts:\n{facts}"
    )

    # Try Anthropic first, then OpenAI
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        result = _call_anthropic(prompt, api_key, timeout)
        if result:
            return _format_llm_queries(result, archive_name)

    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        result = _call_openai(prompt, api_key, timeout)
        if result:
            return _format_llm_queries(result, archive_name)

    return None


def _call_anthropic(prompt: str, api_key: str, timeout: float) -> Optional[str]:
    """Call Anthropic Messages API with urllib (no SDK dependency)."""
    import json as _json
    import urllib.request
    import urllib.error

    body = _json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read())
            return data.get("content", [{}])[0].get("text", "")
    except Exception:
        return None


def _call_openai(prompt: str, api_key: str, timeout: float) -> Optional[str]:
    """Call OpenAI Chat API with urllib (no SDK dependency)."""
    import json as _json
    import urllib.request
    import urllib.error

    body = _json.dumps({
        "model": "gpt-4o-mini",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _format_llm_queries(text: str, archive_name: str) -> list[str]:
    """Parse LLM response into arc load commands."""
    lines = [line.strip().lstrip("0123456789.-) ") for line in text.strip().splitlines()]
    lines = [l for l in lines if l and len(l) > 10]
    return [f'arc load {archive_name} --task "{q}"' for q in lines[:3]]
