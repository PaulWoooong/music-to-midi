#!/usr/bin/env bash
# Music to MIDI - Linux 便携包构建脚本（PyInstaller onedir）
#
# 与 Windows 的 build_portable.ps1 对应：使用同一份 MusicToMidi.spec 打包
# GUI（MusicToMidi）、推理后端（MusicToMidiBackend）与 CLI（MusicToMidiCLI），
# 并把全部模型、FluidSynth、MuseScore、FFmpeg 打进产物。
#
# 模型默认从本机已有的便携版目录复制/收集，不重新下载。
# 目标显卡：NVIDIA Tesla P40（sm_61）。PyTorch cu126 wheel 含 sm_60 SASS，
# 按 NVIDIA 二进制兼容规则可直接在 sm_61 上执行，同时兼容更新的显卡。
#
# 用法:
#   ./build_portable_linux.sh                        # 自动探测模型源并构建
#   ./build_portable_linux.sh --model-source /path/to/_internal
#   ./build_portable_linux.sh --package              # 构建后生成 tar.xz
#   ./build_portable_linux.sh --help

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# LD_LIBRARY_PATH 中的空条目等价于“当前目录”，会让构建/打包过程从工作目录
# 误加载同名 .so（例如 MuseScore 自带的旧版 libbrotli/libc），这里提前清理。
if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    LD_LIBRARY_PATH="$(printf '%s' "$LD_LIBRARY_PATH" | tr ':' '\n' | awk 'NF' | paste -sd: -)"
    export LD_LIBRARY_PATH
fi

MODEL_SOURCE="${MUSIC_TO_MIDI_MODEL_SOURCE:-}"
VENV_DIR="${MUSIC_TO_MIDI_VENV:-$REPO_DIR/venv}"
DIST_DIR="$REPO_DIR/dist-linux"
WORK_DIR="$REPO_DIR/build/pyinstaller-linux"
BUNDLE_NAME="MusicToMidi-Linux-P40"
MAKE_PACKAGE=false
CLEAN=true
ALLOW_ARCH_MISMATCH=false

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

usage() {
    cat <<EOF
用法: ./build_portable_linux.sh [选项]

选项:
  --model-source <dir>   模型/运行时资源根目录（含 models/、resources/、tools/、external/），
                         或直接的 _internal 目录；默认自动探测本机已解包的便携版
  --venv <dir>           构建用 Python 虚拟环境（默认 ./venv）
  --dist <dir>           成品输出目录（默认 ./dist-linux）
  --work <dir>           PyInstaller 工作目录（默认 ./build/pyinstaller-linux）
  --name <name>          成品目录名（默认 MusicToMidi-Linux-P40）
  --package              构建完成后生成 <name>-linux-x86_64.tar.xz 与 .sha256
  --no-clean             保留上一次的 PyInstaller 中间产物
  --allow-arch-mismatch  跳过 PyTorch 对 sm_61 的架构检查（不建议）
  -h, --help             显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model-source) MODEL_SOURCE="${2:-}"; shift 2 ;;
        --model-source=*) MODEL_SOURCE="${1#*=}"; shift ;;
        --venv) VENV_DIR="${2:-}"; shift 2 ;;
        --dist) DIST_DIR="${2:-}"; shift 2 ;;
        --work) WORK_DIR="${2:-}"; shift 2 ;;
        --name) BUNDLE_NAME="${2:-}"; shift 2 ;;
        --package) MAKE_PACKAGE=true; shift ;;
        --no-clean) CLEAN=false; shift ;;
        --allow-arch-mismatch) ALLOW_ARCH_MISMATCH=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) error "未知参数: $1（使用 --help 查看用法）" ;;
    esac
done

PYTHON="$VENV_DIR/bin/python"
[[ -x "$PYTHON" ]] || error "未找到构建环境: $PYTHON
请先创建 venv 并安装依赖:
  /usr/bin/python3.12 -m venv venv
  venv/bin/pip install torch==2.7.0 torchaudio==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu126
  venv/bin/pip install -r requirements.txt
  bash install.sh --help   # 参考 install.sh 中的 audio-separator / muscriptor / aria-amt 安装步骤"

