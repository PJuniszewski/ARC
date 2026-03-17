"""Tests for error conditions — empty dirs, corrupt blobs, bad JSON, missing files."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from arc.builder import build_archive
from arc.cas import ContentAddressedStore
from arc.loader import load
from arc.models import (
    EvidencePointer,
    Layer,
    PolicyRule,
    Resource,
    TextUnit,
    ToolDeclaration,
    WorkflowStep,
)


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


class TestEmptySourceDirectory:
    """Builder should handle empty source directories gracefully."""

    def test_build_empty_dir(self, tmp_dir):
        source = tmp_dir / "empty_source"
        source.mkdir()
        out = tmp_dir / "out_archive"

        result = build_archive(source_dir=source, output_dir=out)

        # Should succeed but produce an archive with no resources
        assert result.valid
        assert len(result.resources) == 0
        assert len(result.text_units) == 0
        assert len(result.claims) == 0

    def test_build_dir_with_only_unsupported_files(self, tmp_dir):
        source = tmp_dir / "unsupported"
        source.mkdir()
        (source / "image.png").write_bytes(b"\x89PNG\r\n")
        (source / "data.bin").write_bytes(b"\x00\x01\x02")
        out = tmp_dir / "out_archive"

        result = build_archive(source_dir=source, output_dir=out)

        assert result.valid
        assert len(result.resources) == 0


class TestCorruptArchive:
    """Loader should reject archives with corrupt data."""

    def _build_valid_archive(self, tmp_dir):
        source = tmp_dir / "source"
        source.mkdir()
        (source / "doc.md").write_text("# Test\n\nThis is a test document with enough content to extract.")
        out = tmp_dir / "archive"
        result = build_archive(source_dir=source, output_dir=out)
        assert result.valid
        return out

    def test_load_missing_manifest(self, tmp_dir):
        archive = tmp_dir / "no_manifest"
        archive.mkdir()
        (archive / "blobs" / "sha256").mkdir(parents=True)

        loaded = load(archive)

        assert loaded.rejected
        assert "Missing manifest" in loaded.reason

    def test_load_corrupt_json_blob(self, tmp_dir):
        archive = self._build_valid_archive(tmp_dir)

        # Corrupt one of the layer blobs
        manifest_path = archive / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for layer in manifest["layers"]:
            blob_path = archive / "blobs" / "sha256" / layer["digest"]
            if blob_path.exists():
                # Write invalid JSON
                blob_path.write_bytes(b"not valid json {{{")
                break

        loaded = load(archive)

        # Should be rejected due to digest mismatch (content changed)
        assert loaded.rejected

    def test_load_missing_required_blob(self, tmp_dir):
        archive = self._build_valid_archive(tmp_dir)

        # Delete a required blob
        manifest = json.loads((archive / "manifest.json").read_text())
        for layer in manifest["layers"]:
            if layer.get("required", False):
                blob_path = archive / "blobs" / "sha256" / layer["digest"]
                if blob_path.exists():
                    blob_path.unlink()
                    break

        loaded = load(archive)

        assert loaded.rejected
        assert "Missing required blob" in loaded.reason

    def test_verify_corrupt_archive(self, tmp_dir):
        archive = self._build_valid_archive(tmp_dir)

        # Tamper with manifest root_digest
        manifest_path = archive / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["root_digest"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, indent=2))

        cas = ContentAddressedStore(archive)
        result = cas.verify_archive()

        assert not result.valid
        assert any("root_digest mismatch" in e for e in result.errors)


class TestMalformedInput:
    """Builder should handle malformed input files."""

    def test_build_with_binary_in_text_file(self, tmp_dir):
        source = tmp_dir / "source"
        source.mkdir()
        # Write binary content with .md extension
        (source / "binary.md").write_bytes(b"\x00\x01\x02\xff\xfe\xfd" * 100)
        out = tmp_dir / "archive"

        # Should not crash — errors="replace" handles encoding issues
        result = build_archive(source_dir=source, output_dir=out)
        assert result.valid

    def test_build_with_empty_text_file(self, tmp_dir):
        source = tmp_dir / "source"
        source.mkdir()
        (source / "empty.md").write_text("")
        out = tmp_dir / "archive"

        result = build_archive(source_dir=source, output_dir=out)
        assert result.valid


class TestLoaderEdgeCases:
    """Loader edge cases."""

    def test_load_nonexistent_path(self, tmp_dir):
        loaded = load(tmp_dir / "does_not_exist")
        assert loaded.rejected

    def test_load_with_invalid_version_check(self, tmp_dir):
        source = tmp_dir / "source"
        source.mkdir()
        (source / "doc.md").write_text("# Test\n\nContent here for extraction.")
        out = tmp_dir / "archive"
        build_archive(source_dir=source, output_dir=out)

        # Request a version higher than what was built
        loaded = load(out, expected_min_version="99.0.0")
        assert loaded.rejected
        assert "rollback" in loaded.reason.lower()


class TestCLIErrorHandling:
    """CLI should not crash with tracebacks."""

    def test_cli_build_nonexistent_source(self, tmp_dir):
        from arc.cli import main

        # Nonexistent source produces an empty but valid archive (os.walk yields nothing)
        ret = main(["build", str(tmp_dir / "nonexistent"), "--out", str(tmp_dir / "out")])
        assert ret == 0

    def test_cli_inspect_nonexistent_archive(self, tmp_dir):
        from arc.cli import main

        ret = main(["inspect", str(tmp_dir / "nonexistent")])
        assert ret == 1

    def test_cli_verify_nonexistent_archive(self, tmp_dir):
        from arc.cli import main

        ret = main(["verify", str(tmp_dir / "nonexistent")])
        # verify of nonexistent returns failed verification or error
        assert ret == 1

    def test_cli_no_command(self):
        from arc.cli import main

        ret = main([])
        assert ret == 1


class TestFromDictRobustness:
    """from_dict methods should tolerate missing and extra fields."""

    def test_textunit_missing_span(self):
        tu = TextUnit.from_dict({
            "id": "x", "resource_id": "r", "kind": "section",
            "content": "hello", "content_digest": "abc",
        })
        assert tu.span == (0, 0)

    def test_textunit_extra_fields(self):
        tu = TextUnit.from_dict({
            "id": "x", "resource_id": "r", "kind": "section",
            "content": "hello", "span": [1, 5], "content_digest": "abc",
            "future_field": "ignored",
        })
        assert tu.span == (1, 5)
        assert not hasattr(tu, "future_field")

    def test_evidence_pointer_missing_source_unit_id(self):
        ep = EvidencePointer.from_dict({})
        assert ep.source_unit_id == ""
        assert ep.span is None
        assert ep.weight == 1.0

    def test_resource_extra_fields(self):
        r = Resource.from_dict({
            "id": "r1", "kind": "file", "locator": "/tmp/f",
            "content_digest": "abc", "metadata": {},
            "new_field": "ignored",
        })
        assert r.id == "r1"
        assert not hasattr(r, "new_field")

    def test_tool_declaration_extra_fields(self):
        td = ToolDeclaration.from_dict({
            "name": "grep", "description": "search",
            "unknown_v2_field": True,
        })
        assert td.name == "grep"

    def test_policy_rule_extra_fields(self):
        pr = PolicyRule.from_dict({
            "scope": "write", "effect": "deny",
            "v2_metadata": {"tag": "test"},
        })
        assert pr.scope == "write"

    def test_workflow_step_extra_fields(self):
        ws = WorkflowStep.from_dict({
            "name": "step1", "kind": "task",
            "future_depends": ["x"],
        })
        assert ws.name == "step1"

    def test_layer_extra_fields(self):
        ly = Layer.from_dict({
            "name": "claims", "type": "semantic.claims",
            "digest": "abc123", "annotations": {"new": True},
        })
        assert ly.name == "claims"
        assert ly.digest == "abc123"
