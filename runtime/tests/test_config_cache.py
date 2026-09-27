"""prefs()/vault() are mtime-cached: unchanged files aren't re-read, but an
actual edit is still picked up on the very next call (no daemon restart
needed to change model/provider mid-session)."""

import json
import os
import time

import support  # noqa: F401
from lib import config


def test_prefs_reflects_an_edit_without_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONF", tmp_path)
    monkeypatch.setattr(config, "_prefs_cache", {"mtime": None, "value": None})
    (tmp_path / "prefs.json").write_text(
        json.dumps({"provider": "openai", "model": "a"})
    )

    first = config.prefs()
    assert first["model"] == "a"

    # Force a distinct mtime — some filesystems have 1s mtime resolution,
    # and a same-second rewrite must still be detected as a change.
    os.utime(tmp_path / "prefs.json", (time.time() + 2, time.time() + 2))
    (tmp_path / "prefs.json").write_text(
        json.dumps({"provider": "openai", "model": "b"})
    )

    second = config.prefs()
    assert second["model"] == "b"


def test_prefs_is_not_reread_when_the_file_has_not_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONF", tmp_path)
    monkeypatch.setattr(config, "_prefs_cache", {"mtime": None, "value": None})
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"provider": "openai", "model": "a"}))

    config.prefs()
    reads = []
    original_read_text = type(path).read_text

    def counting_read_text(self, *a, **kw):
        reads.append(self)
        return original_read_text(self, *a, **kw)

    monkeypatch.setattr(type(path), "read_text", counting_read_text)
    config.prefs()
    config.prefs()
    assert reads == [], "prefs() re-read an unchanged file"


def test_prefs_returns_a_copy_callers_cannot_corrupt_the_cache_with(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "CONF", tmp_path)
    monkeypatch.setattr(config, "_prefs_cache", {"mtime": None, "value": None})
    (tmp_path / "prefs.json").write_text(
        json.dumps({"provider": "openai", "model": "a"})
    )

    got = config.prefs()
    got["model"] = "tampered"
    assert config.prefs()["model"] == "a"


def test_vault_reflects_an_edit_without_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONF", tmp_path)
    monkeypatch.setattr(config, "_vault_cache", {"mtime": None, "value": {}})
    keys = tmp_path / "keys.env"
    keys.write_text("export FOO='one'\n")

    assert config.vault()["FOO"] == "one"

    os.utime(keys, (time.time() + 2, time.time() + 2))
    keys.write_text("export FOO='two'\n")
    assert config.vault()["FOO"] == "two"


def test_vault_missing_file_is_cached_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONF", tmp_path)
    monkeypatch.setattr(config, "_vault_cache", {"mtime": None, "value": {}})
    assert config.vault() == {}
