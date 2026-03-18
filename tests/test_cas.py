"""Unit tests for Content-Addressed Storage."""

import json

import pytest

from arc.cas import ContentAddressedStore, sha256_digest


class TestSha256Digest:
    def test_deterministic(self):
        data = b"hello world"
        assert sha256_digest(data) == sha256_digest(data)

    def test_different_content(self):
        assert sha256_digest(b"hello") != sha256_digest(b"world")

    def test_known_hash(self):
        # SHA-256 of empty string
        assert sha256_digest(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class TestContentAddressedStore:
    def test_initialize(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()
        assert (tmp_path / "test.arc" / "blobs" / "sha256").is_dir()
        assert (tmp_path / "test.arc" / "refs").is_dir()
        assert (tmp_path / "test.arc" / "meta").is_dir()

    def test_store_and_retrieve(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        data = b"test content"
        digest = cas.store_blob(data)
        assert digest == sha256_digest(data)

        retrieved = cas.retrieve_blob(digest)
        assert retrieved == data

    def test_deduplication(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        data = b"same content"
        d1 = cas.store_blob(data)
        d2 = cas.store_blob(data)
        assert d1 == d2
        assert len(cas.list_blobs()) == 1

    def test_verify_blob_valid(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        digest = cas.store_blob(b"test")
        assert cas.verify_blob(digest) is True

    def test_verify_blob_tampered(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        digest = cas.store_blob(b"original")
        # Tamper with the blob
        blob_path = cas.blobs_dir / digest
        blob_path.write_bytes(b"tampered")
        assert cas.verify_blob(digest) is False

    def test_verify_blob_missing(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()
        assert cas.verify_blob("nonexistent") is False

    def test_has_blob(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        digest = cas.store_blob(b"test")
        assert cas.has_blob(digest) is True
        assert cas.has_blob("nonexistent") is False

    def test_list_blobs(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        d1 = cas.store_blob(b"data1")
        d2 = cas.store_blob(b"data2")
        blobs = cas.list_blobs()
        assert set(blobs) == {d1, d2}

    def test_store_and_read_json(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        data = {"key": "value", "nested": {"a": 1}}
        cas.store_json(data, "test.json")
        retrieved = cas.read_json("test.json")
        assert retrieved == data

    def test_write_and_read_manifest(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        manifest = {"schema_version": "1.0.0", "layers": []}
        cas.write_manifest(manifest)
        retrieved = cas.read_manifest()
        assert retrieved == manifest

    def test_verify_archive_valid(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        blob_data = b"test blob"
        digest = cas.store_blob(blob_data)

        manifest = {
            "schema_version": "1.0.0",
            "archive_id": "test",
            "layers": [{"digest": digest}],
        }
        # Compute root digest
        manifest_for_hash = dict(manifest)
        content = json.dumps(manifest_for_hash, sort_keys=True).encode()
        manifest["root_digest"] = sha256_digest(content)
        cas.write_manifest(manifest)

        result = cas.verify_archive()
        assert result.valid

    def test_verify_archive_tampered_blob(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        digest = cas.store_blob(b"original")
        manifest = {
            "schema_version": "1.0.0",
            "layers": [{"digest": digest}],
        }
        manifest_copy = dict(manifest)
        manifest["root_digest"] = sha256_digest(json.dumps(manifest_copy, sort_keys=True).encode())
        cas.write_manifest(manifest)

        # Tamper
        (cas.blobs_dir / digest).write_bytes(b"tampered")
        result = cas.verify_archive()
        assert not result.valid
        assert digest in result.failed_digests

    def test_verify_archive_missing_manifest(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()
        result = cas.verify_archive()
        assert not result.valid

    def test_archive_size(self, tmp_path):
        cas = ContentAddressedStore(tmp_path / "test.arc")
        cas.initialize()

        cas.store_blob(b"a" * 100)
        cas.store_blob(b"b" * 200)
        assert cas.archive_size() == 300

    def test_copy_blob_from(self, tmp_path):
        src = ContentAddressedStore(tmp_path / "src.arc")
        src.initialize()
        dst = ContentAddressedStore(tmp_path / "dst.arc")
        dst.initialize()

        digest = src.store_blob(b"shared data")
        assert dst.copy_blob_from(src, digest)
        assert dst.has_blob(digest)
        assert dst.retrieve_blob(digest) == b"shared data"