# ── 解析资源根目录 ────────────────────────────────────────────
resolve_asset_root() {
    local candidate
    for candidate in "$@"; do
        [[ -n "$candidate" ]] || continue
        if [[ -d "$candidate/models" || -d "$candidate/_internal/models" ]]; then
            if [[ -d "$candidate/models" ]]; then
                printf '%s\n' "$candidate"; return 0
            fi
            printf '%s\n' "$candidate/_internal"; return 0
        fi
    done
    return 1
}

if [[ -z "$MODEL_SOURCE" ]]; then
    if ! MODEL_SOURCE="$(resolve_asset_root \
        "$HOME/Music/MusicToMidi-Linux-GPU-App" \
        "$HOME/Music/MusicToMidi-Linux-GPU-App/_internal" \
        "/media/paul/02D010A3D0109F4B/MusicToMidi-Linux-GPU-Portable/v1.10.0" \
        "/media/paul/02D010A3D0109F4B/MusicToMidi-Linux-GPU-Portable/v1.10.0/MusicToMidi-Windows-GPU-App/_internal" \
        "/media/paul/02D010A3D0109F4B/MusicToMidi-Linux-GPU-Portable/MusicToMidi-Windows-GPU-App/_internal")"; then
        error "未找到模型资源目录；请用 --model-source 指定已解包的便携版 _internal 目录"
    fi
else
    MODEL_SOURCE="$(resolve_asset_root "$MODEL_SOURCE")" || error "模型资源目录结构不正确: $MODEL_SOURCE"
fi
MODEL_SOURCE="$(cd "$MODEL_SOURCE" && pwd)"
success "模型/资源根目录: $MODEL_SOURCE"

# ── 映射到 MusicToMidi.spec 需要的环境变量 ───────────────────
export MUSIC_TO_MIDI_ACCELERATOR="${MUSIC_TO_MIDI_ACCELERATOR:-cuda}"
set_if_dir() {
    local var="$1" dir="$2"
    if [[ -n "${!var:-}" && -d "${!var}" ]]; then
        return 0
    fi
    [[ -d "$dir" ]] || { unset "$var" 2>/dev/null || true; return 0; }
    export "$var"="$dir"
}

set_if_dir MUSIC_TO_MIDI_BUNDLE_AUDIO_SEPARATOR_DIR     "$MODEL_SOURCE/models/audio-separator"
set_if_dir MUSIC_TO_MIDI_BUNDLE_ARIA_AMT_DIR            "$MODEL_SOURCE/models/aria_amt"
set_if_dir MUSIC_TO_MIDI_BUNDLE_BYTEDANCE_PIANO_DIR     "$MODEL_SOURCE/models/bytedance_piano"
set_if_dir MUSIC_TO_MIDI_BUNDLE_BEAT_THIS_DIR           "$MODEL_SOURCE/models/beat_this"
set_if_dir MUSIC_TO_MIDI_BUNDLE_TRANSKUN_V2_AUG_DIR     "$MODEL_SOURCE/models/transkun_v2_aug"
set_if_dir MUSIC_TO_MIDI_BUNDLE_YOURMT3_DIR             "$MODEL_SOURCE/models/yourmt3_all"
set_if_dir MUSIC_TO_MIDI_BUNDLE_MIROS_DIR               "$MODEL_SOURCE/external/ai4m-miros"
set_if_dir MUSIC_TO_MIDI_BUNDLE_CHORDMINI_DIR           "$MODEL_SOURCE/models/chordmini"
set_if_dir MUSIC_TO_MIDI_BUNDLE_MUSCRIPTOR_SMALL_DIR    "$MODEL_SOURCE/models/muscriptor_small"
set_if_dir MUSIC_TO_MIDI_BUNDLE_MUSCRIPTOR_MEDIUM_DIR   "$MODEL_SOURCE/models/muscriptor_medium"
set_if_dir MUSIC_TO_MIDI_BUNDLE_MUSCRIPTOR_LARGE_DIR    "$MODEL_SOURCE/models/muscriptor_large"
set_if_dir MUSIC_TO_MIDI_BUNDLE_MUSCRIPTOR_ASSETS_DIR   "$MODEL_SOURCE/models/muscriptor_assets"
set_if_dir MUSIC_TO_MIDI_BUNDLE_FLUIDSYNTH_DIR          "$MODEL_SOURCE/resources/fluidsynth"
set_if_dir MUSIC_TO_MIDI_BUNDLE_MUSESCORE_DIR           "$MODEL_SOURCE/resources/musescore"
set_if_dir MUSIC_TO_MIDI_BUNDLE_FFMPEG_DIR              "$MODEL_SOURCE/tools/ffmpeg"

