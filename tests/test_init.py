"""Tests for arc init — project detection, config generation, example queries."""

from pathlib import Path

import pytest

from arc.init import detect_project, estimate_size, generate_example_queries, pick_defaults, write_arcconfig, read_arcconfig


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
        """Detect ARC's own repo type."""
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


class TestExampleQueries:
    def test_generates_queries(self):
        from arc.models import Claim, Resource
        claims = [
            Claim(text="authentication module uses JWT tokens for session management"),
            Claim(text="the builder extracts claims from source code"),
            Claim(text="security model prevents prompt injection attacks"),
        ]
        resources = [
            Resource(locator="src/auth.py"),
            Resource(locator="src/builder.py"),
        ]
        queries = generate_example_queries(claims, resources)
        assert len(queries) == 3
        assert all("arc load" in q for q in queries)


class TestInitCLI:
    def test_init_on_mini_project(self, tmp_path):
        from arc.cli import main

        (tmp_path / "pyproject.toml").write_text('[project]\nname = "mini"\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text(
            "def hello():\n"
            "    '''Say hello.'''\n"
            "    print('Hello, world!')\n"
        )

        ret = main(["init", str(tmp_path)])
        assert ret == 0
        assert (tmp_path / ".arcconfig").exists()
        assert (tmp_path / "mini.arc").is_file()  # single-file SQLite

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
