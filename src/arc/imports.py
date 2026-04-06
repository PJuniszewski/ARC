"""Import graph extraction — parse import statements and build a file-level dependency graph.

Language-aware parser interface: add one function per language.
Currently supports Python. JS/TS/Go can be added by implementing a
``parse_imports_<lang>`` function with the same signature.

The graph is stored as a layer in the .arc archive and used at query time
to boost retrieval scores for files that are imported by (or import)
high-scoring files.

Python-specific assumptions (grep for PYTHON-SPECIFIC to find them):
- ``import X`` and ``from X import Y`` statements
- Dotted module paths resolved relative to source root
- Lazy / conditional imports inside function bodies are included
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Graph data model ────────────────────────────────────────────────


@dataclass
class ImportEdge:
    """A single import relationship: *importer* depends on *imported*."""

    importer: str  # locator of the importing file
    imported: str  # locator of the imported file


@dataclass
class ImportGraph:
    """Directed graph of file-level import relationships.

    forward[a] = {b, c}  means file *a* imports *b* and *c*.
    reverse[b] = {a}     means file *b* is imported by *a*.
    """

    forward: dict[str, set[str]] = field(default_factory=dict)
    reverse: dict[str, set[str]] = field(default_factory=dict)

    def add(self, importer: str, imported: str) -> None:
        self.forward.setdefault(importer, set()).add(imported)
        self.reverse.setdefault(imported, set()).add(importer)

    def neighbors(self, locator: str) -> set[str]:
        """Files that *locator* imports OR that import *locator* (depth 1)."""
        fwd = self.forward.get(locator, set())
        rev = self.reverse.get(locator, set())
        return fwd | rev

    # -- serialisation ------------------------------------------------

    def to_dict(self) -> dict:
        edges: list[dict[str, str]] = []
        for src, targets in sorted(self.forward.items()):
            for tgt in sorted(targets):
                edges.append({"from": src, "to": tgt})
        return {
            "version": "1.0",
            "language_parsers": ["python"],
            "edge_count": len(edges),
            "edges": edges,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ImportGraph:
        g = cls()
        for e in d.get("edges", []):
            g.add(e["from"], e["to"])
        return g


# ── Python import parser ────────────────────────────────────────────

# PYTHON-SPECIFIC: matches ``import X``, ``from X import Y``, handles
# dotted paths, parenthesised imports, and conditional/lazy imports
# inside function bodies.

_PY_IMPORT = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE
)


def parse_imports_python(
    content: str,
    file_locator: str,
    all_locators: set[str],
    source_root: str = "",
) -> list[str]:
    """Extract imported module paths from Python source and resolve to locators.

    Returns a list of *locator* strings (matching entries in *all_locators*)
    for every import that can be resolved to a file in the archive.

    PYTHON-SPECIFIC: Resolves dotted module names to file paths.
    """
    resolved: list[str] = []
    for m in _PY_IMPORT.finditer(content):
        module = m.group(1) or m.group(2)
        if not module:
            continue
        # Skip stdlib / third-party (no dots or starts with known stdlib)
        candidates = _module_to_paths(module)
        for candidate in candidates:
            if candidate in all_locators:
                resolved.append(candidate)
                break
    return resolved


def _module_to_paths(module: str) -> list[str]:
    """Convert a dotted Python module path to candidate file locators.

    PYTHON-SPECIFIC: ``django.db.models.base`` →
    [``django/db/models/base.py``, ``django/db/models/base/__init__.py``].
    """
    parts = module.replace(".", "/")
    return [
        f"{parts}.py",
        f"{parts}/__init__.py",
    ]


# ── Language dispatch ────────────────────────────────────────────────

_PARSERS: dict[str, type] = {
    ".py": parse_imports_python,  # type: ignore[dict-item]
}


def build_import_graph(
    resources: list,
    source_dir: Path,
) -> ImportGraph:
    """Build a file-level import graph from source resources.

    Reads each file, dispatches to the language-specific parser, and
    assembles the directed graph.
    """
    graph = ImportGraph()
    all_locators = {r.locator for r in resources}

    for resource in resources:
        ext = resource.metadata.get("extension", "")
        parser = _PARSERS.get(ext)
        if parser is None:
            continue

        fpath = source_dir / resource.locator
        if not fpath.exists():
            continue

        content = fpath.read_text(encoding="utf-8", errors="replace")
        imported = parser(content, resource.locator, all_locators, str(source_dir))

        for imp in imported:
            graph.add(resource.locator, imp)

    return graph