# ── 校验资源与运行时 ─────────────────────────────────────────
info "校验打包资源..."
"$PYTHON" - "$REPO_DIR" "$ALLOW_ARCH_MISMATCH" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

repo = Path(sys.argv[1])
allow_arch_mismatch = sys.argv[2].lower() == "true"

required = {
    "MUSIC_TO_MIDI_BUNDLE_AUDIO_SEPARATOR_DIR": "models/audio-separator",
    "MUSIC_TO_MIDI_BUNDLE_ARIA_AMT_DIR": "models/aria_amt",
    "MUSIC_TO_MIDI_BUNDLE_BYTEDANCE_PIANO_DIR": "models/bytedance_piano",
    "MUSIC_TO_MIDI_BUNDLE_BEAT_THIS_DIR": "models/beat_this",
    "MUSIC_TO_MIDI_BUNDLE_TRANSKUN_V2_AUG_DIR": "models/transkun_v2_aug",
    "MUSIC_TO_MIDI_BUNDLE_YOURMT3_DIR": "models/yourmt3_all",
    "MUSIC_TO_MIDI_BUNDLE_MIROS_DIR": "external/ai4m-miros",
    "MUSIC_TO_MIDI_BUNDLE_CHORDMINI_DIR": "models/chordmini",
    "MUSIC_TO_MIDI_BUNDLE_MUSCRIPTOR_SMALL_DIR": "models/muscriptor_small",
    "MUSIC_TO_MIDI_BUNDLE_MUSCRIPTOR_MEDIUM_DIR": "models/muscriptor_medium",
    "MUSIC_TO_MIDI_BUNDLE_MUSCRIPTOR_LARGE_DIR": "models/muscriptor_large",
    "MUSIC_TO_MIDI_BUNDLE_MUSCRIPTOR_ASSETS_DIR": "models/muscriptor_assets",
    "MUSIC_TO_MIDI_BUNDLE_FLUIDSYNTH_DIR": "resources/fluidsynth",
    "MUSIC_TO_MIDI_BUNDLE_MUSESCORE_DIR": "resources/musescore",
    "MUSIC_TO_MIDI_BUNDLE_FFMPEG_DIR": "tools/ffmpeg",
}

errors = []
for env_name, label in required.items():
    value = os.environ.get(env_name, "")
    if not value or not Path(value).is_dir():
        errors.append(f"缺少资源 {label} ({env_name}={value!r})")
    elif not any(Path(value).iterdir()):
        errors.append(f"资源目录为空 {label}: {value}")

