"""Credential paths: .env migration out of the project root (README Config)."""
from __future__ import annotations

from app.config import AlpacaCreds, load_creds, migrate_legacy_env, save_creds

ENV_TEXT = "APCA_API_KEY_ID=k\nAPCA_API_SECRET_KEY=s\n"


def test_migrate_moves_legacy_env(tmp_path):
    legacy = tmp_path / "project" / ".env"
    legacy.parent.mkdir()
    legacy.write_text(ENV_TEXT, encoding="utf-8")
    new = tmp_path / "data" / ".env"

    assert migrate_legacy_env(legacy, new) == "moved"
    assert not legacy.exists()
    assert new.read_text(encoding="utf-8") == ENV_TEXT


def test_migrate_prefers_existing_new_env(tmp_path, monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    legacy = tmp_path / ".env"
    legacy.write_text("APCA_API_KEY_ID=old\nAPCA_API_SECRET_KEY=old\n", encoding="utf-8")
    new = tmp_path / "data" / ".env"
    new.parent.mkdir()
    new.write_text("APCA_API_KEY_ID=new\nAPCA_API_SECRET_KEY=new\n", encoding="utf-8")

    assert migrate_legacy_env(legacy, new) == "stale-legacy"
    assert legacy.exists()  # never deleted when both exist — the user decides
    assert load_creds(new) == AlpacaCreds("new", "new")


def test_migrate_noop_without_legacy(tmp_path):
    assert migrate_legacy_env(tmp_path / ".env", tmp_path / "new" / ".env") is None
    assert not (tmp_path / "new" / ".env").exists()


def test_save_creds_creates_parent_dirs(tmp_path):
    target = tmp_path / "deep" / "dir" / ".env"
    save_creds(AlpacaCreds("k", "s"), target)
    assert target.read_text(encoding="utf-8") == ENV_TEXT


def test_environment_overrides_env_file(tmp_path, monkeypatch):
    envfile = tmp_path / ".env"
    envfile.write_text("APCA_API_KEY_ID=file\nAPCA_API_SECRET_KEY=file\n", encoding="utf-8")
    monkeypatch.setenv("APCA_API_KEY_ID", "env")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "env")
    assert load_creds(envfile) == AlpacaCreds("env", "env")
