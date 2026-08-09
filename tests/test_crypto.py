"""Optional Fernet encryption helpers."""
from pathlib import Path

from diary_app.core.crypto import (
    generate_key,
    encrypt_bytes,
    decrypt_bytes,
    write_json,
    read_json,
    is_encrypted_blob,
)


def test_roundtrip_bytes(monkeypatch):
    key = generate_key()
    monkeypatch.setenv("DIARY_KEY", key)
    monkeypatch.setenv("DIARY_ENCRYPT", "1")
    # reset fernet cache
    import diary_app.core.crypto as c

    c._fernet = None
    c._checked = False

    plain = b'{"hello": "world"}'
    enc = encrypt_bytes(plain)
    assert is_encrypted_blob(enc)
    assert decrypt_bytes(enc) == plain


def test_write_read_json(tmp_path, monkeypatch):
    key = generate_key()
    monkeypatch.setenv("DIARY_KEY", key)
    monkeypatch.setenv("DIARY_ENCRYPT", "1")
    import diary_app.core.crypto as c

    c._fernet = None
    c._checked = False

    path = tmp_path / "entry.json"
    write_json(path, {"id": "x", "n": 1})
    raw = path.read_bytes()
    assert is_encrypted_blob(raw)
    data = read_json(path)
    assert data["id"] == "x"
