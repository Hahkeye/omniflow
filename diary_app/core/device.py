"""Shared GPU/CPU device detection for Mac + PC.

Priority for auto: CUDA (NVIDIA) → MPS (Apple Silicon) → CPU.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeviceInfo:
    """Resolved compute device plus human-readable details."""
    kind: str  # "cuda" | "mps" | "cpu"
    index: int | None  # CUDA device index, else None
    name: str  # e.g. "NVIDIA GeForce RTX 4090" or "Apple MPS" or "CPU"
    torch_device: Any  # torch.device
    dtype_name: str  # "bfloat16" | "float16" | "float32"
    details: str  # multi-line summary for logs/CLI

    @property
    def label(self) -> str:
        if self.kind == "cuda" and self.index is not None:
            return f"cuda:{self.index}"
        return self.kind


def _try_import_torch():
    try:
        import torch
        return torch
    except ImportError:
        return None


def cuda_available() -> bool:
    torch = _try_import_torch()
    return bool(torch is not None and torch.cuda.is_available())


def mps_available() -> bool:
    torch = _try_import_torch()
    if torch is None:
        return False
    return bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())


def list_cuda_gpus() -> list[dict]:
    """Return info dicts for each CUDA device (empty if none / no torch)."""
    torch = _try_import_torch()
    if torch is None or not torch.cuda.is_available():
        return []
    gpus = []
    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        total_gb = getattr(props, "total_memory", 0) / (1024 ** 3)
        gpus.append({
            "index": i,
            "name": props.name,
            "total_memory_gb": round(total_gb, 2),
            "major": getattr(props, "major", None),
            "minor": getattr(props, "minor", None),
        })
    return gpus


def detect_hardware() -> dict:
    """Probe what this machine can run (independent of user preference)."""
    torch = _try_import_torch()
    info: dict = {
        "torch_installed": torch is not None,
        "torch_version": getattr(torch, "__version__", None) if torch else None,
        "cuda_available": False,
        "cuda_built": False,
        "cuda_version": None,
        "gpus": [],
        "mps_available": False,
        "recommended": "cpu",
    }
    if torch is None:
        info["note"] = (
            "PyTorch is not installed. Install a CUDA build on NVIDIA PCs:\n"
            "  pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128"
        )
        return info

    info["cuda_built"] = bool(getattr(torch.version, "cuda", None))
    info["cuda_version"] = getattr(torch.version, "cuda", None)
    info["cuda_available"] = torch.cuda.is_available()
    info["gpus"] = list_cuda_gpus()
    info["mps_available"] = mps_available()

    if info["cuda_available"]:
        info["recommended"] = "cuda"
    elif info["mps_available"]:
        info["recommended"] = "mps"
    else:
        info["recommended"] = "cpu"
        if info["cuda_built"] is False or info["cuda_version"] is None:
            # CPU-only wheel on a machine that might still have an NVIDIA GPU
            info["note"] = (
                "PyTorch is a CPU-only build (no CUDA). If you have an NVIDIA GPU, reinstall:\n"
                "  pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128"
            )
    return info


def pick_dtype(torch_device) -> Any:
    """bf16 on capable CUDA; float16 optional; float32 elsewhere."""
    torch = _try_import_torch()
    if torch is None:
        return None
    if torch_device.type == "cuda":
        if torch.cuda.is_bf16_supported():
            return torch.bfloat16
        # Older GPUs: prefer float16 for speed/memory
        return torch.float16
    # MPS: float32 is most reliable for multimodal generate
    return torch.float32


def resolve_torch_device(preferred: str = "auto", cuda_index: int | None = None) -> DeviceInfo:
    """
    Pick a torch device.

    preferred: "auto" | "cuda" | "cuda:N" | "mps" | "cpu"
    cuda_index: optional override when preferred is "cuda" or "auto"
    """
    torch = _try_import_torch()
    if torch is None:
        raise RuntimeError(
            "PyTorch is not installed. Install torch for your platform first."
        )

    preferred = (preferred or "auto").strip().lower()
    gpus = list_cuda_gpus()

    def _cuda_device(idx: int) -> DeviceInfo:
        if not torch.cuda.is_available() or not gpus:
            raise RuntimeError(
                "CUDA was requested but is not available.\n"
                f"  torch.cuda.is_available()={torch.cuda.is_available()}\n"
                f"  torch.version.cuda={getattr(torch.version, 'cuda', None)}\n"
                "  Install a CUDA-enabled PyTorch build if you have an NVIDIA GPU."
            )
        if idx < 0 or idx >= len(gpus):
            raise RuntimeError(f"CUDA device index {idx} out of range (have {len(gpus)} GPU(s))")
        g = gpus[idx]
        dev = torch.device(f"cuda:{idx}")
        dtype = pick_dtype(dev)
        details = (
            f"Using NVIDIA GPU [{idx}] {g['name']} "
            f"({g['total_memory_gb']} GB), dtype={dtype}"
        )
        return DeviceInfo(
            kind="cuda",
            index=idx,
            name=g["name"],
            torch_device=dev,
            dtype_name=str(dtype).replace("torch.", ""),
            details=details,
        )

    def _mps_device() -> DeviceInfo:
        if not mps_available():
            raise RuntimeError("MPS was requested but is not available on this system.")
        dev = torch.device("mps")
        dtype = pick_dtype(dev)
        return DeviceInfo(
            kind="mps",
            index=None,
            name="Apple MPS",
            torch_device=dev,
            dtype_name=str(dtype).replace("torch.", ""),
            details=f"Using Apple Silicon MPS, dtype={dtype}",
        )

    def _cpu_device() -> DeviceInfo:
        dev = torch.device("cpu")
        dtype = pick_dtype(dev)
        return DeviceInfo(
            kind="cpu",
            index=None,
            name="CPU",
            torch_device=dev,
            dtype_name=str(dtype).replace("torch.", ""),
            details=f"Using CPU, dtype={dtype}",
        )

    # Explicit cuda:N
    if preferred.startswith("cuda:"):
        try:
            idx = int(preferred.split(":", 1)[1])
        except ValueError as e:
            raise RuntimeError(f"Invalid CUDA device spec: {preferred}") from e
        return _cuda_device(idx)

    if preferred == "cuda":
        idx = 0 if cuda_index is None else cuda_index
        return _cuda_device(idx)

    if preferred == "mps":
        return _mps_device()

    if preferred == "cpu":
        return _cpu_device()

    if preferred != "auto":
        # Unknown string — try torch.device directly
        dev = torch.device(preferred)
        dtype = pick_dtype(dev)
        return DeviceInfo(
            kind=dev.type,
            index=dev.index,
            name=str(dev),
            torch_device=dev,
            dtype_name=str(dtype).replace("torch.", ""),
            details=f"Using {dev}, dtype={dtype}",
        )

    # auto: CUDA → MPS → CPU
    if torch.cuda.is_available() and gpus:
        idx = 0 if cuda_index is None else cuda_index
        return _cuda_device(idx)
    if mps_available():
        return _mps_device()
    return _cpu_device()


def format_detect_report() -> str:
    """Pretty multi-line report for CLI `diary devices`."""
    try:
        from .platform_info import format_platform_report

        plat = format_platform_report()
    except Exception:
        plat = ""

    hw = detect_hardware()
    lines = []
    if plat:
        lines.extend(plat.splitlines())
        lines.append("")
    lines.extend([
        "Compute devices",
        f"  PyTorch:     {hw.get('torch_version') or 'not installed'}",
        f"  CUDA build:  {hw.get('cuda_version') or 'none (CPU wheel or no torch)'}",
        f"  CUDA ready:  {hw['cuda_available']}",
        f"  MPS ready:   {hw['mps_available']}",
        f"  Recommended: {hw['recommended']}",
    ])
    if hw["gpus"]:
        lines.append("  GPUs:")
        for g in hw["gpus"]:
            lines.append(
                f"    [{g['index']}] {g['name']} — {g['total_memory_gb']} GB"
            )
    else:
        lines.append("  GPUs:        (none detected by PyTorch)")
    if hw.get("note"):
        lines.append("")
        lines.append(hw["note"])
    return "\n".join(lines)