if not errors:
    ffmpeg_dir = Path(os.environ["MUSIC_TO_MIDI_BUNDLE_FFMPEG_DIR"])
    for tool in ("ffmpeg", "ffprobe"):
        candidates = [ffmpeg_dir / "bin" / tool, ffmpeg_dir / tool]
        if not any(p.is_file() and p.stat().st_size > 0 for p in candidates):
            errors.append(f"缺少可执行文件: {tool} (在 {ffmpeg_dir} 下)")

    musescore = Path(os.environ["MUSIC_TO_MIDI_BUNDLE_MUSESCORE_DIR"])
    apprun = musescore / "AppRun"
    license_file = musescore / "LICENSE.txt"
    if not apprun.is_file():
        errors.append(f"缺少 MuseScore AppRun: {apprun}")
    if not license_file.is_file():
        errors.append(f"缺少 MuseScore LICENSE.txt: {license_file}")

    manifest = json.loads((repo / "resources" / "chordmini-source.json").read_text(encoding="utf-8"))
    chordmini = Path(os.environ["MUSIC_TO_MIDI_BUNDLE_CHORDMINI_DIR"])
    for relative, expected in manifest.items():
        target = chordmini / relative
        if not target.is_file():
            errors.append(f"ChordMini 文件缺失: {target}")
            break
        if hashlib.file_digest(target.open("rb"), "sha256").hexdigest() != expected:
            errors.append(f"ChordMini 身份校验失败: {relative}")
            break

import torch
arch_list = list(torch.cuda.get_arch_list())
print(f"PyTorch: {torch.__version__} (CUDA {torch.version.cuda})")
print(f"CUDA arch list: {arch_list}")
compatible = any(arch in ("sm_61", "sm_60", "compute_61", "compute_60") for arch in arch_list) or any(
    arch.startswith("compute_") and tuple(int(x) for x in arch.split("_", 1)[1].split(".")) >= (6, 1)
    for arch in arch_list
    if arch.split("_", 1)[1].count(".") == 1
)
if not compatible:
    message = (
        "当前 PyTorch wheel 不包含可在 sm_61 (Tesla P40) 上执行的代码；"
        "请改用含 sm_60/sm_61 的 cu126 wheel 或源码编译版本"
    )
    if allow_arch_mismatch:
        print(f"WARN: {message}", file=sys.stderr)
    else:
        errors.append(message)

if errors:
    print("\n".join(f"  - {msg}" for msg in errors), file=sys.stderr)
    raise SystemExit(1)
print("资源校验通过")
PY
success "资源校验通过"

# ── 清理旧产物 ──────────────────────────────────────────────
if [[ "$CLEAN" == true ]]; then
    info "清理旧的构建中间目录: $WORK_DIR"
    rm -rf "$WORK_DIR"
fi
mkdir -p "$DIST_DIR"

# ── PyInstaller 构建 ────────────────────────────────────────
info "开始 PyInstaller 构建（onedir，含 GUI/Backend/CLI）..."
info "输出目录: $DIST_DIR"
"$PYTHON" -m PyInstaller \
    --noconfirm \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    "$REPO_DIR/MusicToMidi.spec"

BUILT_DIR="$DIST_DIR/MusicToMidi"
[[ -d "$BUILT_DIR" ]] || error "构建未生成预期的目录: $BUILT_DIR"

if [[ "$BUNDLE_NAME" != "MusicToMidi" ]]; then
    rm -rf "$DIST_DIR/$BUNDLE_NAME"
    mv "$BUILT_DIR" "$DIST_DIR/$BUNDLE_NAME"
fi
BUNDLE_DIR="$DIST_DIR/$BUNDLE_NAME"

# PyInstaller 会把 Pillow 自带的新版 libbrotli 与 MuseScore/系统里的旧版
# 收集成同名库，导致 onnxruntime 导入时出现 undefined symbol
# (BrotliSharedDictionaryDestroyInstance)。这里统一为同一版本的一对库。
normalize_brotli_libs() {
    local internal="$BUNDLE_DIR/_internal"
    local common dec
    common="$(ls "$internal"/pillow.libs/libbrotlicommon-*.so.* 2>/dev/null | head -n 1 || true)"
    dec="$(ls "$internal"/pillow.libs/libbrotlidec-*.so.* 2>/dev/null | head -n 1 || true)"
    if [[ -n "$common" && -n "$dec" ]]; then
        cp -f "$common" "$internal/libbrotlicommon.so.1"
        cp -f "$dec" "$internal/libbrotlidec.so.1"
        chmod 755 "$internal/libbrotlicommon.so.1" "$internal/libbrotlidec.so.1"
        info "已统一 libbrotli 版本: $(basename "$common") / $(basename "$dec")"
    fi
}
normalize_brotli_libs

