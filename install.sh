#!/usr/bin/env bash
# Music to MIDI - Linux/WSL 自动安装脚本
# 支持提供 64 位 Python 3.11/3.12 的 Debian/Ubuntu/WSL2 (WSLg)
# 用法: bash install.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${REPO_DIR}/venv"

# ───────────────────────── 颜色输出 ─────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ───────────────────────── 横幅 ─────────────────────────
echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════╗"
echo "║        Music to MIDI - 安装脚本              ║"
echo "║        支持 Linux / WSL2                     ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

# ───────────────────────── 检测 CPU 架构 ─────────────────────────
HOST_ARCH="$(uname -m)"
case "$HOST_ARCH" in
    x86_64|amd64)
        HOST_ARCH="x86_64"
        ;;
    aarch64|arm64)
        HOST_ARCH="aarch64"
        ;;
    *)
        error "不支持的 CPU 架构: $HOST_ARCH；当前安装器支持 x86_64 与 aarch64 (arm64)。"
        ;;
esac
info "CPU 架构: $HOST_ARCH"

# ───────────────────────── 检测环境 ─────────────────────────
IS_WSL=false
if grep -qi microsoft /proc/version 2>/dev/null; then
    IS_WSL=true
    info "检测到 WSL2 环境"
else
    info "检测到原生 Linux 环境"
fi

if ! command -v apt-get &>/dev/null || ! command -v dpkg &>/dev/null; then
    error "当前安装器只支持使用 apt/dpkg 的 Debian、Ubuntu 与 WSL2；检测不到 apt-get 或 dpkg。"
fi

# ───────────────────────── 检查 sudo ─────────────────────────
if ! sudo -n true 2>/dev/null; then
    warn "安装系统依赖需要 sudo 权限，终端会请求密码..."
fi

# ───────────────────────── 检查 Python ─────────────────────────
info "检查 Python 版本..."
PYTHON_BIN=""
for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        IDENTITY=$("$cmd" -c 'import struct, sys; print("{}.{} {}".format(sys.version_info.major, sys.version_info.minor, struct.calcsize("P") * 8))' 2>/dev/null || echo "0.0 0")
        read -r VER BITS <<< "$IDENTITY"
        MAJOR="${VER%%.*}"; MINOR="${VER##*.}"
        if [[ "$MAJOR" =~ ^[0-9]+$ && "$MINOR" =~ ^[0-9]+$ ]] && \
           [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 11 ] && [ "$MINOR" -le 12 ] && \
           [ "$BITS" -eq 64 ]; then
            PYTHON_BIN="$cmd"
            success "找到 64 位 Python $VER ($cmd)"
            break
        elif [[ "$BITS" == "32" ]]; then
            warn "忽略 32 位 Python $VER ($cmd)；完整 CUDA 运行时只支持 64 位 Python。"
        elif [[ "$MAJOR" =~ ^[0-9]+$ && "$MINOR" =~ ^[0-9]+$ ]]; then
            warn "忽略不兼容的 Python $VER ($cmd)；项目仅支持 Python 3.11-3.12。"
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    warn "未找到 64 位 Python 3.11-3.12，尝试从当前 apt 软件源安装..."
    info "更新包列表..."
    sudo apt-get update
    for candidate in python3.12 python3.11; do
        if apt-cache show "$candidate" >/dev/null 2>&1 && \
           apt-cache show "${candidate}-venv" >/dev/null 2>&1 && \
           apt-cache show "${candidate}-dev" >/dev/null 2>&1; then
            sudo apt-get install -y "$candidate" "${candidate}-venv" "${candidate}-dev" python3-pip
            PYTHON_BIN="$candidate"
            break
        fi
    done
    if [ -z "$PYTHON_BIN" ]; then
        error "当前 apt 软件源不提供 64 位 Python 3.11/3.12 及其 venv/dev 包。兼容环境需要发行版官方软件源中的 Python 3.11/3.12；3.10 和 3.13+ 不受支持。"
    fi
fi

if ! "$PYTHON_BIN" -c '
import struct, sys
version = sys.version_info[:2]
if not ((3, 11) <= version <= (3, 12)):
    raise RuntimeError(f"unsupported Python: {version[0]}.{version[1]}")
if struct.calcsize("P") * 8 != 64:
    raise RuntimeError("the installer requires 64-bit Python")
'; then
    error "选中的解释器未通过 Python 3.11-3.12 64 位实测: $PYTHON_BIN"
