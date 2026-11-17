# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the portable P40 (sm_61) piano transcription CLI.

Build inputs (environment variables):
  P40_MODEL_SOURCE  Directory containing the prepared model folders:
                      aria_amt/, bytedance_piano/, transkun_v2_aug/,
                      beat_this/final0.ckpt
  P40_FFMPEG_DIR    Directory containing static Linux ffmpeg and ffprobe.

The resulting onedir bundle is self-contained: Python, PyTorch (CUDA 12.6,
sm_60/sm_61-compatible kernels), all piano engines and model weights.
"""

import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

SPEC_DIR = Path(SPECPATH).resolve()
ROOT_DIR = SPEC_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

APP_NAME = "MusicToMidiPianoP40"


def _require_dir(env_name: str) -> Path:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        raise SystemExit(f"{env_name} is not set. Point it at the prepared assets.")
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"{env_name} does not exist or is not a directory: {path}")
    return path


def collect_tree(source: Path, destination: str) -> list[tuple[str, str]]:
    source = Path(source)
    if not source.is_dir():
        raise SystemExit(f"Required bundle directory is missing: {source}")
    items: list[tuple[str, str]] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name in {".DS_Store", "Thumbs.db"}:
            continue
        relative_parent = path.relative_to(source).parent
        target = Path(destination) / relative_parent
        items.append((str(path), str(target)))
    if not items:
        raise SystemExit(f"Required bundle directory is empty: {source}")
    return items


MODEL_SOURCE = _require_dir("P40_MODEL_SOURCE")
FFMPEG_DIR = _require_dir("P40_FFMPEG_DIR")

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = []

# ---------------------------------------------------------------- model assets
datas += collect_tree(MODEL_SOURCE / "aria_amt", "models/aria_amt")
datas += collect_tree(MODEL_SOURCE / "bytedance_piano", "models/bytedance_piano")
datas += collect_tree(
    MODEL_SOURCE / "transkun_v2_aug" / "checkpointMSimplerAug",
    "models/transkun_v2_aug/checkpointMSimplerAug",
)
beat_this_checkpoint = MODEL_SOURCE / "beat_this" / "final0.ckpt"
if not beat_this_checkpoint.is_file():
    raise SystemExit(f"Beat This checkpoint is missing: {beat_this_checkpoint}")
datas.append((str(beat_this_checkpoint), "models/beat_this"))

# ------------------------------------------------------- application resources
for relative in ("src/i18n/zh_CN.json", "src/i18n/en_US.json"):
    datas.append((str(ROOT_DIR / relative), str(Path(relative).parent)))
for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    candidate = ROOT_DIR / name
    if candidate.is_file():
        datas.append((str(candidate), "."))

aria_readme = ROOT_DIR / "resources" / "aria_amt" / "README.txt"
if aria_readme.is_file():
    # Preserve upstream's required empty asset directories.
    for name in ("impulse", "noise", "applause"):
        datas.append((str(aria_readme), f"amt/assets/{name}/.inference-runtime"))

# Static Linux ffmpeg (no dependency on the target's multimedia stack).
# ffprobe is optional: the P40 CLI never invokes it, but include it when the
# asset directory provides one.
ffmpeg_executable = FFMPEG_DIR / "ffmpeg"
if not ffmpeg_executable.is_file():
    raise SystemExit(f"Required static FFmpeg executable is missing: {ffmpeg_executable}")
datas.append((str(ffmpeg_executable), "tools/ffmpeg/bin"))
ffprobe_executable = FFMPEG_DIR / "ffprobe"
if ffprobe_executable.is_file():
    datas.append((str(ffprobe_executable), "tools/ffmpeg/bin"))

# ------------------------------------------------------------- package metadata
for distribution in (
    "aria-amt",
    "ariautils",
    "beat-this",
    "moduleconf",
    "ncls",
    "piano-transcription-inference",
    "PyQt6",
    "torch",
    "torchaudio",
    "torchvision",
    "torchlibrosa",
    "transkun",
):
    try:
        datas += copy_metadata(distribution)
    except Exception as exc:  # pragma: no cover - build-time diagnostics
        print(f"[P40 spec] metadata unavailable for {distribution}: {exc}")

# Aria-AMT reads its pinned config from <site-packages>/config/config.json.
amt_spec = importlib.util.find_spec("amt")
if not amt_spec or not amt_spec.origin:
    raise SystemExit("The pinned aria-amt package is not installed in this build venv.")
amt_config_dir = Path(amt_spec.origin).resolve().parent.parent / "config"
datas += collect_tree(amt_config_dir, "config")


def _exclude_submodule_prefixes(*prefixes):
    normalized = tuple(prefix.rstrip(".") for prefix in prefixes)

    def include(name):
        return not any(
            name == prefix or name.startswith(prefix + ".") for prefix in normalized
        )

    return include


# ------------------------------------------------------------- python packages
package_specs = {
    "torch": {"filter_submodules": _exclude_submodule_prefixes("torch.testing")},
    "torchaudio": {},
    "torchvision": {},
    "transkun": {},
    "amt": {},
    "ariautils": {},
    "piano_transcription_inference": {},
    "torchlibrosa": {},
    "beat_this": {},
    "librosa": {},
    "soundfile": {},
    "pretty_midi": {},
    "mido": {},
    "soxr": {},
    "seaborn": {},
    "mir_eval": {},
    "pydub": {},
    "moduleconf": {},
    "ncls": {},
    "rotary_embedding_torch": {},
    "matplotlib": {"filter_submodules": _exclude_submodule_prefixes("matplotlib.tests")},
}
for package, kwargs in package_specs.items():
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package, **kwargs)
    except Exception as exc:  # pragma: no cover - build-time diagnostics
        print(f"[P40 spec] collect_all failed for {package}: {exc}")
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

# ---------------------------------------------------------- NVIDIA native libs
# torch/lib/libtorch_cuda.so uses RPATH entries such as
#   $ORIGIN/../../nvidia/cublas/lib
# so native CUDA/cuDNN libraries must be placed at the same relative layout
# inside the frozen bundle.
site_packages = (
    Path(sys.prefix)
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
native_binaries: list[tuple[str, str]] = []
nvidia_root = site_packages / "nvidia"
if nvidia_root.is_dir():
    for library in sorted(nvidia_root.rglob("*.so*")):
        if library.exists() and library.is_file():
            destination = library.relative_to(site_packages).parent
            native_binaries.append((str(library), str(destination)))
cusparselt_root = site_packages / "cusparselt"
if cusparselt_root.is_dir():
    for library in sorted(cusparselt_root.rglob("*.so*")):
        if library.exists() and library.is_file():
            destination = library.relative_to(site_packages).parent
            native_binaries.append((str(library), str(destination)))
binaries += native_binaries

# ------------------------------------------------------------------ entrypoints
hiddenimports += [
    "piano_transcribe_p40.transcribe",
    "piano_transcribe_p40.p40_check",
    "piano_transcribe_p40.gui",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.sip",
    "src.core.transkun_transcriber",
    "src.core.transkun_v2_aug_transcriber",
    "src.core.aria_amt_transcriber",
    "src.core.aria_amt_worker",
    "src.core.aria_amt_sequence",
    "src.core.bytedance_piano_transcriber",
    "src.core.beat_detector",
    "src.core.beat_this_tracker",
    "src.core.telknet_beat_grid_v12",
    "src.core.telknet_tempo_map",
    "src.core.midi_tempo",
    "src.core.transcription_stream",
    "src.i18n.translator",
    "src.models.data_models",
    "src.utils.aria_amt_runtime",
    "src.utils.artifact_identity",
    "src.utils.audio_utils",
    "src.utils.gpu_utils",
    "src.utils.midi_output",
    "src.utils.runtime_paths",
    "src.utils.subprocess_utils",
    "multiprocessing",
    "multiprocessing.spawn",
    "multiprocessing.resource_tracker",
]

a = Analysis(
    [str(SPEC_DIR / "portable_entry.py")],
    pathex=[str(ROOT_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtQml",
        "PyQt6.QtQuick",
        "onnxruntime",
        "tensorflow",
        "torch.testing",
        "matplotlib.tests",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