# 打包的 FFmpeg 4.4 是动态链接版本，spec 只把 tools/ffmpeg 作为数据复制，
# 不会自动带上 libav*/libsw* 依赖。这里从模型源目录补齐缺失的 soname。
ensure_ffmpeg_runtime_libs() {
    local internal="$BUNDLE_DIR/_internal"
    local ffmpeg_bin="$internal/tools/ffmpeg/bin/ffmpeg"
    local ffprobe_bin="$internal/tools/ffmpeg/bin/ffprobe"
    [[ -x "$ffmpeg_bin" ]] || return 0

    local libsrc=""
    local candidate
    for candidate in "$MODEL_SOURCE" "$MODEL_SOURCE/_internal"; do
        if [[ -f "$candidate/libavcodec.so.58" ]]; then
            libsrc="$candidate"
            break
        fi
    done
    if [[ -z "$libsrc" ]]; then
        warn "未找到 FFmpeg 4.4 运行库（libavcodec.so.58）；如目标机缺少系统 FFmpeg，内置 ffmpeg 可能无法启动"
        return 0
    fi

    local round missing soname
    for round in 1 2 3 4; do
        missing="$(LD_LIBRARY_PATH="$internal" ldd "$ffmpeg_bin" "$ffprobe_bin" 2>/dev/null \
            | awk '/not found/ {print $1}' | sort -u)"
        [[ -z "$missing" ]] && break
        while read -r soname; do
            [[ -n "$soname" ]] || continue
            if [[ -f "$libsrc/$soname" ]]; then
                cp -f "$libsrc/$soname" "$internal/$soname"
            else
                warn "FFmpeg 缺少运行库且模型源中没有: $soname"
            fi
        done <<< "$missing"
    done
    if LD_LIBRARY_PATH="$internal" ldd "$ffmpeg_bin" 2>/dev/null | grep -q "not found"; then
        warn "内置 FFmpeg 仍有未解析的动态库，请在有系统 FFmpeg 的环境中验证"
    else
        success "内置 FFmpeg/ffprobe 动态库已就绪"
    fi
}
ensure_ffmpeg_runtime_libs

# FluidSynth 自带的 lib/ 里包含构建机的 glibc（libc.so.6、libm、libpthread 等），
# 在较新的系统上会与宿主 loader 冲突并导致 segfault。glibc 必须始终使用宿主版本。
prune_fluidsynth_glibc() {
    local dir="$BUNDLE_DIR/_internal/resources/fluidsynth/lib"
    [[ -d "$dir" ]] || return 0
    local name
    for name in libc.so.6 libm.so.6 libpthread.so.0 libdl.so.2 librt.so.1 \
                libresolv.so.2 libutil.so.1 libnsl.so.1 libanl.so.1 \
                libBrokenLocale.so.1 libc_malloc_debug.so.0 libthread_db.so.1 \
                ld-linux-x86-64.so.2 ld-linux.so.2; do
        rm -f "$dir/$name"
    done
    success "已移除 FluidSynth 自带的 glibc 运行库（改用宿主 glibc）"
}
prune_fluidsynth_glibc

