"""Tests for SqliteCAS — single-file SQLite archive backend."""

import json
import sqlite3

import pytest

from arc.cas import SqliteCAS, ContentAddressedStore, sha256_digest, open_cas, create_cas


class TestSqliteCAS:
    def test_initialize_creates_tables(self, tmp_path):
        db = tmp_path / "test.arc"
        cas = SqliteCAS(db)
        cas.initialize()
        assert db.is_file()

        # Verify tables exist
        conn = sqlite3.connect(str(db))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "blobs" in tables
        assert "meta" in tables
        conn.close()
        cas.close()

    def test_store_and_retrieve(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()

        data = b"test content"
        digest = cas.store_blob(data)
        assert digest == sha256_digest(data)
        assert cas.retrieve_blob(digest) == data
        cas.close()

    def test_deduplication(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()

        d1 = cas.store_blob(b"same")
        d2 = cas.store_blob(b"same")
        assert d1 == d2
        assert len(cas.list_blobs()) == 1
        cas.close()

    def test_has_blob(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        digest = cas.store_blob(b"x")
        assert cas.has_blob(digest)
        assert not cas.has_blob("nonexistent")
        cas.close()

    def test_verify_blob_valid(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        digest = cas.store_blob(b"original")
        assert cas.verify_blob(digest) is True
        cas.close()

    def test_verify_blob_tampered(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        digest = cas.store_blob(b"original")
        cas._test_tamper_blob(digest, b"tampered")
        assert cas.verify_blob(digest) is False
        cas.close()

    def test_list_blobs(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        d1 = cas.store_blob(b"a")
        d2 = cas.store_blob(b"b")
        assert set(cas.list_blobs()) == {d1, d2}
        cas.close()

    def test_store_and_read_json(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        data = {"key": "value", "nested": {"a": 1}}
        cas.store_json(data, "test.json")
        assert cas.read_json("test.json") == data
        cas.close()

    def test_write_and_read_manifest(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        manifest = {"schema_version": "1.0.0", "layers": []}
        cas.write_manifest(manifest)
        assert cas.read_manifest() == manifest
        cas.close()

    def test_archive_size(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        cas.store_blob(b"a" * 100)
        cas.store_blob(b"b" * 200)
        assert cas.archive_size() == 300
        cas.close()

    def test_verify_archive_valid(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        digest = cas.store_blob(b"test blob")
        manifest = {
            "schema_version": "1.0.0",
            "archive_id": "test",
            "layers": [{"digest": digest}],
        }
        manifest_for_hash = dict(manifest)
        manifest["root_digest"] = sha256_digest(
            json.dumps(manifest_for_hash, sort_keys=True).encode()
        )
        cas.write_manifest(manifest)
        assert cas.verify_archive().valid
        cas.close()

    def test_verify_archive_tampered(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        digest = cas.store_blob(b"original")
        manifest = {
            "schema_version": "1.0.0",
            "layers": [{"digest": digest}],
        }
        manifest["root_digest"] = sha256_digest(
            json.dumps(dict(manifest), sort_keys=True).encode()
        )
        cas.write_manifest(manifest)
        cas._test_tamper_blob(digest, b"tampered")
        result = cas.verify_archive()
        assert not result.valid
        assert digest in result.failed_digests
        cas.close()

    def test_verify_archive_missing_blob(self, tmp_path):
        cas = SqliteCAS(tmp_path / "test.arc")
        cas.initialize()
        digest = cas.store_blob(b"data")
        manifest = {
            "schema_version": "1.0.0",
            "layers": [{"digest": digest}],
        }
        manifest["root_digest"] = sha256_digest(
            json.dumps(dict(manifest), sort_keys=True).encode()
        )
        cas.write_manifest(manifest)
        cas._test_delete_blob(digest)
        result = cas.verify_archive()
        assert not result.valid
        assert digest in result.missing_blobs
        cas.close()

    def test_copy_blob_from_directory(self, tmp_path):
        """Copy blob from directory CAS to SQLite CAS."""
        src = ContentAddressedStore(tmp_path / "dir.arc")
        src.initialize()
        digest = src.store_blob(b"shared")

        dst = SqliteCAS(tmp_path / "sqlite.arc")
        dst.initialize()
        assert dst.copy_blob_from(src, digest)
        assert dst.retrieve_blob(digest) == b"shared"
        dst.close()

    def test_copy_blob_from_sqlite(self, tmp_path):
        """Copy blob from SQLite CAS to directory CAS."""
        src = SqliteCAS(tmp_path / "src.arc")
        src.initialize()
        digest = src.store_blob(b"shared")

        dst = ContentAddressedStore(tmp_path / "dir.arc")
        dst.initialize()
        assert dst.copy_blob_from(src, digest)
        assert dst.retrieve_blob(digest) == b"shared"
        src.close()


class TestFactoryFunctions:
    def test_open_cas_file(self, tmp_path):
        db = tmp_path / "test.arc"
        cas = SqliteCAS(db)
        cas.initialize()
        cas.close()

        opened = open_cas(db)
        assert isinstance(opened, SqliteCAS)

    def test_open_cas_directory(self, tmp_path):
        d = tmp_path / "test.arc"
        d.mkdir()
        opened = open_cas(d)
        assert isinstance(opened, ContentAddressedStore)

    def test_open_cas_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            open_cas(tmp_path / "nonexistent.arc")

    def test_create_cas_sqlite(self, tmp_path):
        db = tmp_path / "new.arc"
        cas = create_cas(db, fmt="sqlite")
        assert isinstance(cas, SqliteCAS)
        assert db.is_file()

    def test_create_cas_directory(self, tmp_path):
        d = tmp_path / "new.arc"
        cas = create_cas(d, fmt="directory")
        assert isinstance(cas, ContentAddressedStore)
        assert d.is_dir()

    def test_create_cas_invalid_format(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown format"):
            create_cas(tmp_path / "bad.arc", fmt="zip")
