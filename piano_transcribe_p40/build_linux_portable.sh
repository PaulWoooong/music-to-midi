#!/usr/bin/env bash
# Build the self-contained Linux P40 piano transcription bundle.
#
# Two build modes:
#   native (default)  Use the existing .venv-p40 on this machine (no Docker).
#                     Requires glibc matching the build host; fine for local use.
#   docker            Build inside python:3.10-slim-bullseye (glibc 2.31) so the
#                     bundle also runs on Ubuntu 20.04/22.04 / Debian 11+.
#
# Usage:
#   ./piano_transcribe_p40/build_linux_portable.sh
#   P40_BUILD_MODE=docker ./piano_transcribe_p40/build_linux_portable.sh
#
# Environment:
#   P40_BUILD_MODE     native (default) or docker
#   P40_MODEL_SOURCE   Model directory containing aria_amt/, bytedance_piano/,
#                      transkun_v2_aug/ and beat_this/final0.ckpt
#   P40_VENV           Build venv for native mode (default: <repo>/.venv-p40)
#   P40_DIST_DIR       Output directory (default: <repo>/dist-p40)
#   PYTHON_IMAGE       Container image for docker mode
#   PIP_INDEX_URL      PyPI mirror used inside the container
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEFAULT_MODEL_SOURCE="/media/paul/02D010A3D0109F4B/MusicToMidi-Linux-GPU-Portable/MusicToMidi-Windows-GPU-App/_internal/models"
MODEL_SOURCE="${P40_MODEL_SOURCE:-${DEFAULT_MODEL_SOURCE}}"
DIST_DIR="${P40_DIST_DIR:-${ROOT_DIR}/dist-p40}"
BUILD_MODE="${P40_BUILD_MODE:-native}"
PYTHON_IMAGE="${PYTHON_IMAGE:-python:3.10-slim-bullseye}"
VENV="${P40_VENV:-${ROOT_DIR}/.venv-p40}"

if [[ ! -d "${MODEL_SOURCE}" ]]; then
    echo "error: model source directory not found: ${MODEL_SOURCE}" >&2
    echo "       set P40_MODEL_SOURCE to the directory that contains aria_amt/ and friends." >&2
    exit 1
fi

for required in aria_amt bytedance_piano transkun_v2_aug beat_this; do
    if [[ ! -d "${MODEL_SOURCE}/${required}" ]]; then
        echo "error: ${MODEL_SOURCE}/${required} is missing" >&2
        exit 1
    fi
done

mkdir -p "${DIST_DIR}"

case "${BUILD_MODE}" in
native)
    if [[ ! -x "${VENV}/bin/pyinstaller" ]]; then
        cat >&2 <<EOF
error: ${VENV}/bin/pyinstaller not found.

Create the build environment once:
  python3 -m venv .venv-p40
  .venv-p40/bin/pip install torch==2.7.0 torchaudio==2.7.0 torchvision==0.22.0 \\
      --index-url https://download.pytorch.org/whl/cu126
  .venv-p40/bin/pip install -r piano_transcribe_p40/requirements-p40.txt \\
      pyinstaller "imageio-ffmpeg>=0.6,<1" "PyQt6==6.7.1"
  .venv-p40/bin/pip install --no-deps \\
      "aria-amt @ https://github.com/EleutherAI/aria-amt/archive/a1ab73fc901d1759ec3bc173c146b3c6a3040261.zip"
EOF
        exit 1
    fi

    echo "==> Building MusicToMidiPianoP40 (native)"
    echo "    venv:   ${VENV}"
    echo "    models: ${MODEL_SOURCE}"
    echo "    output: ${DIST_DIR}"

    FFMPEG_DIR="${P40_FFMPEG_DIR:-${ROOT_DIR}/build/p40_ffmpeg/bin}"
    if [[ ! -x "${FFMPEG_DIR}/ffmpeg" ]]; then
        mkdir -p "${FFMPEG_DIR}"
        cp "$("${VENV}/bin/python" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" \
            "${FFMPEG_DIR}/ffmpeg"
        chmod +x "${FFMPEG_DIR}/ffmpeg"
    fi

    P40_MODEL_SOURCE="${MODEL_SOURCE}" \
    P40_FFMPEG_DIR="${FFMPEG_DIR}" \
        "${VENV}/bin/pyinstaller" \
            --noconfirm --clean \
            --distpath "${DIST_DIR}" \
            --workpath "${ROOT_DIR}/build/p40-pyinstaller" \
            "${SCRIPT_DIR}/PianoP40.spec"
    ;;
docker)
    docker run --rm \
        --user "$(id -u):$(id -g)" \
        -e HOME=/tmp/p40-home \
        -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
        -e PIP_NO_INPUT=1 \
        -e PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}" \
        -e P40_MODEL_SOURCE=/models \
        -e P40_DIST_DIR=/dist \
        -e P40_WORK_DIR=/tmp/p40-pyinstaller \
        -v "${ROOT_DIR}":/work \
        -v "${MODEL_SOURCE}":/models:ro \
        -v "${DIST_DIR}":/dist \
        -w /work \
        "${PYTHON_IMAGE}" \
        bash /work/piano_transcribe_p40/_build_in_container.sh
    ;;
*)
    echo "error: P40_BUILD_MODE must be 'native' or 'docker' (got: ${BUILD_MODE})" >&2
    exit 1
    ;;
esac

echo "==> Done: ${DIST_DIR}/MusicToMidiPianoP40"
echo "    Run: ${DIST_DIR}/MusicToMidiPianoP40/p40-check.sh (after packaging)"
