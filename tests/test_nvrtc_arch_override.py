"""Tests for the arm64 NVRTC override applied after PyInstaller collection."""

from __future__ import annotations

import os
from pathlib import Path

from tools import nvrtc_arch_override as override


def _write_lib(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _fake_cuda(tmp_path: Path) -> tuple[Path, Path]:
    lib_dir = tmp_path / "cuda-13.0" / "targets" / "sbsa-linux" / "lib"
    nvrtc = _write_lib(lib_dir / "libnvrtc.so.13.0.88", b"nvrtc13")
    builtins = _write_lib(lib_dir / "libnvrtc-builtins.so.13.0.88", b"builtins13")
    (lib_dir / "libnvrtc.so.13").symlink_to(nvrtc.name)
    return nvrtc, builtins


def _fake_bundle(tmp_path: Path) -> Path:
    torch_lib = tmp_path / "MusicToMidi" / "_internal" / "torch" / "lib"
    torch_lib.mkdir(parents=True)
    (torch_lib / "libnvrtc.so.12").write_bytes(b"wheel-12.8")
    (torch_lib / "libnvrtc-builtins.so.12.8").write_bytes(b"builtins12.8")
    return torch_lib.parents[2]


def test_find_cuda13_nvrtc_prefers_the_versioned_library(tmp_path):
    nvrtc, builtins = _fake_cuda(tmp_path)

    found = override.find_cuda13_nvrtc(tmp_path / "cuda-13.0")

    assert found == (nvrtc, builtins)


def test_apply_override_replaces_the_abi_link_and_is_idempotent(tmp_path):
    nvrtc, builtins = _fake_cuda(tmp_path)
    bundle = _fake_bundle(tmp_path)
    torch_lib = bundle / "_internal" / "torch" / "lib"

    applied = override.apply_override(bundle, cuda_home=tmp_path / "cuda-13.0")

    link = torch_lib / "libnvrtc.so.12"
    assert applied == link.resolve()
    assert os.readlink(link) == nvrtc.name
    assert (torch_lib / nvrtc.name).read_bytes() == b"nvrtc13"
    assert (torch_lib / builtins.name).read_bytes() == b"builtins13"
    assert os.readlink(torch_lib / "libnvrtc-builtins.so.13.0") == builtins.name

    again = override.apply_override(bundle, cuda_home=tmp_path / "cuda-13.0")

    assert again == applied
    assert os.readlink(link) == nvrtc.name
    assert (torch_lib / "libnvrtc-builtins.so.12.8").exists()


def test_torch_lib_dir_finds_a_source_virtualenv(tmp_path):
    torch_lib = (
        tmp_path
        / "venv"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "torch"
        / "lib"
    )
    torch_lib.mkdir(parents=True)

    assert override._torch_lib_dir(tmp_path / "venv") == torch_lib


def test_apply_override_keeps_the_wheel_nvrtc_without_cuda13(tmp_path, monkeypatch):
    bundle = _fake_bundle(tmp_path)
    torch_lib = bundle / "_internal" / "torch" / "lib"
    monkeypatch.setattr(override, "_candidate_cuda_roots", lambda _home=None: [])

    applied = override.apply_override(bundle, cuda_home=tmp_path / "missing")

    assert applied is None
    assert not (torch_lib / "libnvrtc.so.12").is_symlink()
    assert (torch_lib / "libnvrtc.so.12").read_bytes() == b"wheel-12.8"


def test_apply_override_reports_a_bundle_without_torch(tmp_path):
    (tmp_path / "MusicToMidi" / "_internal").mkdir(parents=True)

    try:
        override.apply_override(tmp_path / "MusicToMidi")
    except FileNotFoundError as exc:
        assert "torch/lib" in str(exc)
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("expected a missing torch/lib error")
