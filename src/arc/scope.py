"""Scope reduction for large repository retrieval.

Pure heuristic module — no ML, no embeddings. Reduces the search space
before expensive vector operations by matching query signals against
repository structure (paths, symbols, directories).

Typical flow:
    query → build_repo_metadata() → infer_scope() → ScopePlan
    → used by retrieval_pipeline.py to restrict phase 1/2 search
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import MAX_SCOPE_FILES, STOP_WORDS
from .models import Resource, TextUnit
from .refinement import detect_mode as _detect_refinement_mode


# ── Data structures ──────────────────────────────────────────────


@dataclass
class RepoMetadata:
    """Structural metadata extracted from chunked repository."""

    file_paths: list[str] = field(default_factory=list)
    path_to_resource_id: dict[str, str] = field(default_factory=dict)
    path_to_extension: dict[str, str] = field(default_factory=dict)
    path_to_chunk_ids: dict[str, list[str]] = field(default_factory=dict)
    directory_tree: dict[str, list[str]] = field(default_factory=dict)
    symbols: dict[str, list[str]] = field(default_factory=dict)
    total_files: int = 0


@dataclass
class ScopePlan:
    """Output of scope inference — defines what to search."""

    mode: str  # implementation | architecture | decision | security | debugging | auto
    candidate_paths: list[str] = field(default_factory=list)
    preferred_source_types: list[str] = field(default_factory=list)
    max_scope_files: int = MAX_SCOPE_FILES
    docs_vs_code_prior: float = 0.5  # 0=code-only, 1=docs-only
    scope_reason: str = ""


# ── Mode → scope mapping ────────────────────────────────────────

_MODE_SCOPE = {
    "implementation": {"docs_vs_code_prior": 0.2, "preferred_source_types": ["code"], "max_scope_files": 30},
    "architecture": {"docs_vs_code_prior": 0.4, "preferred_source_types": ["code", "docs"], "max_scope_files": 50},
    "decision": {"docs_vs_code_prior": 0.8, "preferred_source_types": ["docs", "code"], "max_scope_files": 40},
    "security": {"docs_vs_code_prior": 0.3, "preferred_source_types": ["code", "docs"], "max_scope_files": 40},
    "debugging": {"docs_vs_code_prior": 0.1, "preferred_source_types": ["code"], "max_scope_files": 30},
    "auto": {"docs_vs_code_prior": 0.5, "preferred_source_types": ["code", "docs"], "max_scope_files": 50},
}

# Extended mode patterns (beyond refinement.detect_mode)
_SCOPE_MODE_PATTERNS = [
    (re.compile(r"\b(architect|design|overview|structure|layer|component)\b", re.IGNORECASE), "architecture"),
    (re.compile(r"\b(debug|traceback|error|exception|crash|stack\s*trace)\b", re.IGNORECASE), "debugging"),
]


# ── Public API ───────────────────────────────────────────────────


def build_repo_metadata(
    resources: list[Resource], text_units: list[TextUnit],
) -> RepoMetadata:
    """Build structural metadata from chunked resources.

    Built once per corpus. Extracts file paths, directory tree,
    symbols (function/class names), and chunk-to-path mappings.
    """
    meta = RepoMetadata()

    # Index resources by id for lookup
    resource_by_id = {r.id: r for r in resources}

    # Build path maps from resources
    for r in resources:
        path = r.locator
        meta.file_paths.append(path)
        meta.path_to_resource_id[path] = r.id

        # Extract extension
        dot_idx = path.rfind(".")
        ext = path[dot_idx:] if dot_idx >= 0 else ""
        meta.path_to_extension[path] = ext

        # Build directory tree
        parts = path.replace("\\", "/").split("/")
        if len(parts) > 1:
            dir_path = "/".join(parts[:-1])
            meta.directory_tree.setdefault(dir_path, []).append(parts[-1])
        else:
            meta.directory_tree.setdefault(".", []).append(path)

    meta.total_files = len(meta.file_paths)

    # Build chunk-to-path and symbol maps from text units
    for tu in text_units:
        resource = resource_by_id.get(tu.resource_id)
        if not resource:
            continue
        path = resource.locator
        meta.path_to_chunk_ids.setdefault(path, []).append(tu.id)

        # Extract symbols from function/class text units
        if tu.kind == "function":
            first_line = tu.content.split("\n", 1)[0].strip()
            match = re.match(r"(?:async\s+)?(?:def|class)\s+(\w+)", first_line)
            if match:
                meta.symbols.setdefault(path, []).append(match.group(0))
        else:
            # Also scan first line for def/class in non-function chunks
            first_line = tu.content.split("\n", 1)[0].strip()
            for pattern in [r"def\s+(\w+)", r"class\s+(\w+)"]:
                for m in re.finditer(pattern, first_line):
                    meta.symbols.setdefault(path, []).append(m.group(0))

    return meta


def infer_scope(
    query: str,
    repo_meta: RepoMetadata,
    mode: str = "auto",
) -> ScopePlan:
    """Infer which files are relevant to a query using heuristics.

    Priority order (results merged):
    1. Path mentions — query references specific files/dirs
    2. Symbol mentions — query references function/class names
    3. Keyword→directory — query tokens match directory names
    4. Mode-based defaults — implementation→narrow code, decision→broad docs

    Fallback: if < 5 files match, expand to top-N directories by keyword overlap.
    """
    # Detect mode
    if mode == "auto":
        mode = _infer_mode(query)

    scope_config = _MODE_SCOPE.get(mode, _MODE_SCOPE["auto"])

    candidates: set[str] = set()
    reasons: list[str] = []

    # 1. Path mentions
    path_matches = _extract_path_mentions(query, repo_meta.file_paths)
    if path_matches:
        candidates.update(path_matches)
        reasons.append(f"path mentions: {path_matches[:3]}")

    # 2. Symbol mentions
    symbol_matches = _extract_symbol_mentions(query, repo_meta.symbols)
    if symbol_matches:
        candidates.update(symbol_matches)
        reasons.append(f"symbol matches: {symbol_matches[:3]}")

    # 3. Keyword → directory matching
    query_tokens = _tokenize_query(query)
    dir_matches = _keyword_directory_match(query_tokens, repo_meta)
    if dir_matches:
        for dir_path, _score in dir_matches:
            # Add all files in matching directory
            for file_name in repo_meta.directory_tree.get(dir_path, []):
                full_path = f"{dir_path}/{file_name}"
                if full_path in repo_meta.path_to_resource_id:
                    candidates.add(full_path)
        reasons.append(f"dir matches: {[d for d, _ in dir_matches[:3]]}")

    # 4. Fallback: if scope too narrow, expand to top dirs by keyword overlap
    if len(candidates) < 5:
        expanded = _expand_scope(query_tokens, repo_meta, exclude=candidates)
        candidates.update(expanded)
        if expanded:
            reasons.append(f"fallback expansion: +{len(expanded)} files")

    # Cap to max_scope_files
    max_files = scope_config["max_scope_files"]
    candidate_list = sorted(candidates)[:max_files]

    return ScopePlan(
        mode=mode,
        candidate_paths=candidate_list,
        preferred_source_types=scope_config["preferred_source_types"],
        max_scope_files=max_files,
        docs_vs_code_prior=scope_config["docs_vs_code_prior"],
        scope_reason="; ".join(reasons) if reasons else "no scope signals found",
    )


# ── Internal helpers ─────────────────────────────────────────────


def _infer_mode(query: str) -> str:
    """Detect scope mode from query, extending refinement.detect_mode."""
    # Check scope-specific patterns first
    for pattern, mode_name in _SCOPE_MODE_PATTERNS:
        if pattern.search(query):
            return mode_name

    # Fall back to refinement mode detection
    refinement_mode = _detect_refinement_mode(query)
    return refinement_mode.name


def _tokenize_query(query: str) -> set[str]:
    """Extract meaningful tokens from query."""
    words = re.findall(r"\b\w{2,}\b", query.lower())
    return {w for w in words if w not in STOP_WORDS and len(w) > 2}


def _extract_path_mentions(query: str, file_paths: list[str]) -> list[str]:
    """Find files whose names or paths appear in the query."""
    query_lower = query.lower()
    matches = []
    for path in file_paths:
        # Match filename (e.g., "routing.py")
        parts = path.replace("\\", "/").split("/")
        filename = parts[-1].lower()
        if filename in query_lower:
            matches.append(path)
            continue
        # Match path segments (e.g., "dependencies/")
        for part in parts[:-1]:
            if len(part) > 2 and part.lower() in query_lower:
                matches.append(path)
                break
    return matches


def _extract_symbol_mentions(
    query: str, symbols: dict[str, list[str]],
) -> list[str]:
    """Find files containing symbols mentioned in the query."""
    query_lower = query.lower()
    matches = []
    for path, syms in symbols.items():
        for sym in syms:
            # Extract just the name (after def/class)
            parts = sym.split()
            name = parts[-1] if parts else sym
            if len(name) > 2 and name.lower() in query_lower:
                matches.append(path)
                break
    return matches


def _keyword_directory_match(
    query_tokens: set[str],
    repo_meta: RepoMetadata,
) -> list[tuple[str, float]]:
    """Match query tokens against directory names."""
    if not query_tokens:
        return []

    scored: list[tuple[str, float]] = []
    for dir_path in repo_meta.directory_tree:
        dir_parts = dir_path.replace("\\", "/").split("/")
        dir_tokens = {p.lower() for p in dir_parts if len(p) > 2}
        if not dir_tokens:
            continue
        overlap = len(query_tokens & dir_tokens)
        if overlap > 0:
            score = overlap / len(dir_tokens)
            scored.append((dir_path, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:10]


def _expand_scope(
    query_tokens: set[str],
    repo_meta: RepoMetadata,
    exclude: set[str],
    max_dirs: int = 3,
) -> set[str]:
    """Expand scope by adding top directories with keyword overlap."""
    # Score all directories by keyword overlap with query
    dir_scores: list[tuple[str, float]] = []
    for dir_path, files in repo_meta.directory_tree.items():
        dir_parts = dir_path.replace("\\", "/").split("/")
        dir_tokens = {p.lower() for p in dir_parts if len(p) > 2}

        # Also check file names in directory
        file_tokens = set()
        for f in files:
            name = f.rsplit(".", 1)[0].lower() if "." in f else f.lower()
            # Split on underscores and hyphens
            file_tokens.update(p for p in re.split(r"[_\-]", name) if len(p) > 2)

        all_tokens = dir_tokens | file_tokens
        if not all_tokens:
            continue

        overlap = len(query_tokens & all_tokens)
        if overlap > 0:
            dir_scores.append((dir_path, overlap / len(all_tokens)))

    dir_scores.sort(key=lambda x: x[1], reverse=True)

    expanded: set[str] = set()
    for dir_path, _score in dir_scores[:max_dirs]:
        for file_name in repo_meta.directory_tree.get(dir_path, []):
            full_path = f"{dir_path}/{file_name}"
            if full_path in repo_meta.path_to_resource_id and full_path not in exclude:
                expanded.add(full_path)
    return expanded
