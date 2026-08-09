"""Install PyTorch wheels for this OS/arch (multi-platform).

Usage:
  python -m diary_app.install_torch
  python -m diary_app.install_torch --flavor cpu
  python -m diary_app.install_torch --flavor cuda --cuda-channel cu128
  python -m diary_app.install_torch --dry-run

Env:
  OMNIFLOW_TORCH=auto|cpu|cuda|default
  OMNIFLOW_CUDA_CHANNEL=cu128|cu126|cu124|...
  TORCH_CUDA_INDEX=https://download.pytorch.org/whl/cu128
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def _torch_matches_profile(profile) -> bool:
    """True if installed torch already matches the desired CUDA/CPU/default flavor."""
    try:
        import torch
    except ImportError:
        return False
    cuda_built = bool(getattr(torch.version, "cuda", None))
    if profile.torch_flavor == "cuda":
        return cuda_built and torch.cuda.is_available()
    if profile.torch_flavor == "cpu":
        # CPU index wheels: no CUDA in build string (or cuda unavailable is OK)
        return not cuda_built or not torch.cuda.is_available()
    # default (Mac / aarch64 PyPI): any importable torch is fine
    return True


def main(argv: list[str] | None = None) -> int:
    from diary_app.core.platform_info import (
        detect_platform,
        format_platform_report,
        recommend_torch_pip_args,
        cuda_channel,
    )

    parser = argparse.ArgumentParser(description="Install arch-correct PyTorch wheels")
    parser.add_argument(
        "--flavor",
        choices=["auto", "cpu", "cuda", "default"],
        default=None,
        help="Override OMNIFLOW_TORCH / auto detection",
    )
    parser.add_argument(
        "--cuda-channel",
        default=None,
        help="e.g. cu128, cu126 (sets OMNIFLOW_CUDA_CHANNEL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print platform + pip command without installing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall torch even if the current build looks correct",
    )
    parser.add_argument(
        "--pip",
        default=None,
        help="pip executable (default: python -m pip)",
    )
    args = parser.parse_args(argv)

    if args.cuda_channel:
        import os

        os.environ["OMNIFLOW_CUDA_CHANNEL"] = args.cuda_channel

    profile = detect_platform(force_flavor=args.flavor)
    print(format_platform_report(profile))
    print()

    if not profile.supported and profile.support_level == "unsupported":
        print("ERROR: platform marked unsupported. Install torch manually.", file=sys.stderr)
        return 2

    pip_args = recommend_torch_pip_args(profile)
    if args.pip:
        cmd = [args.pip, "install", *pip_args]
    else:
        cmd = [sys.executable, "-m", "pip", "install", *pip_args]

    print("Command:", " ".join(cmd))
    if args.dry_run:
        return 0

    # Skip reinstall when already correct (unless --force)
    if not getattr(args, "force", False) and _torch_matches_profile(profile):
        print(
            f"\nExisting torch already matches flavor={profile.torch_flavor}; "
            "skipping install (pass --force to reinstall)."
        )
        return 0

    print(f"\nInstalling torch ({profile.torch_flavor}, arch={profile.arch})…")
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        print("pip failed.", file=sys.stderr)
        return proc.returncode

    # Verify import + arch sanity
    verify = f"""
import platform, torch
print("torch", torch.__version__)
print("cuda", getattr(torch.version, "cuda", None))
print("cuda_available", torch.cuda.is_available())
print("machine", platform.machine())
try:
    import torchaudio
    print("torchaudio", torchaudio.__version__)
except Exception as e:
    print("torchaudio error", e)
"""
    subprocess.run([sys.executable, "-c", verify], check=False)
    print("\nDone. Next: pip install -r diary_app/requirements-core.txt")
    print("       or:  pip install -e '.[dev]'")
    print(f"(CUDA channel default was {cuda_channel()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
