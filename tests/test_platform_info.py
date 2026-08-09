"""Multi-arch platform detection (no network)."""
import sys

from diary_app.core.platform_info import (
    detect_platform,
    recommend_torch_pip_args,
    recommend_torch_command,
    _normalize_arch,
    _normalize_os,
)


def test_normalize_arch():
    assert _normalize_arch("x86_64") == "x86_64"
    assert _normalize_arch("AMD64") == "x86_64"
    assert _normalize_arch("aarch64") in ("aarch64", "arm64")


def test_normalize_os():
    assert _normalize_os("Darwin") == "darwin"
    assert _normalize_os("Linux") == "linux"
    assert _normalize_os("Windows") == "windows"


def test_detect_current_platform():
    p = detect_platform()
    assert p.os_name in ("darwin", "linux", "windows", "other")
    assert p.arch
    assert p.python
    assert p.torch_flavor in ("cpu", "cuda", "default")
    cmd = recommend_torch_command(p)
    assert "pip install" in cmd
    assert "torch" in cmd


def test_force_cpu_linux_style(monkeypatch):
    p = detect_platform(force_flavor="cpu")
    args = recommend_torch_pip_args(p)
    assert "torch" in args
    # On linux x86_64 CPU should use cpu index; on mac default index
    if p.os_name == "linux" and p.arch == "x86_64":
        assert "--index-url" in args
        assert any("cpu" in a for a in args)
    if p.os_name == "darwin":
        assert "--index-url" not in args


def test_force_cuda_sets_index_on_x86_linux(monkeypatch):
    monkeypatch.setenv("OMNIFLOW_CUDA_CHANNEL", "cu128")
    p = detect_platform(force_flavor="cuda")
    args = recommend_torch_pip_args(p)
    if p.os_name == "linux" and p.arch == "x86_64":
        assert any("cu128" in a for a in args)
    if p.os_name == "darwin":
        # CUDA not used on Mac
        assert p.torch_flavor == "default" or "--index-url" not in args


def test_doctor_runs():
    from diary_app.core.platform_info import doctor_checks, format_doctor_report

    data = doctor_checks()
    assert "checks" in data
    assert "platform" in data
    text = format_doctor_report()
    assert "Doctor checks" in text
    assert sys.version_info >= (3, 11)
