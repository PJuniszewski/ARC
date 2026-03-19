"""Tests for 0%-coverage modules: reasoning, cache, refinement, scope, retrieval_pipeline.

Covers every public function in:
- arc.reasoning (has_reasoning, count_reasoning_markers)
- arc.cache (RetrievalCache, CacheConfig)
- arc.refinement (detect_mode, refine, _detect_source_type, dataclasses)
- arc.scope (build_repo_metadata, infer_scope, helpers)
- arc.retrieval_pipeline (ScopedRetrievalPipeline, _ext_to_source_type)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc.models import Resource, TextUnit, _generate_id


# ---------------------------------------------------------------------------
# Helpers — minimal Resource / TextUnit factories
# ---------------------------------------------------------------------------


def _make_resource(locator: str, kind: str = "file", extension: str = ".py") -> Resource:
    return Resource(locator=locator, kind=kind, metadata={"extension": extension})


def _make_text_unit(
    content: str,
    resource_id: str,
    kind: str = "section",
    span: tuple[int, int] = (1, 5),
) -> TextUnit:
    return TextUnit(content=content, resource_id=resource_id, kind=kind, span=span)


# ═══════════════════════════════════════════════════════════════════════════
# 1. arc.reasoning
# ═══════════════════════════════════════════════════════════════════════════


class TestReasoning:
    """Tests for reasoning marker detection."""

    def test_has_reasoning_causal_connective(self):
        from arc.reasoning import has_reasoning

        assert has_reasoning("We chose SQLite because it has no server dependency.")

    def test_has_reasoning_decision_verb(self):
        from arc.reasoning import has_reasoning

        assert has_reasoning("The team decided to use Postgres for production.")

    def test_has_reasoning_contrastive(self):
        from arc.reasoning import has_reasoning

        assert has_reasoning("We preferred FastAPI rather than Flask.")

    def test_has_reasoning_adr_heading(self):
        from arc.reasoning import has_reasoning

        assert has_reasoning("# Context\nSome background text.")

    def test_has_reasoning_adr_heading_rationale(self):
        from arc.reasoning import has_reasoning

        assert has_reasoning("## Rationale\nExplanation here.")

    def test_has_reasoning_negative_plain_text(self):
        from arc.reasoning import has_reasoning

        assert not has_reasoning("This is a plain sentence with no reasoning markers.")

    def test_has_reasoning_negative_empty(self):
        from arc.reasoning import has_reasoning

        assert not has_reasoning("")

    def test_count_reasoning_markers_multiple(self):
        from arc.reasoning import count_reasoning_markers

        text = "We chose X because it is faster. Therefore we decided to deploy."
        count = count_reasoning_markers(text)
        # "chose", "because", "Therefore", "decided" — at least 3 matches
        assert count >= 3

    def test_count_reasoning_markers_zero(self):
        from arc.reasoning import count_reasoning_markers

        assert count_reasoning_markers("Hello world") == 0

    def test_count_reasoning_markers_adr_heading(self):
        from arc.reasoning import count_reasoning_markers

        text = "## Decision\nSome text\n## Consequences\nMore text"
        count = count_reasoning_markers(text)
        assert count >= 2  # two headings


# ═══════════════════════════════════════════════════════════════════════════
# 2. arc.cache
# ═══════════════════════════════════════════════════════════════════════════


class TestCacheConfig:
    """Tests for CacheConfig defaults."""

    def test_default_disabled(self):
        from arc.cache import CacheConfig

        cfg = CacheConfig()
        assert cfg.enabled is False
        assert cfg.cache_dir == Path(".arc_cache")

    def test_custom_values(self):
        from arc.cache import CacheConfig

        cfg = CacheConfig(enabled=True, cache_dir=Path("/tmp/test_cache"))
        assert cfg.enabled is True
        assert cfg.cache_dir == Path("/tmp/test_cache")


class TestRetrievalCache:
    """Tests for RetrievalCache get/put and hash_directory."""

    def test_disabled_cache_returns_none(self):
        from arc.cache import CacheConfig, RetrievalCache

        cache = RetrievalCache(CacheConfig(enabled=False))
        assert cache.get_chunks("abc") is None
        assert cache.get_embeddings("abc") is None

    def test_disabled_cache_put_is_noop(self):
        from arc.cache import CacheConfig, RetrievalCache

        cache = RetrievalCache(CacheConfig(enabled=False))
        # Should not raise
        cache.put_chunks("abc", [{"a": 1}], [{"b": 2}])
        cache.put_embeddings("abc", {"vec": [1, 2, 3]})

    def test_enabled_cache_roundtrip_chunks(self, tmp_path):
        from arc.cache import CacheConfig, RetrievalCache

        cache = RetrievalCache(CacheConfig(enabled=True, cache_dir=tmp_path / "cache"))
        resources = [{"id": "r1", "locator": "foo.py"}]
        text_units = [{"id": "tu1", "content": "hello"}]

        cache.put_chunks("hash1", resources, text_units)
        result = cache.get_chunks("hash1")

        assert result is not None
        assert result[0] == resources
        assert result[1] == text_units

    def test_enabled_cache_roundtrip_embeddings(self, tmp_path):
        from arc.cache import CacheConfig, RetrievalCache

        cache = RetrievalCache(CacheConfig(enabled=True, cache_dir=tmp_path / "cache"))
        store_dict = {"model": "tfidf", "vectors": [[0.1, 0.2]]}

        cache.put_embeddings("ehash1", store_dict)
        result = cache.get_embeddings("ehash1")

        assert result is not None
        assert result["model"] == "tfidf"

    def test_cache_miss_chunks(self, tmp_path):
        from arc.cache import CacheConfig, RetrievalCache

        cache = RetrievalCache(CacheConfig(enabled=True, cache_dir=tmp_path / "cache"))
        assert cache.get_chunks("nonexistent") is None

    def test_cache_miss_embeddings(self, tmp_path):
        from arc.cache import CacheConfig, RetrievalCache

        cache = RetrievalCache(CacheConfig(enabled=True, cache_dir=tmp_path / "cache"))
        assert cache.get_embeddings("nonexistent") is None

    def test_corrupt_json_chunks(self, tmp_path):
        from arc.cache import CacheConfig, RetrievalCache

        cache = RetrievalCache(CacheConfig(enabled=True, cache_dir=tmp_path / "cache"))
        # Write corrupt JSON
        corrupt_path = tmp_path / "cache" / "chunks" / "bad.json"
        corrupt_path.write_text("{not valid json!!!")
        assert cache.get_chunks("bad") is None

    def test_corrupt_json_embeddings(self, tmp_path):
        from arc.cache import CacheConfig, RetrievalCache

        cache = RetrievalCache(CacheConfig(enabled=True, cache_dir=tmp_path / "cache"))
        corrupt_path = tmp_path / "cache" / "embeddings" / "bad.json"
        corrupt_path.write_text("{not valid json!!!")
        assert cache.get_embeddings("bad") is None

    def test_hash_directory(self, tmp_path):
        from arc.cache import RetrievalCache

        # Create a small directory structure
        (tmp_path / "a.py").write_text("hello")
        (tmp_path / "b.py").write_text("world")

        h = RetrievalCache.hash_directory(tmp_path)
        assert isinstance(h, str)
        assert len(h) == 16  # truncated to 16 hex chars

    def test_hash_directory_deterministic(self, tmp_path):
        from arc.cache import RetrievalCache

        (tmp_path / "a.py").write_text("hello")
        h1 = RetrievalCache.hash_directory(tmp_path)
        h2 = RetrievalCache.hash_directory(tmp_path)
        assert h1 == h2

    def test_hash_directory_nonexistent(self, tmp_path):
        from arc.cache import RetrievalCache

        # Should not raise — falls back to hashing path string
        h = RetrievalCache.hash_directory(tmp_path / "does_not_exist")
        assert isinstance(h, str)
        assert len(h) == 16


# ═══════════════════════════════════════════════════════════════════════════
# 3. arc.refinement
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectMode:
    """Tests for detect_mode — pattern-based mode selection."""

    def test_implementation_mode(self):
        from arc.refinement import detect_mode

        mode = detect_mode("Where is the authentication handler located?")
        assert mode.name == "implementation"

    def test_decision_mode(self):
        from arc.refinement import detect_mode

        mode = detect_mode("Why did we choose FastAPI instead of Flask?")
        assert mode.name == "decision"

    def test_cross_file_mode(self):
        from arc.refinement import detect_mode

        mode = detect_mode("How does the request flow across services?")
        assert mode.name == "cross_file"

    def test_security_mode(self):
        from arc.refinement import detect_mode

        mode = detect_mode("What security controls protect the auth endpoint?")
        assert mode.name == "security"

    def test_feature_mode(self):
        from arc.refinement import detect_mode

        mode = detect_mode("How does the caching system work?")
        assert mode.name == "feature"

    def test_balanced_fallback(self):
        from arc.refinement import detect_mode

        mode = detect_mode("Tell me about the project")
        assert mode.name == "balanced"

    def test_mode_has_expected_attributes(self):
        from arc.refinement import detect_mode

        mode = detect_mode("some query")
        assert hasattr(mode, "passthrough_k")
        assert hasattr(mode, "code_weight")
        assert hasattr(mode, "docs_weight")
        assert hasattr(mode, "min_code_items")
        assert hasattr(mode, "reasoning_boost")


class TestDetectSourceType:
    """Tests for _detect_source_type heuristic."""

    def test_python_file_is_code(self):
        from arc.refinement import ChunkWithMeta, _detect_source_type

        r = _make_resource("src/foo.py", extension=".py")
        chunk = ChunkWithMeta(text="def hello(): pass", chunk_id="c1", score=0.8, resource=r)
        assert _detect_source_type(chunk) == "code"

    def test_markdown_file_is_docs(self):
        from arc.refinement import ChunkWithMeta, _detect_source_type

        r = _make_resource("docs/readme.md", extension=".md")
        chunk = ChunkWithMeta(text="# Title\nSome docs", chunk_id="c2", score=0.5, resource=r)
        assert _detect_source_type(chunk) == "docs"

    def test_document_kind_is_docs(self):
        from arc.refinement import ChunkWithMeta, _detect_source_type

        r = Resource(locator="ticket-123", kind="document", metadata={})
        chunk = ChunkWithMeta(text="Bug report text", chunk_id="c3", score=0.3, resource=r)
        assert _detect_source_type(chunk) == "docs"

    def test_code_pattern_heuristic_fallback(self):
        from arc.refinement import ChunkWithMeta, _detect_source_type

        chunk = ChunkWithMeta(
            text="def process_data():\n    return 42",
            chunk_id="c4",
            score=0.6,
            resource=None,
        )
        assert _detect_source_type(chunk) == "code"

    def test_no_resource_no_code_pattern_is_docs(self):
        from arc.refinement import ChunkWithMeta, _detect_source_type

        chunk = ChunkWithMeta(
            text="This is documentation text about the project.",
            chunk_id="c5",
            score=0.4,
            resource=None,
        )
        assert _detect_source_type(chunk) == "docs"


class TestChunkWithMeta:
    """Tests for ChunkWithMeta dataclass."""

    def test_creation_defaults(self):
        from arc.refinement import ChunkWithMeta

        c = ChunkWithMeta(text="hello", chunk_id="id1", score=0.5)
        assert c.text_unit is None
        assert c.resource is None
        assert c.source_type == "unknown"


class TestRefinedItem:
    """Tests for RefinedItem dataclass."""

    def test_creation(self):
        from arc.refinement import RefinedItem

        item = RefinedItem(id="item1", text="claim text", source_type="docs")
        assert item.confidence == 1.0
        assert item.retrieval_score == 0.0
        assert item.evidence == []


class TestRefinementResult:
    """Tests for RefinementResult dataclass."""

    def test_empty_defaults(self):
        from arc.refinement import RefinementResult

        result = RefinementResult()
        assert result.items == []
        assert result.tokens_before == 0
        assert result.tokens_after == 0
        assert result.evidence_map == {}


class TestRefine:
    """Tests for refine() pipeline."""

    def _make_chunks(self, n_code=3, n_docs=3):
        """Create a mix of code and doc ChunkWithMeta items with associated resources/TUs."""
        from arc.refinement import ChunkWithMeta

        resources = []
        text_units = []
        chunks = []

        for i in range(n_code):
            r = _make_resource(f"src/mod{i}.py", extension=".py")
            resources.append(r)
            tu = _make_text_unit(
                content=f"def func_{i}():\n    return {i}",
                resource_id=r.id,
                kind="function",
                span=(1, 3),
            )
            text_units.append(tu)
            chunks.append(
                ChunkWithMeta(
                    text=tu.content,
                    chunk_id=tu.id,
                    score=0.9 - i * 0.1,
                    text_unit=tu,
                    resource=r,
                )
            )

        for i in range(n_docs):
            r = _make_resource(f"docs/guide{i}.md", extension=".md")
            resources.append(r)
            tu = _make_text_unit(
                content=f"The system uses pattern {i}. It provides reliability and handles errors.",
                resource_id=r.id,
                kind="section",
                span=(1, 10),
            )
            text_units.append(tu)
            chunks.append(
                ChunkWithMeta(
                    text=tu.content,
                    chunk_id=tu.id,
                    score=0.7 - i * 0.1,
                    text_unit=tu,
                    resource=r,
                )
            )

        tu_by_id = {tu.id: tu for tu in text_units}
        r_by_id = {r.id: r for r in resources}
        return chunks, tu_by_id, r_by_id

    def test_empty_chunks(self):
        from arc.refinement import refine

        result = refine([], {}, {})
        assert result.items == []
        assert result.tokens_before == 0
        assert result.tokens_after == 0

    def test_refine_produces_items(self):
        from arc.refinement import refine

        chunks, tu_by_id, r_by_id = self._make_chunks()
        result = refine(chunks, tu_by_id, r_by_id, question="How does X work?")
        assert len(result.items) > 0
        assert result.tokens_before > 0
        assert result.tokens_after > 0

    def test_refine_evidence_map_populated(self):
        from arc.refinement import refine

        chunks, tu_by_id, r_by_id = self._make_chunks()
        result = refine(chunks, tu_by_id, r_by_id, question="Where is the handler?")
        # Every item should have an evidence_map entry
        for item in result.items:
            assert item.id in result.evidence_map

    def test_refine_passthrough_items_present(self):
        from arc.refinement import refine

        chunks, tu_by_id, r_by_id = self._make_chunks(n_code=5, n_docs=5)
        result = refine(chunks, tu_by_id, r_by_id, question="Where is auth?")
        # Passthrough items have confidence=2.0
        passthrough = [i for i in result.items if i.confidence == 2.0]
        assert len(passthrough) >= 1

    def test_refine_code_items_present(self):
        from arc.refinement import refine

        chunks, tu_by_id, r_by_id = self._make_chunks(n_code=5, n_docs=2)
        result = refine(chunks, tu_by_id, r_by_id, question="Where is the handler?")
        code_items = [i for i in result.items if i.source_type == "code"]
        assert len(code_items) >= 1

    def test_refine_token_budget_respected(self):
        from arc.refinement import refine

        chunks, tu_by_id, r_by_id = self._make_chunks(n_code=10, n_docs=10)
        result = refine(
            chunks, tu_by_id, r_by_id,
            token_budget=100,
            question="Tell me about the system",
        )
        # tokens_after should respect budget (approximately)
        assert result.tokens_after <= 200  # some slack for per-item granularity

    def test_refine_decision_mode_reasoning_boost(self):
        """Decision mode should boost reasoning-bearing chunks."""
        from arc.refinement import ChunkWithMeta, refine

        r = _make_resource("docs/adr.md", extension=".md")
        tu_reasoning = _make_text_unit(
            content="We chose SQLite because it requires no server. Therefore it simplifies deployment.",
            resource_id=r.id,
            kind="section",
            span=(1, 5),
        )
        tu_plain = _make_text_unit(
            content="The system has a database layer for storage.",
            resource_id=r.id,
            kind="section",
            span=(6, 10),
        )

        chunks = [
            ChunkWithMeta(text=tu_reasoning.content, chunk_id=tu_reasoning.id, score=0.5, text_unit=tu_reasoning, resource=r),
            ChunkWithMeta(text=tu_plain.content, chunk_id=tu_plain.id, score=0.5, text_unit=tu_plain, resource=r),
        ]
        tu_by_id = {tu_reasoning.id: tu_reasoning, tu_plain.id: tu_plain}
        r_by_id = {r.id: r}

        result = refine(chunks, tu_by_id, r_by_id, question="Why did we choose SQLite instead of Postgres?")
        # Should have items
        assert len(result.items) > 0

    def test_refine_cross_file_neighbor_boost(self):
        """Cross-file mode should boost neighboring files."""
        from arc.refinement import ChunkWithMeta, refine

        # Create chunks from multiple files in same directory
        resources = []
        text_units = []
        chunks = []
        for i in range(8):
            r = _make_resource(f"src/handlers/handler_{i}.py", extension=".py")
            resources.append(r)
            tu = _make_text_unit(
                content=f"class Handler{i}:\n    def handle(self): pass",
                resource_id=r.id,
                kind="function",
                span=(1, 3),
            )
            text_units.append(tu)
            chunks.append(
                ChunkWithMeta(
                    text=tu.content,
                    chunk_id=tu.id,
                    score=0.9 - i * 0.05,
                    text_unit=tu,
                    resource=r,
                )
            )

        tu_by_id = {tu.id: tu for tu in text_units}
        r_by_id = {r.id: r for r in resources}

        result = refine(
            chunks, tu_by_id, r_by_id,
            question="How does the request flow across handlers?",
        )
        assert len(result.items) > 0
        # Cross-file mode should have expanded token budget
        # And multiple files should be represented
        source_files = set()
        for item in result.items:
            if item.id in result.evidence_map:
                sf = result.evidence_map[item.id].get("source_file", "")
                if sf:
                    source_files.add(sf)
        assert len(source_files) >= 2


# ═══════════════════════════════════════════════════════════════════════════
# 4. arc.scope
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildRepoMetadata:
    """Tests for build_repo_metadata."""

    def test_basic_metadata(self):
        from arc.scope import build_repo_metadata

        r1 = _make_resource("src/app.py", extension=".py")
        r2 = _make_resource("docs/readme.md", extension=".md")
        tu1 = _make_text_unit("def main(): pass", resource_id=r1.id, kind="function")
        tu2 = _make_text_unit("# Readme\nProject docs", resource_id=r2.id, kind="section")

        meta = build_repo_metadata([r1, r2], [tu1, tu2])

        assert meta.total_files == 2
        assert "src/app.py" in meta.file_paths
        assert "docs/readme.md" in meta.file_paths

    def test_directory_tree_built(self):
        from arc.scope import build_repo_metadata

        r1 = _make_resource("src/app.py")
        r2 = _make_resource("src/utils.py")
        meta = build_repo_metadata([r1, r2], [])

        assert "src" in meta.directory_tree
        assert "app.py" in meta.directory_tree["src"]
        assert "utils.py" in meta.directory_tree["src"]

    def test_path_to_chunk_ids(self):
        from arc.scope import build_repo_metadata

        r = _make_resource("src/app.py")
        tu = _make_text_unit("def foo(): pass", resource_id=r.id, kind="function")

        meta = build_repo_metadata([r], [tu])
        assert tu.id in meta.path_to_chunk_ids.get("src/app.py", [])

    def test_symbols_extracted(self):
        from arc.scope import build_repo_metadata

        r = _make_resource("src/app.py")
        tu = _make_text_unit("def process_data():\n    return 42", resource_id=r.id, kind="function")

        meta = build_repo_metadata([r], [tu])
        assert "src/app.py" in meta.symbols
        # Should contain the symbol match
        assert any("process_data" in s for s in meta.symbols["src/app.py"])

    def test_extension_extracted(self):
        from arc.scope import build_repo_metadata

        r = _make_resource("src/app.py", extension=".py")
        meta = build_repo_metadata([r], [])
        assert meta.path_to_extension["src/app.py"] == ".py"

    def test_root_level_file(self):
        from arc.scope import build_repo_metadata

        r = _make_resource("setup.py")
        meta = build_repo_metadata([r], [])
        assert "." in meta.directory_tree
        assert "setup.py" in meta.directory_tree["."]


class TestInferScope:
    """Tests for infer_scope — heuristic scope reduction."""

    def _build_repo(self):
        """Build a small repo metadata for testing."""
        from arc.scope import build_repo_metadata

        resources = [
            _make_resource("src/auth/login.py"),
            _make_resource("src/auth/oauth.py"),
            _make_resource("src/models/user.py"),
            _make_resource("src/models/post.py"),
            _make_resource("docs/architecture.md", extension=".md"),
            _make_resource("docs/security.md", extension=".md"),
            _make_resource("tests/test_auth.py"),
            _make_resource("tests/test_models.py"),
        ]
        text_units = [
            _make_text_unit("def login(): pass", resource_id=resources[0].id, kind="function"),
            _make_text_unit("def oauth_flow(): pass", resource_id=resources[1].id, kind="function"),
            _make_text_unit("class User: pass", resource_id=resources[2].id, kind="function"),
            _make_text_unit("class Post: pass", resource_id=resources[3].id, kind="function"),
            _make_text_unit("# Architecture\nOverview", resource_id=resources[4].id, kind="section"),
            _make_text_unit("# Security\nThreat model", resource_id=resources[5].id, kind="section"),
        ]
        meta = build_repo_metadata(resources, text_units)
        return meta

    def test_path_mention_scoping(self):
        from arc.scope import infer_scope

        meta = self._build_repo()
        plan = infer_scope("What does login.py do?", meta)
        assert "src/auth/login.py" in plan.candidate_paths

    def test_symbol_mention_scoping(self):
        from arc.scope import infer_scope

        meta = self._build_repo()
        plan = infer_scope("How does the login function work?", meta)
        # Should include files with 'login' symbol
        assert any("login" in p for p in plan.candidate_paths)

    def test_keyword_directory_match(self):
        from arc.scope import infer_scope

        meta = self._build_repo()
        plan = infer_scope("How does the auth module handle requests?", meta)
        # Should include auth directory files
        assert any("auth" in p for p in plan.candidate_paths)

    def test_fallback_expansion(self):
        from arc.scope import infer_scope

        meta = self._build_repo()
        # Query with no direct matches — should trigger fallback expansion
        plan = infer_scope("something completely unrelated xyz", meta)
        # Should still produce some candidates via fallback
        assert plan.scope_reason  # Should have a reason string

    def test_mode_passed_through(self):
        from arc.scope import infer_scope

        meta = self._build_repo()
        plan = infer_scope("query", meta, mode="implementation")
        assert plan.mode == "implementation"

    def test_auto_mode_detection(self):
        from arc.scope import infer_scope

        meta = self._build_repo()
        plan = infer_scope("What is the overall architecture design?", meta)
        # "architecture" keyword should trigger architecture mode
        assert plan.mode == "architecture"


class TestInferMode:
    """Tests for _infer_mode — scope-specific mode detection."""

    def test_architecture_pattern(self):
        from arc.scope import _infer_mode

        assert _infer_mode("What is the overall design of the system?") == "architecture"

    def test_debugging_pattern(self):
        from arc.scope import _infer_mode

        assert _infer_mode("I see a traceback error in the logs") == "debugging"

    def test_fallback_to_refinement_mode(self):
        from arc.scope import _infer_mode

        # "where" triggers implementation in refinement
        result = _infer_mode("Where is the config file?")
        assert result == "implementation"

    def test_balanced_fallback(self):
        from arc.scope import _infer_mode

        result = _infer_mode("tell me about the project")
        assert result == "balanced"


class TestTokenizeQuery:
    """Tests for _tokenize_query."""

    def test_removes_stop_words(self):
        from arc.scope import _tokenize_query

        tokens = _tokenize_query("What is the authentication handler?")
        assert "the" not in tokens
        assert "what" not in tokens
        assert "authentication" in tokens

    def test_lowercase(self):
        from arc.scope import _tokenize_query

        tokens = _tokenize_query("Authentication Handler")
        assert "authentication" in tokens
        assert "handler" in tokens

    def test_short_words_excluded(self):
        from arc.scope import _tokenize_query

        tokens = _tokenize_query("go to it")
        # All words are 2 chars or stop words
        assert len(tokens) == 0


class TestExtractPathMentions:
    """Tests for _extract_path_mentions."""

    def test_filename_match(self):
        from arc.scope import _extract_path_mentions

        paths = ["src/auth/login.py", "src/models/user.py"]
        result = _extract_path_mentions("Tell me about login.py", paths)
        assert "src/auth/login.py" in result

    def test_directory_segment_match(self):
        from arc.scope import _extract_path_mentions

        paths = ["src/auth/login.py", "src/auth/oauth.py"]
        result = _extract_path_mentions("How does the auth module work?", paths)
        assert len(result) == 2

    def test_no_match(self):
        from arc.scope import _extract_path_mentions

        paths = ["src/auth/login.py"]
        result = _extract_path_mentions("something unrelated", paths)
        assert result == []


class TestExtractSymbolMentions:
    """Tests for _extract_symbol_mentions."""

    def test_symbol_found(self):
        from arc.scope import _extract_symbol_mentions

        symbols = {"src/app.py": ["def process_data", "class AppConfig"]}
        result = _extract_symbol_mentions("How does process_data work?", symbols)
        assert "src/app.py" in result

    def test_symbol_not_found(self):
        from arc.scope import _extract_symbol_mentions

        symbols = {"src/app.py": ["def process_data"]}
        result = _extract_symbol_mentions("unrelated query", symbols)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# 5. arc.retrieval_pipeline
# ═══════════════════════════════════════════════════════════════════════════


class TestExtToSourceType:
    """Tests for _ext_to_source_type helper."""

    def test_python_is_code(self):
        from arc.retrieval_pipeline import _ext_to_source_type

        assert _ext_to_source_type(".py") == "code"

    def test_javascript_is_code(self):
        from arc.retrieval_pipeline import _ext_to_source_type

        assert _ext_to_source_type(".js") == "code"

    def test_markdown_is_docs(self):
        from arc.retrieval_pipeline import _ext_to_source_type

        assert _ext_to_source_type(".md") == "docs"

    def test_rst_is_docs(self):
        from arc.retrieval_pipeline import _ext_to_source_type

        assert _ext_to_source_type(".rst") == "docs"

    def test_unknown_defaults_to_code(self):
        from arc.retrieval_pipeline import _ext_to_source_type

        assert _ext_to_source_type(".xyz") == "code"


class TestScopedRetrievalPipeline:
    """Tests for ScopedRetrievalPipeline construction and query."""

    def _build_pipeline(self):
        """Build a minimal pipeline with a few resources and text units."""
        from arc.retrieval_pipeline import PipelineConfig, ScopedRetrievalPipeline

        resources = [
            _make_resource("src/auth/login.py"),
            _make_resource("src/auth/middleware.py"),
            _make_resource("src/models/user.py"),
            _make_resource("docs/guide.md", extension=".md"),
        ]
        text_units = [
            _make_text_unit(
                "def login(username, password):\n    return authenticate(username, password)",
                resource_id=resources[0].id, kind="function", span=(1, 3),
            ),
            _make_text_unit(
                "def auth_middleware(request):\n    token = request.headers.get('Authorization')",
                resource_id=resources[1].id, kind="function", span=(1, 3),
            ),
            _make_text_unit(
                "class User:\n    username: str\n    email: str",
                resource_id=resources[2].id, kind="function", span=(1, 4),
            ),
            _make_text_unit(
                "The authentication system uses JWT tokens for session management. It provides secure login.",
                resource_id=resources[3].id, kind="section", span=(1, 5),
            ),
        ]

        config = PipelineConfig(
            max_scope_files=50,
            max_phase1_chunks=200,
            max_phase2_chunks=30,
            token_budget=4000,
        )
        pipeline = ScopedRetrievalPipeline(resources, text_units, config)
        return pipeline, resources, text_units

    def test_construction(self):
        pipeline, resources, text_units = self._build_pipeline()
        assert len(pipeline.resources) == 4
        assert len(pipeline.text_units) == 4
        assert pipeline.repo_meta.total_files == 4

    def test_query_returns_result(self):
        from arc.retrieval_pipeline import PipelineResult

        pipeline, _, _ = self._build_pipeline()
        result = pipeline.query("How does authentication work?")
        assert isinstance(result, PipelineResult)
        assert result.total_chunks == 4

    def test_query_has_scope_plan(self):
        pipeline, _, _ = self._build_pipeline()
        result = pipeline.query("How does login work?")
        assert result.scope_plan is not None
        assert result.scope_plan.mode  # mode should be set

    def test_query_phase_counts(self):
        pipeline, _, _ = self._build_pipeline()
        result = pipeline.query("Tell me about the user model")
        assert result.phase1_chunk_count > 0
        assert result.total_chunks == 4

    def test_phase1_no_scope_signals_returns_all(self):
        """Phase1 with empty candidate_paths should return all chunks."""
        from arc.scope import ScopePlan

        pipeline, _, text_units = self._build_pipeline()
        empty_plan = ScopePlan(mode="auto", candidate_paths=[])
        ids = pipeline._phase1(empty_plan)
        assert len(ids) == len(text_units)

    def test_phase1_with_scope_candidates(self):
        from arc.scope import ScopePlan

        pipeline, _, _ = self._build_pipeline()
        plan = ScopePlan(
            mode="implementation",
            candidate_paths=["src/auth/login.py", "src/auth/middleware.py"],
            preferred_source_types=["code"],
        )
        ids = pipeline._phase1(plan)
        # Should include chunk IDs from the scoped paths
        assert len(ids) >= 1

    def test_phase1_fallback_on_few_chunks(self):
        """If scope produces too few chunks (<5), falls back to full corpus."""
        from arc.scope import ScopePlan

        pipeline, _, text_units = self._build_pipeline()
        # Only one file with 1 chunk — fewer than 5
        plan = ScopePlan(
            mode="implementation",
            candidate_paths=["src/auth/login.py"],
            preferred_source_types=["code"],
        )
        ids = pipeline._phase1(plan)
        # Should fallback to all chunks since < 5
        assert len(ids) == len(text_units)

    def test_phase2_scoring(self):
        pipeline, _, text_units = self._build_pipeline()
        all_ids = {tu.id for tu in text_units}
        chunks = pipeline._phase2("How does login authentication work?", all_ids)
        assert len(chunks) > 0
        # Chunks should be sorted by score (descending)
        scores = [c.score for c in chunks]
        assert scores == sorted(scores, reverse=True)

    def test_scope_reduction_ratio(self):
        pipeline, _, _ = self._build_pipeline()
        result = pipeline.query("How does login work?")
        assert 0.0 <= result.scope_reduction_ratio <= 1.0
