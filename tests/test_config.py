import json

from orpheus.config import ConfigStore


class FakeDpapi:
    @staticmethod
    def protect(value):
        return ("protected:" + value).encode("utf-8")

    @staticmethod
    def unprotect(value):
        raw = value.decode("utf-8")
        return raw.removeprefix("protected:")


def test_lossless_migration_copies_but_keeps_legacy_files(tmp_path):
    legacy = tmp_path / "ResticRestoreTool"
    legacy.mkdir()
    config_bytes = b'{"backup_base_path":"Z:\\\\Backup","staging_dir":""}'
    secret_bytes = b'protected:{"HOST":"pw"}'
    (legacy / "config.json").write_bytes(config_bytes)
    (legacy / "secrets.bin").write_bytes(secret_bytes)
    (legacy / "ls_cache").mkdir()
    (legacy / "ls_cache" / "old.json").write_text("[]", encoding="utf-8")

    store = ConfigStore(str(tmp_path), dpapi_module=FakeDpapi)
    copied = store.ensure_and_migrate()

    assert "config.json" in copied
    assert (store.app_dir / "secrets.bin").read_bytes() == secret_bytes
    assert (legacy / "secrets.bin").read_bytes() == secret_bytes
    assert store.get_repo_password("HOST") == "pw"
    assert (store.app_dir / "ls_cache" / "old.json").exists()


def test_migration_never_overwrites_existing_orpheus_target(tmp_path):
    legacy = tmp_path / "ResticRestoreTool"
    current = tmp_path / "Orpheus"
    legacy.mkdir()
    current.mkdir()
    (legacy / "config.json").write_text('{"backup_base_path":"ALT"}', encoding="utf-8")
    (current / "config.json").write_text('{"backup_base_path":"NEU"}', encoding="utf-8")
    store = ConfigStore(str(tmp_path), dpapi_module=FakeDpapi)
    assert store.load_config()["backup_base_path"] == "NEU"
    assert json.loads((legacy / "config.json").read_text(encoding="utf-8"))["backup_base_path"] == "ALT"


def test_config_and_secrets_roundtrip_atomically(tmp_path):
    store = ConfigStore(str(tmp_path), dpapi_module=FakeDpapi)
    store.save_config({"backup_base_path": r"\\nas\Backup", "staging_dir": r"C:\Stage"})
    assert store.load_config()["staging_dir"] == r"C:\Stage"
    store.set_repo_password("HOST-Ä", "päss word")
    assert store.get_repo_password("HOST-Ä") == "päss word"
    assert not list(store.app_dir.glob("*.tmp"))


def test_broken_config_is_preserved_and_defaults_are_used(tmp_path):
    app_dir = tmp_path / "Orpheus"
    app_dir.mkdir()
    broken = app_dir / "config.json"
    broken.write_text("{kaputt", encoding="utf-8")
    store = ConfigStore(str(tmp_path), dpapi_module=FakeDpapi)
    assert store.load_config()["backup_base_path"] == ""
    assert broken.read_text(encoding="utf-8") == "{kaputt"
    assert store.last_warning
