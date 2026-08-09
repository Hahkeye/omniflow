"""Optional at-rest encryption for diary JSON (Fernet).

Enable by setting either:
  DIARY_ENCRYPT=1  and  DIARY_KEY=<url-safe base64 32-byte key>
or create ~/.diary/.key (Fernet key) and set DIARY_ENCRYPT=1.

When disabled, read/write are plain JSON (default).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .logutil import get_logger

log = get_logger("crypto")

_MAGIC = b"OMNIFLOW1"
_fernet = None
_checked = False


def encryption_enabled() -> bool:
    flag = os.environ.get("DIARY_ENCRYPT", "").strip().lower()
    return flag in ("1", "true", "yes", "on") and _get_fernet() is not None


def generate_key() -> str:
    """Return a new Fernet key as a URL-safe base64 string."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def ensure_key_file(path: Path | None = None) -> Path:
    """Create ~/.diary/.key if missing; return path. Does not enable encryption."""
    path = path or (Path.home() / "diary" / ".key")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(generate_key() + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        log.info("Created diary encryption key at %s", path)
    return path


def _load_key_bytes() -> bytes | None:
    env = os.environ.get("DIARY_KEY", "").strip()
    if env:
        return env.encode("ascii")
    key_path = Path(os.environ.get("DIARY_KEY_FILE", Path.home() / "diary" / ".key"))
    if key_path.is_file():
        raw = key_path.read_text(encoding="utf-8").strip()
        if raw:
            return raw.encode("ascii")
    return None


def _get_fernet():
    global _fernet, _checked
    if _checked:
        return _fernet
    _checked = True
    key = _load_key_bytes()
    if not key:
        _fernet = None
        return None
    try:
        from cryptography.fernet import Fernet

        _fernet = Fernet(key)
    except Exception as e:
        log.warning("Invalid DIARY_KEY / key file: %s", e)
        _fernet = None
    return _fernet


def encrypt_bytes(data: bytes) -> bytes:
    f = _get_fernet()
    if f is None:
        raise RuntimeError("Encryption requested but no valid DIARY_KEY is configured")
    return _MAGIC + f.encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    if not data.startswith(_MAGIC):
        return data  # plain
    f = _get_fernet()
    if f is None:
        raise RuntimeError("Encrypted diary file found but no DIARY_KEY configured")
    from cryptography.fernet import InvalidToken

    try:
        return f.decrypt(data[len(_MAGIC) :])
    except InvalidToken as e:
        raise RuntimeError("Failed to decrypt diary file (wrong key?)") from e


def is_encrypted_blob(data: bytes) -> bool:
    return data.startswith(_MAGIC)


def read_text(path: Path) -> str:
    raw = Path(path).read_bytes()
    if is_encrypted_blob(raw):
        return decrypt_bytes(raw).decode("utf-8")
    return raw.decode("utf-8")


def write_text(path: Path, text: str, *, encrypt: bool | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    use = encryption_enabled() if encrypt is None else encrypt
    data = text.encode("utf-8")
    if use:
        path.write_bytes(encrypt_bytes(data))
    else:
        path.write_bytes(data)


def read_json(path: Path) -> dict[str, Any]:
    try:
        text = read_text(path)
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.warning("Invalid JSON at %s: %s", path, e)
        return {}
    except Exception as e:
        log.warning("Failed to read %s: %s", path, e)
        return {}


def write_json(path: Path, data: dict[str, Any], *, encrypt: bool | None = None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    write_text(path, text, encrypt=encrypt)
