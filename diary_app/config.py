"""First-class application configuration.

Load order (later wins):
  1. Built-in defaults
  2. Config file (~/.config/omniflow/config.toml or $DIARY_DIR/config.toml)
  3. Environment variables
  4. Explicit overrides (CLI / tests)

Environment mapping (subset):
  DIARY_DIR / OMNIFLOW_DIARY_DIR
  DIARY_PROJECT_ROOT / OMNIFLOW_ROOT
  DIARY_PYTHON / PYTHON
  OMNIFLOW_DAEMON_HOST / OMNIFLOW_DAEMON_PORT
  DIARY_ENCRYPT / DIARY_KEY / DIARY_KEY_FILE
  OMNIFLOW_TORCH / OMNIFLOW_DEFAULT_BACKEND / OMNIFLOW_DEFAULT_DEVICE
  DIARY_LOG_LEVEL
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2  # domain/on-disk document version


def _default_config_paths() -> list[Path]:
    paths: list[Path] = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        paths.append(Path(xdg) / "omniflow" / "config.toml")
    paths.append(Path.home() / ".config" / "omniflow" / "config.toml")
    diary = os.environ.get("DIARY_DIR") or os.environ.get("OMNIFLOW_DIARY_DIR")
    if diary:
        paths.append(Path(diary).expanduser() / "config.toml")
    paths.append(Path.home() / "diary" / "config.toml")
    return paths


@dataclass
class AppConfig:
    """Runtime configuration shared by CLI, daemon, and UIs."""

    # Paths
    diary_dir: Path = field(default_factory=lambda: Path.home() / "diary")
    project_root: Path | None = None
    python_bin: str = "python3"

    # STT / compute
    default_backend: str = "auto"  # auto | moss | whisper | nemo
    default_device: str = "auto"  # auto | cuda | mps | cpu
    auto_backend_order: list[str] = field(
        default_factory=lambda: ["moss", "whisper", "nemo"]
    )
    max_speakers: int = 4

    # Daemon
    daemon_host: str = "127.0.0.1"
    daemon_port: int = 17432

    # Privacy
    encrypt: bool = False

    # Analysis
    analyzer: str = "heuristic"  # heuristic | (future: llm)

    # Logging
    log_level: str = "INFO"

    # Schema
    schema_version: int = SCHEMA_VERSION

    def ensure_dirs(self) -> None:
        self.diary_dir.mkdir(parents=True, exist_ok=True)
        (self.diary_dir / "entries").mkdir(parents=True, exist_ok=True)
        (self.diary_dir / "exports").mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["diary_dir"] = str(self.diary_dir)
        if self.project_root is not None:
            d["project_root"] = str(self.project_root)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        base = cls()
        if not data:
            return base
        kwargs: dict[str, Any] = {}
        if "diary_dir" in data and data["diary_dir"]:
            kwargs["diary_dir"] = Path(str(data["diary_dir"])).expanduser()
        if data.get("project_root"):
            kwargs["project_root"] = Path(str(data["project_root"])).expanduser()
        for key in (
            "python_bin",
            "default_backend",
            "default_device",
            "daemon_host",
            "analyzer",
            "log_level",
        ):
            if key in data and data[key] is not None:
                kwargs[key] = data[key]
        if "daemon_port" in data and data["daemon_port"] is not None:
            kwargs["daemon_port"] = int(data["daemon_port"])
        if "max_speakers" in data and data["max_speakers"] is not None:
            kwargs["max_speakers"] = int(data["max_speakers"])
        if "encrypt" in data:
            kwargs["encrypt"] = bool(data["encrypt"])
        if "auto_backend_order" in data and data["auto_backend_order"]:
            kwargs["auto_backend_order"] = list(data["auto_backend_order"])
        if "schema_version" in data:
            kwargs["schema_version"] = int(data["schema_version"])
        return replace(base, **kwargs)


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _env_overlay() -> dict[str, Any]:
    out: dict[str, Any] = {}
    diary = os.environ.get("DIARY_DIR") or os.environ.get("OMNIFLOW_DIARY_DIR")
    if diary:
        out["diary_dir"] = diary
    root = os.environ.get("DIARY_PROJECT_ROOT") or os.environ.get("OMNIFLOW_ROOT")
    if root:
        out["project_root"] = root
    py = os.environ.get("DIARY_PYTHON") or os.environ.get("PYTHON")
    if py:
        out["python_bin"] = py
    if os.environ.get("OMNIFLOW_DAEMON_HOST"):
        out["daemon_host"] = os.environ["OMNIFLOW_DAEMON_HOST"]
    if os.environ.get("OMNIFLOW_DAEMON_PORT"):
        try:
            out["daemon_port"] = int(os.environ["OMNIFLOW_DAEMON_PORT"])
        except ValueError:
            pass
    if os.environ.get("OMNIFLOW_DEFAULT_BACKEND"):
        out["default_backend"] = os.environ["OMNIFLOW_DEFAULT_BACKEND"]
    if os.environ.get("OMNIFLOW_DEFAULT_DEVICE"):
        out["default_device"] = os.environ["OMNIFLOW_DEFAULT_DEVICE"]
    enc = os.environ.get("DIARY_ENCRYPT", "").strip().lower()
    if enc in ("1", "true", "yes", "on"):
        out["encrypt"] = True
    elif enc in ("0", "false", "no", "off"):
        out["encrypt"] = False
    if os.environ.get("DIARY_LOG_LEVEL"):
        out["log_level"] = os.environ["DIARY_LOG_LEVEL"]
    if os.environ.get("OMNIFLOW_ANALYZER"):
        out["analyzer"] = os.environ["OMNIFLOW_ANALYZER"]
    return out


_CONFIG: AppConfig | None = None


def load_config(
    *,
    config_file: Path | str | None = None,
    overrides: dict[str, Any] | None = None,
    reload: bool = False,
) -> AppConfig:
    """Load and cache application config."""
    global _CONFIG
    if _CONFIG is not None and not reload and config_file is None and not overrides:
        return _CONFIG

    data: dict[str, Any] = {}
    if config_file:
        data.update(_load_toml(Path(config_file).expanduser()))
    else:
        for path in _default_config_paths():
            chunk = _load_toml(path)
            if chunk:
                # support [omniflow] table or flat
                if "omniflow" in chunk and isinstance(chunk["omniflow"], dict):
                    data.update(chunk["omniflow"])
                else:
                    data.update(chunk)
                break  # first found file wins as base file layer
    data.update(_env_overlay())
    if overrides:
        data.update(overrides)

    cfg = AppConfig.from_dict(data)
    # Sync encrypt flag into env so crypto module sees it
    if cfg.encrypt:
        os.environ.setdefault("DIARY_ENCRYPT", "1")
    _CONFIG = cfg
    return cfg


def get_config() -> AppConfig:
    """Return cached config (loads defaults/env if never loaded)."""
    return load_config()


def set_config(cfg: AppConfig) -> AppConfig:
    global _CONFIG
    _CONFIG = cfg
    return cfg


def reset_config() -> None:
    global _CONFIG
    _CONFIG = None


def get_diary_dir() -> Path:
    """Canonical diary root (config / DIARY_DIR / ~/diary). Use this everywhere."""
    return Path(get_config().diary_dir).expanduser()


def write_example_config(path: Path | None = None) -> Path:
    """Write a documented example config.toml."""
    path = path or (Path.home() / ".config" / "omniflow" / "config.toml")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = """# Omniflow configuration
# Docs: see README — load order: defaults → this file → environment → CLI

diary_dir = "~/diary"
# project_root = "/path/to/omniflow"
# python_bin = "python3"

default_backend = "auto"   # auto | moss | whisper | nemo
default_device = "auto"    # auto | cuda | mps | cpu
max_speakers = 4
auto_backend_order = ["moss", "whisper", "nemo"]

daemon_host = "127.0.0.1"
daemon_port = 17432

encrypt = false
analyzer = "heuristic"
log_level = "INFO"
"""
    path.write_text(text, encoding="utf-8")
    return path
