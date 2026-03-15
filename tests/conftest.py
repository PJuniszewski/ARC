"""Shared fixtures for ARC Archive tests."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CORPUS_DIR = FIXTURES_DIR / "corpus"
GROUND_TRUTH_PATH = FIXTURES_DIR / "ground_truth.json"


@pytest.fixture
def corpus_dir():
    """Path to the test corpus directory."""
    return CORPUS_DIR


@pytest.fixture
def ground_truth():
    """Load ground truth data."""
    return json.loads(GROUND_TRUTH_PATH.read_text())


@pytest.fixture
def tmp_archive(tmp_path):
    """Temporary directory for building archives."""
    archive_dir = tmp_path / "test.arc"
    return archive_dir


@pytest.fixture
def tmp_archive_v2(tmp_path):
    """Second temporary directory for incremental/diff tests."""
    archive_dir = tmp_path / "test_v2.arc"
    return archive_dir


@pytest.fixture
def built_archive(corpus_dir, tmp_archive):
    """A pre-built archive from the test corpus."""
    from arc.builder import build_archive
    result = build_archive(
        source_dir=corpus_dir,
        output_dir=tmp_archive,
        archive_id="arc://test-corpus",
        archive_version="1.0.0",
        compression_budget=0.5,
    )
    assert result.valid, f"Build failed: {result.errors}"
    return result


@pytest.fixture
def modified_corpus(tmp_path, corpus_dir):
    """A copy of the corpus with one file modified."""
    modified = tmp_path / "modified_corpus"
    shutil.copytree(corpus_dir, modified)

    # Modify one file
    target = modified / "security.md"
    content = target.read_text()
    content += "\n\n## New Section: Advanced Threats\n\nNew threat category: model extraction attacks where adversaries attempt to extract proprietary knowledge from the archive through crafted queries.\n"
    target.write_text(content)

    return modified