# ── 写入启动脚本与说明 ──────────────────────────────────────
info "写入启动脚本..."
cat > "$BUNDLE_DIR/gui.sh" <<'EOF'
#!/bin/sh
# 启动图形界面（无窗口管理器/服务器时请使用 cli.sh）
cd "$(dirname "$0")"
exec ./MusicToMidi "$@"
EOF
cat > "$BUNDLE_DIR/cli.sh" <<'EOF'
#!/bin/sh
# 命令行转换: ./cli.sh song.wav -o out
# 批量:       ./cli.sh batch /data/audio --recursive -o /data/midi
cd "$(dirname "$0")"
exec ./MusicToMidiCLI "$@"
EOF
cat > "$BUNDLE_DIR/backend.sh" <<'EOF'
#!/bin/sh
# 启动版本化推理 API 后端
cd "$(dirname "$0")"
exec ./MusicToMidiBackend "$@"
EOF
cat > "$BUNDLE_DIR/p40-check.sh" <<'EOF'
#!/bin/sh
# NVIDIA P40 (sm_61) 运行时自检
cd "$(dirname "$0")"
echo "== NVIDIA 驱动 / 显卡 =="
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,compute_cap,driver_version,memory.total --format=csv
else
    echo "未找到 nvidia-smi（将只能使用 CPU）"
fi
echo
echo "== 可用转换路线 =="
./MusicToMidiCLI routes --json
EOF
chmod +x "$BUNDLE_DIR/gui.sh" "$BUNDLE_DIR/cli.sh" "$BUNDLE_DIR/backend.sh" "$BUNDLE_DIR/p40-check.sh"

cat > "$BUNDLE_DIR/使用说明.txt" <<'EOF'
音乐转 MIDI 转换器 - Linux 便携版（NVIDIA P40 / sm_61 及更新的 NVIDIA 显卡）

快速开始：
  ./gui.sh                 启动图形界面
  ./cli.sh song.wav        命令行转换单个文件
  ./cli.sh batch <目录>    命令行批量转换
  ./p40-check.sh           查看显卡驱动与可用转换路线

本目录已内置 Python、PyTorch/CUDA 运行时、全部模型、FluidSynth、MuseScore
与 FFmpeg，无需安装 Python/CUDA Toolkit，也无需联网。

处理模式（完整 7 种）：
  1. SMART：完整混音多乐器转写（YourMT3+ / MIROS / MuScriptor）
  2. VOCAL_SPLIT：Leap XE 人声 + Leap Instrumental 伴奏
  3. SIX_STEM_SPLIT：BS-RoFormer SW Fixed 六声部
  4. PIANO_TRANSKUN：TransKun 2.0.1 默认 V2
  5. PIANO_TRANSKUN_V2_AUG：TransKun V2 Aug
  6. PIANO_ARIA_AMT：Aria-AMT
  7. PIANO_BYTEDANCE_PEDAL：ByteDance Piano（保留踏板 CC64）

P40 说明：
  Tesla P40 为 Pascal / sm_61，不支持 BF16。Aria-AMT 等 BF16 路径会按
  `cuda_bf16_policy=auto` 自动回退到 FP32；支持 BF16 的新显卡仍使用 BF16。
  运行时若出现 “no kernel image is available”，请确认 PyTorch 为含
  sm_60/sm_61 的构建（如 cu126），且 NVIDIA 驱动 >= 525.60.13（建议 550 及以上）。

要求：Linux x86_64（glibc >= 2.39）、X11/Wayland（GUI）、NVIDIA 驱动。
EOF

# ── 可选打包 ────────────────────────────────────────────────
if [[ "$MAKE_PACKAGE" == true ]]; then
    ARCHIVE="$DIST_DIR/$BUNDLE_NAME-linux-x86_64.tar.xz"
    info "生成压缩包（xz -T0 -1，可能需要较长时间）..."
    rm -f "$ARCHIVE" "$ARCHIVE.sha256"
    tar -C "$DIST_DIR" -I 'xz -T0 -1' -cf "$ARCHIVE" "$BUNDLE_NAME"
    (cd "$DIST_DIR" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")
    success "压缩包: $ARCHIVE"
fi

success "构建完成: $BUNDLE_DIR"
du -sh "$BUNDLE_DIR" 2>/dev/null || true