fi

if [[ "$PYTHON_BIN" =~ ^python3\.(11|12)$ ]]; then
    PYTHON_VENV_PACKAGE="${PYTHON_BIN}-venv"
    PYTHON_DEV_PACKAGE="${PYTHON_BIN}-dev"
else
    PYTHON_VENV_PACKAGE="python3-venv"
    PYTHON_DEV_PACKAGE="python3-dev"
fi

# ───────────────────────── 预检本地模型目录 ─────────────────────────
MODELS_SOURCE="${MUSIC_TO_MIDI_MODELS_SOURCE:-${HOME}/models}"
info "预检本地模型目录：${MODELS_SOURCE}"
if [ ! -d "$MODELS_SOURCE" ]; then
    error "本地模型目录不存在：${MODELS_SOURCE}。请按缓存镜像结构准备模型，或设置 MUSIC_TO_MIDI_MODELS_SOURCE 指向正确目录。"
fi
if ! "$PYTHON_BIN" "${REPO_DIR}/prepare_local_models.py" --check-only --source "$MODELS_SOURCE"; then
    error "本地模型目录结构预检失败；安装器不会联网下载模型。"
fi
success "本地模型目录结构预检通过"

# ───────────────────────── 安装系统依赖 ─────────────────────────
info "安装系统依赖..."
info "更新包列表..."
sudo apt-get update

SYSTEM_PKGS=(
    # 版本控制
    git
    curl
    # aarch64 上 ncls/diffq 需要从源码构建
    build-essential
    # 音频处理
    ffmpeg
    fluidsynth
    libsamplerate0
    libsndfile1
    libportaudio2
    portaudio19-dev
    # Python 开发（必须与选中的解释器一致）
    "$PYTHON_DEV_PACKAGE"
    "$PYTHON_VENV_PACKAGE"
    # PyQt6 / X11 运行时库
    libxcb-xinerama0
    libxcb-cursor0
    libxkbcommon-x11-0
    libxcb-icccm4
    libxcb-image0
    libxcb-keysyms1
    libxcb-randr0
    libxcb-render-util0
    libxcb-shape0
    libxcb-util1
    libxrender1
    libgl1
    libglib2.0-0
    # UI 字体（英文）
    fonts-ubuntu
    fonts-dejavu-core
    # 中文字体（修复中文显示为方块的问题）
    fonts-noto-cjk
    fonts-wqy-zenhei
    fonts-wqy-microhei
    # Emoji/图标字体（修复图标显示为方块的问题）
    fonts-noto-color-emoji
    fonts-symbola
)

MISSING_PKGS=()
for pkg in "${SYSTEM_PKGS[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null 2>&1; then
        MISSING_PKGS+=("$pkg")
    fi
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    info "安装缺失的系统包 (${#MISSING_PKGS[@]} 个)..."
    sudo apt-get install -y "${MISSING_PKGS[@]}"
    success "系统包安装完成"
else
    success "所有系统依赖已就绪"
fi

# ───────────────────────── 更新字体缓存 ─────────────────────────
info "更新字体缓存..."
fc-cache -f 2>/dev/null || true
success "字体缓存已更新"

# ───────────────────────── 配置 fontconfig（emoji回退）─────────────────────────
info "配置字体回退（Emoji/图标支持）..."
mkdir -p "${HOME}/.config/fontconfig"
FONTCONFIG_FILE="${HOME}/.config/fontconfig/fonts.conf"
if [ -e "$FONTCONFIG_FILE" ] && ! grep -q "Music to MIDI managed font fallback" "$FONTCONFIG_FILE"; then
    warn "检测到用户已有 fontconfig 配置，保留不覆盖: $FONTCONFIG_FILE"
else
cat > "$FONTCONFIG_FILE" << 'FONTCONF_EOF'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <!-- Music to MIDI managed font fallback -->
  <!-- 优先使用 Noto CJK 渲染中文，Noto Color Emoji 渲染图标 -->
  <alias>
    <family>sans-serif</family>
    <prefer>
      <family>Noto Sans CJK SC</family>
      <family>WenQuanYi Micro Hei</family>
      <family>Noto Color Emoji</family>
      <family>Symbola</family>
    </prefer>
  </alias>
  <alias>
    <family>serif</family>
    <prefer>
      <family>Noto Serif CJK SC</family>
      <family>Noto Color Emoji</family>
      <family>Symbola</family>
    </prefer>
  </alias>
  <alias>
    <family>monospace</family>
    <prefer>
      <family>Noto Sans Mono CJK SC</family>
      <family>Ubuntu Mono</family>
      <family>Noto Color Emoji</family>
      <family>Symbola</family>
    </prefer>
  </alias>
