#!/usr/bin/env bash
# Runs inside the build container started by build_linux_portable.sh.
set -euo pipefail

: "${P40_MODEL_SOURCE:?P40_MODEL_SOURCE must point at the bundled model directory}"

VENV=/tmp/p40-venv
FFMPEG_DIR=/tmp/p40-ffmpeg/bin
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
DIST_DIR="${P40_DIST_DIR:-/work/dist-p40}"
WORK_DIR="${P40_WORK_DIR:-/tmp/p40-pyinstaller}"

echo "==> Python: $(python3 --version)"
python3 - <<'PY'
import platform
print("==> glibc:", platform.libc_ver())
PY

echo "==> Creating build venv"
python3 -m venv "${VENV}"
"${VENV}/bin/python" -m pip install --upgrade pip setuptools wheel -i "${PIP_INDEX_URL}"

# CUDA 12.6 keeps Pascal SASS (sm_60), which is binary-compatible with the
# Tesla P40's sm_61. Newer CUDA lines (12.8+) dropped Pascal.
echo "==> Installing PyTorch 2.7.0 + CUDA 12.6"
"${VENV}/bin/python" -m pip install \
    "torch==2.7.0" "torchaudio==2.7.0" "torchvision==0.22.0" \
    --index-url https://download.pytorch.org/whl/cu126

echo "==> Installing piano transcription dependencies"
"${VENV}/bin/python" -m pip install -i "${PIP_INDEX_URL}" \
    "numpy==1.26.4" \
    "scipy>=1.10,<2" \
    "librosa>=0.10,<1" \
    "soundfile>=0.14,<1" \
    "mido>=1.3,<2" \
    "pretty-midi>=0.2.10,<1" \
    "tqdm>=4.66,<5" \
    "pyyaml>=6,<7" \
    "requests>=2.32.5,<3" \
    "safetensors>=0.4,<1" \
    "huggingface_hub>=0.20,<2" \
    "soxr>=0.3.7,<1" \
    "einops>=0.7,<1" \
    "orjson>=3.9,<4" \
    "matplotlib>=3.7,<4" \
    "psutil>=5.9,<8" \
    "chardet>=5,<6" \
    "numba>=0.60,<1" \
    "transkun==2.0.1" \
    "ncls==0.0.68" \
    "setuptools==80.10.2" \
    "piano-transcription-inference==0.0.6" \
    "torchlibrosa>=0.1,<0.2" \
    "beat-this==1.1.0" \
    "pyinstaller>=6.10,<7" \
    "imageio-ffmpeg>=0.6,<1" \
    "PyQt6==6.7.1"

# Upstream pins torchaudio<=2.5; install the pinned sources without letting
# their metadata rewrite the fixed CUDA 12.6 runtime.
echo "==> Installing pinned Aria-AMT sources"
"${VENV}/bin/python" -m pip install --no-deps \
    "ariautils @ https://github.com/EleutherAI/aria-utils/archive/7c815755c6889a784b6a1b3343e9e8daa3e7d128.zip" \
    "aria-amt @ https://github.com/EleutherAI/aria-amt/archive/a1ab73fc901d1759ec3bc173c146b3c6a3040261.zip"

echo "==> Preparing static ffmpeg"
mkdir -p "${FFMPEG_DIR}"
cp "$("${VENV}/bin/python" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" "${FFMPEG_DIR}/ffmpeg"
chmod +x "${FFMPEG_DIR}/ffmpeg"
"${FFMPEG_DIR}/ffmpeg" -version | head -1

echo "==> Verifying engine runtimes"
"${VENV}/bin/python" - <<'PY'
from src.core.transkun_transcriber import TranskunTranscriber
from src.core.transkun_v2_aug_transcriber import TranskunV2AugTranscriber
from src.core.aria_amt_transcriber import AriaAmtTranscriber
from src.core.bytedance_piano_transcriber import ByteDancePianoTranscriber

for name, cls in (
    ("transkun", TranskunTranscriber),
    ("transkun_v2_aug", TranskunV2AugTranscriber),
    ("aria_amt", AriaAmtTranscriber),
    ("bytedance_pedal", ByteDancePianoTranscriber),
):
    print(f"{name}: available={cls.is_available()}")
PY

echo "==> Running PyInstaller"
cd /work
P40_MODEL_SOURCE="${P40_MODEL_SOURCE}" \
P40_FFMPEG_DIR="${FFMPEG_DIR}" \
    "${VENV}/bin/pyinstaller" \
        --noconfirm \
        --clean \
        --distpath "${DIST_DIR}" \
        --workpath "${WORK_DIR}" \
        piano_transcribe_p40/PianoP40.spec

echo "==> Build complete"
