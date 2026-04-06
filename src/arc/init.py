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
    except Exception:
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


def generate_example_queries(claims: list, resources: list) -> list[str]:
    """Generate 3 example queries from actual archive content."""
    queries = []

    # Strategy 1: find the most referenced topic from claims
    word_freq: dict[str, int] = {}
    stop = {"the", "is", "are", "was", "has", "have", "and", "for", "with", "this",
            "that", "from", "all", "not", "but", "its", "can", "should", "must",
            "will", "each", "any", "into", "via", "per", "may", "such", "also",
            "uses", "used", "using", "provides", "provides", "based", "when"}
    for c in claims[:50]:
        text = getattr(c, "text", str(c))
        for word in re.findall(r"\b[a-z]{4,}\b", text.lower()):
            if word not in stop:
                word_freq[word] = word_freq.get(word, 0) + 1

    top_words = sorted(word_freq.items(), key=lambda x: -x[1])[:10]

    # Strategy 2: extract key modules from resource locators
    modules = set()
    for r in resources[:30]:
        loc = getattr(r, "locator", str(r))
        parts = Path(loc).parts
        if len(parts) >= 2:
            modules.add(parts[0] if parts[0] != "." else parts[1] if len(parts) > 1 else "")

    # Generate queries
    if top_words:
        queries.append(f'arc load *.arc --task "how does {top_words[0][0]} work"')
    if len(top_words) >= 3:
        queries.append(f'arc load *.arc --task "{top_words[1][0]} and {top_words[2][0]}"')
    if modules:
        mod = sorted(modules)[0]
        queries.append(f'arc load *.arc --task "explain the {mod} module"')

    # Fallback
    while len(queries) < 3:
        queries.append('arc load *.arc --task "project architecture overview"')

    return queries[:3]