</fontconfig>
FONTCONF_EOF
    success "项目字体回退配置已写入: $FONTCONFIG_FILE"
fi
fc-cache -f 2>/dev/null || true
success "字体缓存刷新完成"

# ───────────────────────── WSL 显示检查 ─────────────────────────
if $IS_WSL; then
    info "检查 WSL 显示环境..."
    if [ -z "${DISPLAY:-}" ]; then
        if [ -d "/mnt/wslg" ]; then
            warn "WSLg 已检测到。所需 shell 设置：export DISPLAY=:0"
        else
            warn "未检测到 WSLg。"
            warn "  - Windows 11: 确保 WSLg 已启用（通常默认开启）"
            warn "  - Windows 10: 需要安装 VcXsrv 并设置 DISPLAY"
        fi
    else
        success "显示环境 DISPLAY=$DISPLAY 已就绪"
    fi
fi

# ───────────────────────── 修复运行时目录权限 ─────────────────────────
if [ -d "/run/user/$(id -u)" ]; then
    chmod 700 "/run/user/$(id -u)" 2>/dev/null || true
fi

# ───────────────────────── 创建虚拟环境 ─────────────────────────
info "创建 Python 虚拟环境..."
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    success "虚拟环境已创建: $VENV_DIR"
else
    VENV_PYTHON="${VENV_DIR}/bin/python"
    if [ ! -x "$VENV_PYTHON" ] || ! "$VENV_PYTHON" -c '
import struct, sys
version = sys.version_info[:2]
if not (version >= (3, 11) and version <= (3, 12)):
    raise RuntimeError(f"unsupported venv Python: {version[0]}.{version[1]}")
if struct.calcsize("P") * 8 != 64:
    raise RuntimeError("the project venv must use 64-bit Python")
'; then
        warn "现有 venv 的解释器损坏或不符合 Python 3.11-3.12 64 位契约，正在使用 $PYTHON_BIN --clear 重建可复现环境..."
        "$PYTHON_BIN" -m venv --clear "$VENV_DIR"
        success "虚拟环境已按固定解释器重建: $VENV_DIR"
    else
        success "虚拟环境已存在且解释器版本/位数正确: $VENV_DIR"
    fi
fi

PIP="${VENV_DIR}/bin/pip"
PYTHON="${VENV_DIR}/bin/python"

# ───────────────────────── 升级 pip ─────────────────────────
info "升级 pip..."
"$PIP" install --upgrade pip setuptools wheel
success "pip 升级完成"

# ───────────────────────── 严格 NVIDIA CUDA / PyTorch 契约 ─────────────────────────
info "验证完整七模式 NVIDIA CUDA 12.8 运行时..."

if ! command -v nvidia-smi &>/dev/null || ! nvidia-smi &>/dev/null 2>&1; then
    if command -v rocm-smi &>/dev/null && rocm-smi &>/dev/null 2>&1; then
        error "检测到 AMD/ROCm，安装已停止；当前 Linux 完整七模式需要 NVIDIA CUDA 12.8 与 ONNX Runtime CUDAExecutionProvider，尚未支持 ROCm。"
    fi
    error "未检测到可用的 NVIDIA 驱动 (nvidia-smi)，安装已停止。请检查 NVIDIA 显卡及驱动。"
fi

CUDA_VER=$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: \([0-9.]*\).*/\1/p' | head -1)
if [ -z "$CUDA_VER" ]; then
    error "nvidia-smi 未报告 CUDA 驱动版本，无法确认 CUDA 12.8 运行时兼容性。"
fi
CUDA_MAJOR="${CUDA_VER%%.*}"
CUDA_MINOR="${CUDA_VER#*.}"
CUDA_MINOR="${CUDA_MINOR%%.*}"
if [ "${CUDA_MAJOR:-0}" -lt 12 ] || { [ "$CUDA_MAJOR" -eq 12 ] && [ "${CUDA_MINOR:-0}" -lt 8 ]; }; then
    error "NVIDIA 驱动仅报告 CUDA $CUDA_VER；完整七模式的固定 PyTorch/ONNX Runtime 组合需要 CUDA 12.8 兼容驱动。"
