"""Platform / architecture detection for multi-arch installs.

Supported targets (Python wheels):
  - macOS arm64 (Apple Silicon) — MPS + CPU
  - macOS x86_64 (Intel) — CPU (MPS rare)
  - Linux x86_64 — CUDA or CPU
  - Linux aarch64 — CPU (CUDA only via special/Jetson builds)
  - Windows x86_64 — CUDA or CPU
  - Windows arm64 — CPU (limited torch wheels)

Torch is *not* installed by a single PyPI pin across arches: CUDA vs CPU
wheels live on different indexes. Use recommend_torch_install() / setup_venv.sh.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


# Default CUDA wheel channel (NVIDIA PC x86_64). Override with TORCH_CUDA_INDEX
# or OMNIFLOW_CUDA_CHANNEL=cu124|cu126|cu128|cu121
DEFAULT_CUDA_CHANNEL = os.environ.get("OMNIFLOW_CUDA_CHANNEL", "cu128")
TORCH_INDEX_BASE = "https://download.pytorch.org/whl"


@dataclass(frozen=True)
class PlatformProfile:
    """Normalized host profile used for install decisions."""

    os_name: str  # darwin | linux | windows | other
    arch: str  # x86_64 | aarch64 | arm64 | other
    python: str
    python_impl: str
    is_wsl: bool = False
    is_64bit: bool = True
    machine_raw: str = ""
    system_raw: str = ""
    nvidia_smi: bool = False
    nvidia_gpus: list[str] = field(default_factory=list)
    # Recommended torch mode after auto-detect
    torch_flavor: str = "cpu"  # cpu | cuda | default (PyPI / Mac)
    torch_index_url: str | None = None
    notes: list[str] = field(default_factory=list)
    supported: bool = True
    support_level: str = "full"  # full | partial | experimental | unsupported

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_arch(machine: str) -> str:
    m = (machine or "").lower()
    if m in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        # Apple reports arm64; Linux aarch64 — keep both spellings useful
        return "arm64" if sys.platform == "darwin" else "aarch64"
    if m in ("i386", "i686", "x86"):
        return "x86"
    return m or "unknown"


def _normalize_os(system: str) -> str:
    s = (system or "").lower()
    if s == "darwin":
        return "darwin"
    if s == "linux":
        return "linux"
    if s in ("windows", "win32", "cygwin"):
        return "windows"
    return s or "other"


def _detect_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        with open("/proc/version", encoding="utf-8", errors="ignore") as f:
            v = f.read().lower()
        if "microsoft" in v or "wsl" in v:
            return True
    except OSError:
        pass
    return bool(os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"))


def _nvidia_smi_gpus() -> tuple[bool, list[str]]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return False, []
    try:
        out = subprocess.run(
            [smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if out.returncode != 0:
            return True, []  # binary exists but failed (driver issue)
        lines = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
        return True, lines
    except (OSError, subprocess.TimeoutExpired):
        return True, []


def cuda_channel() -> str:
    """cu128 / cu126 / … from env."""
    ch = os.environ.get("OMNIFLOW_CUDA_CHANNEL") or os.environ.get("TORCH_CUDA_CHANNEL")
    if ch:
        ch = ch.strip().lower().lstrip("/")
        if not ch.startswith("cu") and not ch.startswith("rocm"):
            ch = f"cu{ch}" if ch.isdigit() or ch[0].isdigit() else ch
        return ch
    return DEFAULT_CUDA_CHANNEL


def torch_index_for_channel(channel: str) -> str:
    env = os.environ.get("TORCH_CUDA_INDEX") or os.environ.get("OMNIFLOW_TORCH_INDEX")
    if env:
        return env.rstrip("/")
    return f"{TORCH_INDEX_BASE}/{channel}"


def detect_platform(
    *,
    force_flavor: str | None = None,
) -> PlatformProfile:
    """
    Probe OS, CPU arch, and GPU to decide how to install PyTorch.

    force_flavor: override auto (cpu|cuda|default|auto)
    """
    system_raw = platform.system()
    machine_raw = platform.machine()
    os_name = _normalize_os(system_raw)
    arch = _normalize_arch(machine_raw)
    is_wsl = _detect_wsl()
    has_smi, gpus = _nvidia_smi_gpus()
    notes: list[str] = []
    supported = True
    support_level = "full"

    # Resolve forced flavor from env if not passed
    forced = (force_flavor or os.environ.get("OMNIFLOW_TORCH") or "auto").strip().lower()
    if forced in ("", "auto"):
        forced = "auto"

    # --- decide torch_flavor + index ---
    torch_flavor = "cpu"
    torch_index: str | None = None

    if os_name == "darwin":
        # Official macOS wheels on PyPI (arm64 + x86_64). MPS on Apple Silicon.
        torch_flavor = "default"
        torch_index = None
        if arch == "arm64":
            notes.append("Apple Silicon: PyTorch from PyPI enables MPS when available.")
        else:
            notes.append("Intel Mac: CPU wheels from PyPI (MPS usually unavailable).")
        if forced == "cuda":
            notes.append("CUDA is not available on macOS; using default Mac wheels.")
        if forced == "cpu":
            torch_flavor = "default"  # same wheels; device selection is runtime
            notes.append("OMNIFLOW_TORCH=cpu: install uses Mac wheels; runtime --device cpu.")

    elif os_name == "linux":
        if arch == "x86_64":
            want_cuda = forced == "cuda" or (
                forced == "auto" and has_smi and bool(gpus)
            )
            if forced == "cpu":
                want_cuda = False
            if want_cuda:
                ch = cuda_channel()
                torch_flavor = "cuda"
                torch_index = torch_index_for_channel(ch)
                if not has_smi:
                    notes.append(
                        "CUDA requested but nvidia-smi not found — install NVIDIA drivers "
                        "or set OMNIFLOW_TORCH=cpu."
                    )
                elif not gpus:
                    notes.append(
                        "nvidia-smi present but no GPUs listed — check drivers / WSL GPU setup."
                    )
                if is_wsl:
                    notes.append("WSL2: ensure Windows NVIDIA driver + GPU support is enabled.")
            else:
                torch_flavor = "cpu"
                torch_index = torch_index_for_channel("cpu")
                if has_smi and gpus and forced == "auto":
                    # should not happen
                    pass
                elif has_smi and not gpus:
                    notes.append("NVIDIA tooling found but no GPU; installing CPU wheels.")
                else:
                    notes.append(
                        "No NVIDIA GPU detected — CPU wheels. For CUDA later: "
                        "OMNIFLOW_TORCH=cuda bash diary_app/setup_venv.sh"
                    )
        elif arch == "aarch64":
            # Official CUDA wheels are primarily x86_64. aarch64 gets PyPI/CPU.
            torch_flavor = "default"
            torch_index = None
            support_level = "partial"
            notes.append(
                "Linux aarch64: installing PyPI torch (CPU). "
                "NVIDIA Jetson / aarch64 CUDA needs vendor-specific PyTorch builds."
            )
            if forced == "cuda":
                notes.append(
                    "OMNIFLOW_TORCH=cuda on aarch64 is not auto-supported; "
                    "install your board's CUDA torch wheel manually, then "
                    "pip install -e . --no-deps && pip install -r diary_app/requirements-core.txt"
                )
                support_level = "experimental"
            if is_wsl:
                notes.append("WSL on ARM: expect CPU-only unless you provide custom wheels.")
        else:
            supported = False
            support_level = "unsupported"
            torch_flavor = "default"
            notes.append(f"Unusual Linux arch {arch!r}: try PyPI torch or build from source.")

    elif os_name == "windows":
        if arch == "x86_64":
            want_cuda = forced == "cuda" or (forced == "auto" and has_smi and bool(gpus))
            if forced == "cpu":
                want_cuda = False
            if want_cuda:
                ch = cuda_channel()
                torch_flavor = "cuda"
                torch_index = torch_index_for_channel(ch)
            else:
                torch_flavor = "cpu"
                torch_index = torch_index_for_channel("cpu")
        elif arch in ("arm64", "aarch64"):
            torch_flavor = "default"
            torch_index = None
            support_level = "partial"
            notes.append("Windows ARM: limited torch wheels — using PyPI if available.")
        else:
            support_level = "experimental"
            torch_flavor = "default"
            notes.append(f"Windows arch {arch!r}: try PyPI torch.")

    else:
        supported = False
        support_level = "unsupported"
        torch_flavor = "default"
        notes.append(f"OS {os_name!r} is not a primary target; install torch manually.")

    # Python bitness
    is_64 = sys.maxsize > 2**32
    if not is_64:
        support_level = "unsupported"
        supported = False
        notes.append("32-bit Python is not supported. Use 64-bit Python 3.11+.")

    py_ver = platform.python_version()
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        support_level = "unsupported"
        supported = False
        notes.append(f"Python {py_ver} is too old; need 3.11+.")
    elif (major, minor) >= (3, 14):
        support_level = "experimental"
        notes.append(f"Python {py_ver} may lack wheels for some deps; 3.11–3.12 recommended.")

    return PlatformProfile(
        os_name=os_name,
        arch=arch,
        python=py_ver,
        python_impl=platform.python_implementation(),
        is_wsl=is_wsl,
        is_64bit=is_64,
        machine_raw=machine_raw,
        system_raw=system_raw,
        nvidia_smi=has_smi,
        nvidia_gpus=gpus,
        torch_flavor=torch_flavor,
        torch_index_url=torch_index,
        notes=notes,
        supported=supported,
        support_level=support_level,
    )


def recommend_torch_pip_args(
    profile: PlatformProfile | None = None,
    *,
    packages: tuple[str, ...] = ("torch", "torchaudio"),
) -> list[str]:
    """
    Return argv fragment after `pip install` for the correct torch wheels.

    Examples:
      ['torch', 'torchaudio']
      ['torch', 'torchaudio', '--index-url', 'https://download.pytorch.org/whl/cu128']
      ['torch', 'torchaudio', '--index-url', 'https://download.pytorch.org/whl/cpu']
    """
    profile = profile or detect_platform()
    args = list(packages)
    if profile.torch_index_url:
        # extra-index can pull wrong platforms; use index-url for CUDA/CPU channels
        args.extend(["--index-url", profile.torch_index_url])
    return args


def recommend_torch_command(profile: PlatformProfile | None = None) -> str:
    """Shell-friendly pip install line for documentation / scripts."""
    profile = profile or detect_platform()
    args = recommend_torch_pip_args(profile)
    # Quote for display
    parts = ["pip", "install", *args]
    return " ".join(parts)


def format_platform_report(profile: PlatformProfile | None = None) -> str:
    p = profile or detect_platform()
    lines = [
        "Install platform profile",
        f"  OS:           {p.os_name} ({p.system_raw})",
        f"  Arch:         {p.arch} (machine={p.machine_raw})",
        f"  Python:       {p.python} ({p.python_impl}, 64-bit={p.is_64bit})",
        f"  WSL:          {p.is_wsl}",
        f"  Support:      {p.support_level}" + ("" if p.supported else " — NOT SUPPORTED"),
        f"  nvidia-smi:   {p.nvidia_smi}",
        f"  Torch flavor: {p.torch_flavor}",
        f"  Torch index:  {p.torch_index_url or '(PyPI default)'}",
        f"  Install cmd:  {recommend_torch_command(p)}",
    ]
    if p.nvidia_gpus:
        lines.append("  GPUs (smi):")
        for g in p.nvidia_gpus:
            lines.append(f"    - {g}")
    if p.notes:
        lines.append("  Notes:")
        for n in p.notes:
            for part in n.splitlines():
                lines.append(f"    • {part}")
    return "\n".join(lines)


def doctor_checks() -> dict[str, Any]:
    """Runtime health check used by `diary_app doctor`."""
    p = detect_platform()
    checks: list[dict[str, Any]] = []
    ok = True

    def add(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        if not passed:
            ok = False
        checks.append({"name": name, "ok": passed, "detail": detail})

    add(
        "python_version",
        sys.version_info >= (3, 11),
        f"{platform.python_version()} (need >= 3.11)",
    )
    add("python_64bit", p.is_64bit, f"is_64bit={p.is_64bit}")
    add(
        "platform_supported",
        p.supported and p.support_level != "unsupported",
        f"{p.os_name}/{p.arch} level={p.support_level}",
    )

    try:
        import torch

        add("torch_import", True, f"torch {torch.__version__}")
        # Wheel / build hints
        cuda_built = getattr(torch.version, "cuda", None)
        add(
            "torch_cuda_build",
            True,
            f"cuda={cuda_built or 'none'} mps_built={hasattr(torch.backends, 'mps')}",
        )
        if p.torch_flavor == "cuda" and not torch.cuda.is_available():
            add(
                "cuda_runtime",
                False,
                "Expected CUDA torch but torch.cuda.is_available() is False. "
                "Re-run setup with OMNIFLOW_TORCH=cuda or fix drivers.",
            )
        elif p.torch_flavor == "cuda":
            add("cuda_runtime", True, f"device_count={torch.cuda.device_count()}")
        else:
            add(
                "cuda_runtime",
                True,
                f"cuda_available={torch.cuda.is_available()} (flavor={p.torch_flavor})",
            )
        # Arch sanity: torch module file path
        torch_file = getattr(torch, "__file__", "") or ""
        add("torch_path", True, torch_file)
    except ImportError as e:
        add("torch_import", False, f"not installed: {e}")

    try:
        import torchaudio  # noqa: F401

        add("torchaudio", True, "import ok")
    except ImportError as e:
        add("torchaudio", False, str(e))

    try:
        import diary_app  # noqa: F401

        add("diary_app", True, "import ok")
    except ImportError as e:
        add("diary_app", False, str(e))

    try:
        import moss_transcribe_diarize  # noqa: F401

        add("moss_backend_pkg", True, "import ok")
    except ImportError:
        add(
            "moss_backend_pkg",
            False,
            "moss-transcribe-diarize not installed (optional until first transcribe)",
        )

    # Writable diary dir
    diary = os.path.expanduser("~/diary")
    try:
        os.makedirs(diary, exist_ok=True)
        probe = os.path.join(diary, ".omniflow_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        add("diary_writable", True, diary)
    except OSError as e:
        add("diary_writable", False, f"{diary}: {e}")

    return {
        "ok": ok,
        "platform": p.to_dict(),
        "checks": checks,
        "torch_install_command": recommend_torch_command(p),
    }


def format_doctor_report() -> str:
    data = doctor_checks()
    lines = [format_platform_report(), "", "Doctor checks:"]
    for c in data["checks"]:
        mark = "✓" if c["ok"] else "✗"
        lines.append(f"  {mark} {c['name']}: {c['detail']}")
    lines.append("")
    lines.append("Overall: " + ("OK" if data["ok"] else "ISSUES FOUND"))
    if not data["ok"]:
        lines.append("Suggested torch install:")
        lines.append(f"  {data['torch_install_command']}")
    return "\n".join(lines)
