"""Persistent Orpheus configuration and lossless migration from the legacy folder."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from . import dpapi


NEW_APP_DIRNAME = "Orpheus"
LEGACY_APP_DIRNAME = "ResticRestoreTool"


class ConfigError(RuntimeError):
    """Configuration or secret store could not be processed safely."""


def default_staging_dir(appdata: str | None = None) -> str:
    root = appdata or os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not root:
        root = os.path.expanduser("~")
    return os.path.join(root, NEW_APP_DIRNAME, "Staging")


DEFAULT_CONFIG = {
    "backup_base_path": "",
    "staging_dir": "",
}


class ConfigStore:
    """Testable access to the config and the DPAPI blob.

    Migration only copies missing targets. The legacy folder is left completely
    intact; `secrets.bin` in particular is copied byte for byte.
    """

    def __init__(self, appdata: str | None = None, *, dpapi_module=dpapi):
        root = appdata or os.environ.get("APPDATA") or os.path.expanduser("~")
        self.app_dir = Path(root) / NEW_APP_DIRNAME
        self.legacy_dir = Path(root) / LEGACY_APP_DIRNAME
        self.config_path = self.app_dir / "config.json"
        self.secrets_path = self.app_dir / "secrets.bin"
        self.dpapi = dpapi_module
        self.last_warning = ""

    def ensure_and_migrate(self) -> list[str]:
        self.app_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        if not self.legacy_dir.is_dir():
            return copied
        for source in self.legacy_dir.rglob("*"):
            relative = source.relative_to(self.legacy_dir)
            target = self.app_dir / relative
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(source, target)
                    copied.append(str(relative))
                except OSError as exc:
                    self.last_warning = (
                        f"The legacy file '{relative}' could not be copied to Orpheus. "
                        f"The source is left untouched. ({exc})"
                    )
        return copied

    def load_config(self) -> dict:
        try:
            self.ensure_and_migrate()
            if not self.config_path.exists():
                return dict(DEFAULT_CONFIG)
            with self.config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("root element is not an object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.last_warning = (
                "The configuration could not be read. Orpheus uses default values; "
                f"the existing file is left unchanged. ({exc})"
            )
            return dict(DEFAULT_CONFIG)
        merged = dict(DEFAULT_CONFIG)
        merged.update({key: value for key, value in data.items() if key in DEFAULT_CONFIG})
        return merged

    def save_config(self, config: dict):
        self.ensure_and_migrate()
        payload = {key: config.get(key, default) for key, default in DEFAULT_CONFIG.items()}
        self._atomic_write(self.config_path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))

    def _load_secrets(self, *, strict: bool = False) -> dict:
        try:
            self.ensure_and_migrate()
            if not self.secrets_path.exists() or self.secrets_path.stat().st_size == 0:
                return {}
            plaintext = self.dpapi.unprotect(self.secrets_path.read_bytes())
            values = json.loads(plaintext)
            if not isinstance(values, dict):
                raise ValueError("secret store does not contain an object")
            return {str(key): str(value) for key, value in values.items()}
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            message = (
                "The stored passwords cannot be decrypted by this Windows user. "
                "Please enter the password again. The old file was not changed. "
                f"({exc})"
            )
            self.last_warning = message
            if strict:
                raise ConfigError(message) from exc
            return {}

    def get_repo_password(self, hostname: str) -> str | None:
        return self._load_secrets().get(hostname)

    def set_repo_password(self, hostname: str, password: str):
        secrets = self._load_secrets(strict=True)
        secrets[hostname] = password
        try:
            protected = self.dpapi.protect(json.dumps(secrets, ensure_ascii=False))
            self._atomic_write(self.secrets_path, protected)
        except OSError as exc:
            raise ConfigError(
                "The password could not be stored with Windows DPAPI. "
                "No unencrypted fallback file was created."
            ) from exc

    @staticmethod
    def _atomic_write(path: Path, data: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise


_STORE = ConfigStore()


def load_config() -> dict:
    return _STORE.load_config()


def save_config(config: dict):
    _STORE.save_config(config)


def get_repo_password(hostname: str) -> str | None:
    return _STORE.get_repo_password(hostname)


def set_repo_password(hostname: str, password: str):
    _STORE.set_repo_password(hostname, password)


def config_warning() -> str:
    return _STORE.last_warning


def app_dir() -> str:
    _STORE.ensure_and_migrate()
    return str(_STORE.app_dir)