fi
success "NVIDIA 驱动检查通过（报告 CUDA $CUDA_VER）"

validate_torch_cuda_runtime() {
    "$PYTHON" -c '
import sys
from importlib import metadata
expected = {"torch": "2.7.0", "torchaudio": "2.7.0", "torchvision": "0.22.0"}
try:
    actual = {name: metadata.version(name) for name in expected}
except metadata.PackageNotFoundError as exc:
    print(f"Missing pinned PyTorch runtime package: {exc.name}", file=sys.stderr)
    raise SystemExit(2)
base = {name: version.split("+", 1)[0] for name, version in actual.items()}
if base != expected:
    raise RuntimeError(f"PyTorch trio mismatch: expected={expected}, actual={actual}")
import torch, torchaudio, torchvision
if getattr(torch.version, "hip", None):
    raise RuntimeError(f"ROCm runtime is unsupported for the complete seven-mode stack: HIP={torch.version.hip}")
if torch.version.cuda != "12.8":
    raise RuntimeError(f"Expected PyTorch CUDA 12.8 runtime, got {torch.version.cuda!r}")
if not torch.cuda.is_available():
    raise RuntimeError("torch.cuda.is_available() is False; a working NVIDIA CUDA GPU is required")
probe = torch.ones(1, device="cuda")
probe.add_(1)
torch.cuda.synchronize()
print("PyTorch trio:", actual)
print("PyTorch CUDA runtime:", torch.version.cuda)
print("NVIDIA device:", torch.cuda.get_device_name(0))
'
}

info "检查 PyTorch 2.7.0 / torchaudio 2.7.0 / torchvision 0.22.0 cu128..."
if ! validate_torch_cuda_runtime; then
    info "当前 PyTorch 三件套或 CUDA flavor 不符合固定运行时，正在强制安装 cu128..."
    "$PIP" install torch==2.7.0 torchaudio==2.7.0 torchvision==0.22.0 \
        --index-url "https://download.pytorch.org/whl/cu128" --force-reinstall
    if ! validate_torch_cuda_runtime; then
        error "PyTorch 三件套安装后仍未通过精确版本/CUDA 12.8/GPU 张量验证"
    fi
fi
success "PyTorch 三件套与 NVIDIA CUDA 12.8 实测通过"
info "完整七模式固定使用 NVIDIA CUDA，不安装 IPEX/CPU 降级运行时。"

# ───────────────────────── 安装项目依赖 ─────────────────────────
info "安装项目 Python 依赖..."
cd "$REPO_DIR"

# onnxruntime-gpu 1.23.2 只提供 x86_64 wheel；上游从 1.29 起发布 aarch64
# wheel。diffq-fixed 的 sdist 缺少 bitpack.pyx，arm64 改用上游同版本 diffq
# 源码构建（audio-separator 在非 Windows 平台本来就要求 diffq）。
if [ "$HOST_ARCH" = "aarch64" ]; then
    ORT_GPU_REQUIREMENT="onnxruntime-gpu==1.31.1"
    DIFFQ_REQUIREMENT="diffq==0.2.4"
    info "arm64 适配: onnxruntime-gpu 1.31.1 + 源码构建 diffq 0.2.4"
else
    ORT_GPU_REQUIREMENT="onnxruntime-gpu==1.23.2"
    DIFFQ_REQUIREMENT="diffq-fixed==0.2.4"
fi

if "$PIP" show audio-separator >/dev/null 2>&1; then
    info "检测到旧的 audio-separator，先卸载以避免 NumPy 解析冲突..."
    "$PIP" uninstall audio-separator -y
fi

TMP_REQ=$(mktemp "${TMPDIR:-/tmp}/music-to-midi-requirements-without-aria-amt.XXXXXX")
cleanup_requirements_file() {
    if [ -n "${TMP_REQ:-}" ] && [ -f "$TMP_REQ" ]; then
        rm -f -- "$TMP_REQ"
    fi
}
trap cleanup_requirements_file EXIT
grep -vE '^[[:space:]]*aria-amt[[:space:]]*@' requirements.txt > "$TMP_REQ"
if [ "$HOST_ARCH" = "aarch64" ]; then
    # requirements.txt 固定的是没有 aarch64 wheel 的 x86_64 版本；下面通过
    # ORT_GPU_REQUIREMENT 安装 arm64 可用的 onnxruntime-gpu。
    grep -vE '^[[:space:]]*onnxruntime-gpu([[:space:]=<>!~@;\[]|$)' "$TMP_REQ" > "${TMP_REQ}.arch"
    mv "${TMP_REQ}.arch" "$TMP_REQ"
