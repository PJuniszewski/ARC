"""Tests for arc init — project detection, config, query generation, --json mode."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from arc.init import (
    detect_project, estimate_size, extract_top_claims,
    generate_heuristic_queries, generate_llm_queries,
    pick_defaults, write_arcconfig, read_arcconfig,
    _extract_names_from_claims,
)
from arc.models import Claim, EvidencePointer


class TestDetectProject:
    def test_detect_python(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "myapp"\n')
        info = detect_project(tmp_path)
        assert info["type"] == "python"
        assert info["name"] == "myapp"
        assert "pyproject.toml" in info["markers"]

    def test_detect_javascript(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "my-app"}')
        info = detect_project(tmp_path)
        assert info["type"] == "javascript"
        assert info["name"] == "my-app"

    def test_detect_go(self, tmp_path):
        (tmp_path / "go.mod").write_text("module github.com/user/proj")
        info = detect_project(tmp_path)
        assert info["type"] == "go"

    def test_detect_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "mylib"\n')
        info = detect_project(tmp_path)
        assert info["type"] == "rust"
        assert info["name"] == "mylib"

    def test_detect_generic(self, tmp_path):
        info = detect_project(tmp_path)
        assert info["type"] == "generic"

    def test_detect_arc_repo(self):
        repo = Path(__file__).parent.parent
        info = detect_project(repo)
        assert info["type"] == "python"
        assert "pyproject.toml" in info["markers"]


class TestEstimateSize:
    def test_count_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
        (tmp_path / "b.py").write_text("z = 3\n")
        size = estimate_size(tmp_path)
        assert size["files"] == 2
        assert size["lines"] == 3

    def test_skip_hidden_dirs(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("hidden")
        (tmp_path / "main.py").write_text("print('hi')\n")
        size = estimate_size(tmp_path)
        assert size["files"] == 1

    def test_skip_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "big.js").write_text("x" * 10000)
        (tmp_path / "app.js").write_text("console.log('hi')\n")
        size = estimate_size(tmp_path)
        assert size["files"] == 1


class TestPickDefaults:
    def test_python_defaults(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "docs").mkdir()
        defaults = pick_defaults("python", {"lines": 5000}, tmp_path)
        assert "src" in defaults["scan"]
        assert defaults["embeddings"] in ("tfidf", "neural")

    def test_fallback_to_dot(self, tmp_path):
        defaults = pick_defaults("python", {"lines": 100}, tmp_path)
        assert defaults["scan"] == ["."]


class TestArcconfig:
    def test_write_and_read(self, tmp_path):
        config = {
            "name": "test-project",
            "type": "python",
            "scan": ["src", "docs"],
            "ignore": [".venv", "__pycache__"],
            "embeddings": "tfidf",
        }
        config_path = tmp_path / ".arcconfig"
        write_arcconfig(config, config_path)
        assert config_path.exists()

        loaded = read_arcconfig(config_path)
        assert loaded["project"]["name"] == "test-project"
        assert loaded["project"]["type"] == "python"
        assert loaded["build"]["scan"] == ["src", "docs"]
        assert loaded["build"]["embeddings"] == "tfidf"


class TestExtractTopClaims:
    def test_extracts_diverse_claims(self):
        claims = [
            Claim(text="ContentAddressedStore uses SHA-256 for blob addressing",
                  claim_type="observation", confidence=0.9,
                  evidence=[EvidencePointer(source_unit_id="su-1")]),
            Claim(text="should migrate to JWT for stateless auth",
                  claim_type="decision", confidence=0.8),
            Claim(text="x", claim_type="observation"),  # too short, filtered
            Claim(text="build_archive processes 8 stages from ingest to validate",
                  claim_type="observation", confidence=0.85),
        ]
        top = extract_top_claims(claims, n=5)
        assert len(top) == 3  # short one filtered
        assert all("type" in c and "text" in c for c in top)
        # Decision should be boosted
        types = [c["type"] for c in top]
        assert "decision" in types

    def test_limits_to_n(self):
        claims = [Claim(text=f"observation number {i} about the codebase architecture")
                  for i in range(20)]
        top = extract_top_claims(claims, n=5)
        assert len(top) == 5


class TestExtractNames:
    def test_finds_class_names(self):
        claims = [
            Claim(text="ContentAddressedStore uses SHA-256 for blob storage"),
            Claim(text="BuildResult contains the manifest and all claims"),
            Claim(text="The VectorStore supports cosine similarity search"),
        ]
        names = _extract_names_from_claims(claims)
        assert "ContentAddressedStore" in names
        assert "BuildResult" in names
        assert "VectorStore" in names

    def test_finds_function_names(self):
        claims = [
            Claim(text="build_archive processes 8 stages"),
            Claim(text="extract_claims uses regex patterns"),
            Claim(text="verify_blob recomputes the hash"),
        ]
        names = _extract_names_from_claims(claims)
        assert "build_archive" in names
        assert "extract_claims" in names


class TestHeuristicQueries:
    def test_generates_from_names(self):
        claims = [
            Claim(text="ContentAddressedStore provides SHA-256 blob storage"),
            Claim(text="build_archive runs the 8-stage extraction pipeline"),
            Claim(text="VectorStore implements cosine similarity search"),
        ]
        queries = generate_heuristic_queries(claims, "project.arc")
        assert len(queries) == 3
        assert all("arc load project.arc" in q for q in queries)
        # Should use actual names, not generic words
        all_text = " ".join(queries)
        assert "ContentAddressedStore" in all_text or "build archive" in all_text

    def test_fallback_when_no_names(self):
        claims = [Claim(text="this is a simple text with no names")]
        queries = generate_heuristic_queries(claims)
        assert len(queries) == 3
        assert "architecture overview" in queries[-1]


class TestLLMQueries:
    def test_no_api_key_returns_none(self):
        """Without API keys, generate_llm_queries returns None."""
        with patch.dict("os.environ", {}, clear=True):
            result = generate_llm_queries([Claim(text="test claim about something")])
            assert result is None

    def test_api_failure_returns_none(self):
        """API call failure returns None silently."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
            # Will fail because key is fake — should return None, not raise
            result = generate_llm_queries(
                [Claim(text="test claim about something important")],
                timeout=1.0,
            )
            assert result is None


