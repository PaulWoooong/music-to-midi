"""Choose the NVRTC runtime that can target the installed NVIDIA GPU.

PyTorch compiles a few CUDA kernels at runtime through NVRTC (the so-called
jiterator path).  ``torchaudio``'s magnitude spectrogram, used by Beat This and
other audio front ends, is such a kernel because it takes ``abs`` of a complex
tensor.  The CUDA 12.8 wheel of PyTorch 2.7 ships NVRTC 12.8, which rejects
``sm_121`` (NVIDIA GB10 / DGX Spark):

    nvrtc: error: invalid value for --gpu-architecture (-arch)

CUDA 13 NVRTC understands ``sm_121`` and keeps the NVRTC C ABI that PyTorch
2.7 calls, so portable Linux arm64 bundles use it in place of the wheel copy.
The original ``libnvrtc.so.12`` name is preserved so PyTorch keeps resolving
the library through its usual RPATH lookup.

The override is opt-in: only the Linux arm64 CUDA bundle applies it, because
CUDA 13 dropped pre-Volta GPUs.  x86_64 builds keep the wheel's NVRTC.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
from pathlib import Path

# NVRTC 13 is the first release that accepts the GB10 architecture.
MIN_SUPPORTED_MAJOR = 13


def _candidate_cuda_roots(cuda_home: str | os.PathLike[str] | None = None) -> list[Path]:
    roots: list[Path] = []
    for value in (cuda_home, os.environ.get("CUDA_HOME"), os.environ.get("CUDA_PATH")):
        if value:
            roots.append(Path(value))
    roots.extend(
        [
            Path("/usr/local/cuda"),
            *sorted(Path("/usr/local").glob("cuda-%d*" % MIN_SUPPORTED_MAJOR), reverse=True),
        ]
    )
    unique: list[Path] = []
    for root in roots:
        resolved = Path(os.path.abspath(os.path.expanduser(str(root))))
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _find_library(root: Path, pattern: str) -> Path | None:
    lib_dirs = [
        root / "lib64",
        root / "targets" / "sbsa-linux" / "lib",
        root / "targets" / "aarch64-linux" / "lib",
        root / "lib",
    ]
    matches: list[Path] = []
    for directory in lib_dirs:
        if directory.is_dir():
            matches.extend(p for p in directory.glob(pattern) if p.is_file())
    if not matches:
        return None
    # Prefer the fully versioned file over the unversioned development symlink.
    matches.sort(key=lambda p: (len(p.name), p.name), reverse=True)
    return matches[0]


def find_cuda13_nvrtc(
    cuda_home: str | os.PathLike[str] | None = None,
) -> tuple[Path, Path] | None:
    """Return ``(libnvrtc, libnvrtc-builtins)`` from a CUDA 13+ toolkit."""

    for root in _candidate_cuda_roots(cuda_home):
        nvrtc = _find_library(root, "libnvrtc.so.%d*" % MIN_SUPPORTED_MAJOR)
        builtins = _find_library(root, "libnvrtc-builtins.so.%d*" % MIN_SUPPORTED_MAJOR)
        if nvrtc and builtins:
            return nvrtc, builtins
    return None


def _torch_lib_dir(bundle_dir: Path) -> Path:
    candidates = [
        bundle_dir / "_internal" / "torch" / "lib",
        bundle_dir / "torch" / "lib",
        *sorted(bundle_dir.glob("lib/python*/site-packages/torch/lib")),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"No torch/lib directory found in bundle or virtualenv: {bundle_dir}"
    )


def _points_at_cuda13(path: Path) -> bool:
    if not path.exists():
        return False
    target = os.readlink(path) if path.is_symlink() else path.name
    return ".so.%d" % MIN_SUPPORTED_MAJOR in target


def apply_override(
    bundle_dir: str | os.PathLike[str],
    *,
    cuda_home: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Install the CUDA 13 NVRTC into an onedir bundle.

    Returns the library that now serves ``libnvrtc.so.12``, or ``None`` when
    no CUDA 13 toolkit is available.  Calling it twice is a no-op.
    """

    bundle = Path(bundle_dir)
    torch_lib = _torch_lib_dir(bundle)
    link = torch_lib / "libnvrtc.so.12"
    if _points_at_cuda13(link):
        return link.resolve()

    found = find_cuda13_nvrtc(cuda_home)
    if found is None:
        return None
    nvrtc, builtins = found

    for source in (nvrtc, builtins):
        destination = torch_lib / source.name
        if not destination.exists() or destination.stat().st_size != source.stat().st_size:
            shutil.copy2(source, destination)

    builtins_link = torch_lib / ("libnvrtc-builtins.so.%d.0" % MIN_SUPPORTED_MAJOR)
    if not builtins_link.is_symlink() or os.readlink(builtins_link) != builtins.name:
        builtins_link.unlink(missing_ok=True)
        builtins_link.symlink_to(builtins.name)

    # PyTorch opens exactly "libnvrtc.so.12"; keep that ABI name but point it
    # at the newer compiler.  A relative symlink survives moving the bundle.
    link.unlink(missing_ok=True)
    link.symlink_to(nvrtc.name)
    return link.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="onedir bundle, e.g. dist/MusicToMidi")
    parser.add_argument("--cuda-home", type=Path, default=None, help="CUDA 13 toolkit root")
    args = parser.parse_args(argv)

    if platform.machine().strip().lower() not in {"aarch64", "arm64"}:
        print("Skipping NVRTC override: bundle is not Linux arm64.", file=sys.stderr)
        return 0

    applied = apply_override(args.bundle, cuda_home=args.cuda_home)
    if applied is None:
        print(
            "No CUDA 13 NVRTC found; the bundle keeps its PyTorch NVRTC. "
            "sm_121 devices will fail on runtime-compiled kernels.",
            file=sys.stderr,
        )
        return 1
    print(f"NVRTC override active: {applied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