fi
ORT_PACKAGES_TO_REMOVE=()
for ort_package in onnxruntime onnxruntime-gpu; do
    if "$PIP" show "$ort_package" >/dev/null 2>&1; then
        ORT_PACKAGES_TO_REMOVE+=("$ort_package")
    fi
done
if [ ${#ORT_PACKAGES_TO_REMOVE[@]} -gt 0 ]; then
    "$PIP" uninstall -y "${ORT_PACKAGES_TO_REMOVE[@]}"
fi
"$PIP" install -r "$TMP_REQ"
cleanup_requirements_file
trap - EXIT
if ! validate_torch_cuda_runtime; then
    error "requirements.txt 安装后 PyTorch 三件套版本或 CUDA 12.8 运行时被改变"
fi
success "Python 依赖安装完成"

info "安装 audio-separator 运行依赖（固定兼容 NumPy 1.26）..."
"$PIP" install \
    "numpy==1.26.4" \
    "beartype==0.18.5" \
    "$DIFFQ_REQUIREMENT" \
    "julius==0.2.7" \
    "ml_collections==1.1.0" \
    "onnx-weekly==1.21.0.dev20260223" \
    "onnx2torch-py313==1.6.0" \
    "pydub==0.25.1" \
    "requests>=2.32.5,<3" \
    "chardet>=5,<6" \
    "$ORT_GPU_REQUIREMENT" \
    'onnxruntime==1.23.2; platform_system == "Darwin"' \
    "resampy==0.4.3" \
    "rotary-embedding-torch==0.6.5" \
    "samplerate==0.1.0" \
    "six==1.17.0"
if ! validate_torch_cuda_runtime; then
    error "audio-separator 运行依赖安装后 PyTorch 三件套版本或 CUDA 12.8 运行时被改变"
fi
"$PYTHON" - <<'PY'
import onnxruntime as ort
import torch

providers = ort.get_available_providers()
print("ONNX Runtime providers:", providers)
if getattr(torch.version, "hip", None):
    raise RuntimeError(f"ROCm runtime is unsupported: HIP={torch.version.hip}")
if torch.version.cuda != "12.8" or not torch.cuda.is_available():
    raise RuntimeError(f"Expected working PyTorch CUDA 12.8, got CUDA={torch.version.cuda!r}")
if "CUDAExecutionProvider" not in providers:
    raise RuntimeError("Complete seven-mode runtime requires ONNX Runtime CUDAExecutionProvider")
PY

if [ "$HOST_ARCH" = "aarch64" ]; then
    # PyTorch 2.7 的 cu128 wheel 自带 NVRTC 12.8，无法为 GB10（sm_121）编译
    # jiterator 内核（如 torchaudio 幅度谱的复数 abs）。CUDA 13 NVRTC 兼容
    # PyTorch 调用的 C ABI，因此源码安装时同样替换 venv 中的运行时编译器。
    info "为 aarch64（sm_121 / GB10）配置兼容的 NVRTC 运行时..."
    if ! "$PYTHON" "${REPO_DIR}/tools/nvrtc_arch_override.py" "$VENV_DIR"; then
        warn "未找到 CUDA 13 NVRTC；GB10 上 Beat This 等运行时编译内核可能失败。"
    fi
fi
"$PIP" install "audio-separator==0.44.1" --no-deps
success "audio-separator 安装完成"

info "安装并严格校验官方 MuScriptor（不改写固定 PyTorch 运行时）..."
MUSCRIPTOR_REQUIREMENT="$(cd "$REPO_DIR" && "$PYTHON" -c 'from src.utils.muscriptor_source_identity import MUSCRIPTOR_SOURCE_REQUIREMENT; print(MUSCRIPTOR_SOURCE_REQUIREMENT)')"
if [ -z "$MUSCRIPTOR_REQUIREMENT" ]; then
    error "无法从项目源码读取 MuScriptor 固定安装身份"
fi
"$PIP" install "$MUSCRIPTOR_REQUIREMENT" --no-deps --force-reinstall
(cd "$REPO_DIR" && "$PYTHON" -m src.utils.source_runtime)
(cd "$REPO_DIR" && "$PYTHON" -c 'from src.core.muscriptor_transcriber import MuscriptorTranscriber; reason = MuscriptorTranscriber._runtime_unavailable_reason(); print(reason or "MuScriptor public runtime identity/API verified"); raise SystemExit(0 if reason == "" else 1)')
success "MuScriptor 官方源码与硬乐器约束 API 校验通过"

validate_default_transkun_runtime() {
    "$PYTHON" - <<'PY'
from download_sota_models import validate_default_transkun_runtime

identity = validate_default_transkun_runtime()
print("TransKun default runtime:", identity)
PY
}

info "验证 TransKun 2.0.1 默认 V2 包与随包资源身份..."
if ! validate_default_transkun_runtime; then
    info "TransKun 默认 V2 身份不完整，正在强制重装 transkun==2.0.1..."
    "$PIP" install "transkun==2.0.1" --no-deps --force-reinstall
    if ! validate_default_transkun_runtime; then
        error "TransKun 2.0.1 重装后包内 V2 资源仍未通过大小/SHA256 身份校验"
    fi
fi
success "TransKun 默认 V2 严格身份检查通过"

info "验证 Aria-AMT 钢琴后端..."
if ! "$PYTHON" - <<'PY'
import sys
sys.path.insert(0, '.')
from src.core.aria_amt_transcriber import AriaAmtTranscriber
reason = AriaAmtTranscriber.get_unavailable_reason()
print(reason or 'Aria-AMT source identity verified')
print('Aria-AMT package:', AriaAmtTranscriber.is_available())
print('Aria-AMT model:', AriaAmtTranscriber().is_model_available())
raise SystemExit(0 if reason == '' else 1)
PY
then
    info "Aria-AMT 缺失或源码身份不匹配，正在强制安装固定 GitHub archive..."
    "$PIP" install "aria-amt @ https://github.com/EleutherAI/aria-amt/archive/a1ab73fc901d1759ec3bc173c146b3c6a3040261.zip" --no-deps --force-reinstall
    "$PYTHON" - <<'PY'
import sys
sys.path.insert(0, '.')
from src.core.aria_amt_transcriber import AriaAmtTranscriber
reason = AriaAmtTranscriber.get_unavailable_reason()
print(reason or 'Aria-AMT source identity verified')
print('Aria-AMT package:', AriaAmtTranscriber.is_available())
raise SystemExit(0 if reason == '' else 1)
PY
fi

info "验证 ByteDance Piano 带踏板钢琴后端..."
if ! "$PYTHON" - <<'PY'
import sys
sys.path.insert(0, '.')
from src.core.bytedance_piano_transcriber import ByteDancePianoTranscriber
print('ByteDance Piano package:', ByteDancePianoTranscriber.is_available())
print('ByteDance Piano model:', ByteDancePianoTranscriber().is_model_available())
raise SystemExit(0 if ByteDancePianoTranscriber.is_available() else 1)
PY
then
    error "ByteDance Piano 安装校验失败：piano-transcription-inference、torchlibrosa 或 matplotlib 不完整。"
fi

# ───────────────────────── 验证核心依赖 ─────────────────────────
info "验证核心依赖..."

declare -A DEP_CHECKS=(
    ["PyQt6"]="PyQt6"
    ["torch"]="torch"
    ["librosa"]="librosa"
    ["mido"]="mido"
    ["soundfile"]="soundfile"
    ["pytorch_lightning"]="pytorch_lightning"
    ["beat-this"]="beat_this"
    ["fastapi"]="fastapi"
    ["audio_separator"]="audio_separator.separator"
)

for name in "${!DEP_CHECKS[@]}"; do
    mod="${DEP_CHECKS[$name]}"
    info "  validating $name..."
    if dep_output=$("$PYTHON" -c "import importlib; m=importlib.import_module('$mod'); print(getattr(m, '__version__', 'unknown'))" 2>&1); then
        success "  $name OK (version: $dep_output)"
    else
        echo "$dep_output"
        error "  $name import failed (full error shown above)"
    fi
done

if ! command -v ffmpeg &>/dev/null; then
    error "  ffmpeg 未找到；音频转换所需运行时不完整"
else
    FFMPEG_VER=$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
    success "  ffmpeg $FFMPEG_VER OK"
fi

info "验证受控 YourMT3+ 源码树身份..."
if ! "$PYTHON" - <<'PY'
from pathlib import Path

from src.utils.yourmt3_source_identity import validate_patched_yourmt3_source

source_dir = Path("YourMT3") / "amt" / "src"
manifest, file_count = validate_patched_yourmt3_source(source_dir)
print("YourMT3+ patched source manifest:", manifest)
print("YourMT3+ patched source files:", file_count)
PY
then
    error "YourMT3+ 源码树缺失或身份不匹配；需要恢复当前项目版本，可变上游源码与本版本不兼容。"
fi
success "YourMT3+ 源码身份检查通过"

# ───────────────────────── 复制本地模型集合 ─────────────────────────
info "从本地模型目录复制预下载模型：${MODELS_SOURCE}"
info "安装器不会联网下载模型；缺少任何必需模型都会立即停止。"

if ! "$PYTHON" "${REPO_DIR}/prepare_local_models.py" --source "$MODELS_SOURCE"; then
    error "本地模型复制或离线校验失败；安装器不会回退到联网下载。"
fi
success "YourMT3+、MIROS、分离/钢琴模型、MuScriptor Small/Medium/Large、ChordMini 与 SoundFont 已从本地复制并通过离线校验"

info "准备 MuseScore Studio 4 运行时（运行时组件，不属于模型权重）..."
if ! "$PYTHON" "${REPO_DIR}/download_musescore_runtime.py"; then
    error "MuseScore Studio 运行时准备或校验失败"
fi
success "MuseScore Studio 运行时准备完成"

# ───────────────────────── 验证启动脚本 ─────────────────────────
info "验证版本控制的启动脚本..."
RUN_SCRIPT="${REPO_DIR}/run.sh"
if [ ! -f "$RUN_SCRIPT" ]; then
    error "缺少版本控制的 run.sh；完整项目应包含该文件，安装器不会生成替代副本。"
fi
chmod +x "$RUN_SCRIPT"
success "启动脚本已验证: run.sh"

# ───────────────────────── 添加 ~/.bashrc 配置 ─────────────────────────
if $IS_WSL; then
    BASHRC="${HOME}/.bashrc"
    if ! grep -q "export DISPLAY=:0" "$BASHRC" 2>/dev/null; then
        echo "" >> "$BASHRC"
        echo "# WSLg 显示配置（Music to MIDI）" >> "$BASHRC"
        echo "export DISPLAY=:0" >> "$BASHRC"
        info "已将 DISPLAY=:0 添加到 ~/.bashrc"
    fi
fi

# ───────────────────────── 完成 ─────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  安装完成！${NC}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}运行方式：${NC}"
echo -e "  ${GREEN}./run.sh${NC}                    # 推荐：直接运行"
echo -e "  ${GREEN}./venv/bin/python -m src.main${NC}"
echo ""
echo -e "  ${BOLD}已自动安装：${NC}"
echo -e "  ${GREEN}✔${NC} Python 依赖"
echo -e "  ${GREEN}✔${NC} YourMT3+ 官方模式模型权重"
echo -e "  ${GREEN}✔${NC} BS-RoFormer SW Fixed 六声部模型"
echo -e "  ${GREEN}✔${NC} Leap XE 人声 + Leap Instrumental 伴奏模型"
echo -e "  ${GREEN}✔${NC} TransKun V2 Aug 模型"
echo -e "  ${GREEN}✔${NC} ByteDance Piano 带踏板模型"
echo -e "  ${GREEN}✔${NC} MuScriptor Small/Medium/Large 固定权重与 MuseScore General SoundFont"
echo -e "  ${GREEN}✔${NC} FluidSynth 真实 MIDI 播放链"
echo ""
echo -e "  ${BOLD}本地模型来源：${NC}"
echo -e "  ${YELLOW}${MODELS_SOURCE}${NC}（可用 MUSIC_TO_MIDI_MODELS_SOURCE 覆盖）"
echo ""
echo -e "  ${BOLD}模型维护命令（只复制本地文件，不联网下载）：${NC}"
echo -e "  ${YELLOW}venv/bin/python prepare_local_models.py --source \"${MODELS_SOURCE}\"${NC}"
echo -e "  ${YELLOW}venv/bin/python prepare_local_models.py --source \"${MODELS_SOURCE}\" --skip-verify${NC}"
echo ""
if $IS_WSL; then
    echo -e "  ${YELLOW}WSL 首次运行环境命令：${NC}source ~/.bashrc"
    echo ""
fi