class TestInitCLI:
    def test_init_on_mini_project(self, tmp_path):
        from arc.cli import main

        (tmp_path / "pyproject.toml").write_text('[project]\nname = "mini"\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text(
            "class MyService:\n"
            "    '''Main service class.'''\n"
            "    def process_request(self, request):\n"
            "        return self.validate(request)\n"
        )

        ret = main(["init", str(tmp_path)])
        assert ret == 0
        assert (tmp_path / ".arcconfig").exists()
        assert (tmp_path / "mini.arc").is_file()

    def test_init_json_mode(self, tmp_path, capsys):
        from arc.cli import main

        (tmp_path / "pyproject.toml").write_text('[project]\nname = "jsontest"\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text(
            "class AuthMiddleware:\n"
            "    def authenticate(self, request):\n"
            "        return check_token(request.headers)\n"
        )

        ret = main(["init", str(tmp_path), "--json"])
        assert ret == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["project"] == "jsontest"
        assert data["language"] == "python"
        assert "files_scanned" in data
        assert "claims_extracted" in data
        assert "artifact" in data
        assert "top_claims" in data
        assert isinstance(data["top_claims"], list)

    def test_init_json_parseable(self, tmp_path, capsys):
        """JSON output must be valid JSON (pipe test)."""
        from arc.cli import main

        (tmp_path / "main.py").write_text("def hello(): pass\n")
        ret = main(["init", str(tmp_path), "--json", "--name", "pipetest"])
        assert ret == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)  # must not raise
        assert "artifact_size_kb" in data

    def test_init_no_build(self, tmp_path):
        from arc.cli import main

        (tmp_path / "package.json").write_text('{"name": "js-app"}')
        ret = main(["init", str(tmp_path), "--no-build"])
        assert ret == 0
        assert (tmp_path / ".arcconfig").exists()
        assert not (tmp_path / "js-app.arc").exists()

    def test_init_with_name_override(self, tmp_path):
        from arc.cli import main

        (tmp_path / "main.py").write_text("x = 1\n")
        ret = main(["init", str(tmp_path), "--name", "custom-name"])
        assert ret == 0
        assert (tmp_path / "custom-name.arc").is_file()

    def test_init_heuristic_uses_names(self, tmp_path, capsys):
        """Mode 3: heuristic queries should use class/function names."""
        from arc.cli import main

        (tmp_path / "pyproject.toml").write_text('[project]\nname = "nametest"\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "service.py").write_text(
            "class RequestHandler:\n"
            "    '''Handles HTTP requests and validates input.'''\n"
            "    def process_request(self, req):\n"
            "        '''Process an incoming request.'''\n"
            "        return self.validate(req)\n"
            "\n"
            "def build_response(data):\n"
            "    '''Build an HTTP response from data.'''\n"
            "    return {'status': 200, 'body': data}\n"
        )
        (src / "README.md").write_text(
            "# NameTest\n\n"
            "## Architecture\n\n"
            "RequestHandler is the main entry point for all HTTP requests.\n"
            "The build_response function provides a standardized response format.\n"
            "The system uses process_request to validate and handle incoming data.\n"
        )

        # No API key → mode 3 (heuristic)
        with patch.dict("os.environ", {}, clear=True):
            ret = main(["init", str(tmp_path)])

        assert ret == 0
        captured = capsys.readouterr()
        # Should contain class or function names, not generic words
        output = captured.out
        assert "RequestHandler" in output or "process_request" in output or "build_response" in output or "process request" in output or "build response" in output
