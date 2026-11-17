# 钢琴转录（桌面版功能抽取）- NVIDIA P40 (Pascal/sm_61) 适配版

本目录将 [music-to-midi](../README.md) 桌面版中的**钢琴转录**功能单独抽取为可独立使用的命令行工具，并针对 **NVIDIA Tesla P40 / Pascal 架构（Compute Capability 6.1, `sm_61`）** 提供兼容性说明与适配入口。

## 包含的钢琴引擎

| 引擎 ID | 名称 | 说明 | 主要依赖 |
|---|---|---|---|
| `transkun` | TransKun 2.0 | 官方 TransKun 钢琴转写 | `transkun==2.0.1`, PyTorch |
| `transkun_v2_aug` | TransKun V2 Aug | 官方增强 checkpoint（钢琴+踏板） | `transkun==2.0.1` + 下载的官方 checkpoint |
| `aria_amt` | Aria-AMT | Aria-AMT 钢琴转写 | 固定源码版 `aria-amt`/`ariautils`, safetensors, PyTorch, ffmpeg |
| `bytedance_pedal` | ByteDance Piano | 带踏板钢琴转写（CC64） | `piano-transcription-inference==0.0.6`, `torchlibrosa`, librosa, checkpoint |

## 便携执行包（推荐，Linux）

`build_linux_portable.sh` 会生成自包含的 `MusicToMidiPianoP40/` 目录：内置 Python、PyQt6 桌面 GUI、PyTorch 2.7.0 + CUDA 12.6、4 个钢琴引擎、全部模型权重和静态 ffmpeg，**运行时不需要联网、不需要 Docker，也不需要安装 Python 或 CUDA Toolkit**。

GUI 为**钢琴专用界面**（不是完整多乐器桌面应用）：选择音频/视频、引擎、输出目录、速度与 BF16 策略后开始转写，日志与进度实时显示。

```bash
# 在本机现有 .venv-p40 环境中原生构建（推荐，不涉及 Docker）
P40_MODEL_SOURCE="/path/to/MusicToMidi-Windows-GPU-App/_internal/models" \
  ./piano_transcribe_p40/build_linux_portable.sh

# 产物：dist-p40/MusicToMidiPianoP40/
```

原生构建的 glibc 下限与构建机一致（例如 Linux Mint 22 / Ubuntu 24.04 为 glibc 2.39）。如果要把同一个包拿到 **Ubuntu 20.04/22.04** 等旧系统上运行，再加一步可选的 Docker 构建（`P40_BUILD_MODE=docker`，基于 Debian 11 / glibc 2.31）：

```bash
P40_BUILD_MODE=docker \
P40_MODEL_SOURCE="/path/to/models" \
  ./piano_transcribe_p40/build_linux_portable.sh
```

> Docker 只影响“构建产物能兼容多旧的系统”，与运行无关；在本机 Cinnamon 上直接运行原生构建的包即可。

目标机要求：

- x86_64 Linux（原生包要求 glibc >= 2.39；Docker 构建包要求 glibc >= 2.31）
- 桌面 GUI 需要可用的 X11/Wayland 会话（纯服务器环境用 `run.sh` 命令行）
- NVIDIA 驱动 >= 560.28.03（仅需驱动，支持 CUDA 12.6 运行时）
- 运行 `./p40-check.sh` 确认 `CUDA arch compatible: True`

日常使用：

```bash
cd MusicToMidiPianoP40
./p40-check.sh                                  # GPU / 模型自检
./gui.sh                                        # 打开钢琴专用 GUI
./run.sh input.wav -o output -e transkun        # CLI：转写
./run.sh input.mp4 -o output -e aria_amt        # CLI：非 WAV 自动调用内置 ffmpeg
./run.sh --help
```

> 直接运行 `./MusicToMidiPianoP40`（不带参数）也会打开 GUI；带参数时仍按 CLI 执行。

分发包内附 `使用说明.txt`。添加启动脚本并打包分享：

```bash
./piano_transcribe_p40/package_linux_portable.sh dist-p40
# 产物：dist-p40/MusicToMidiPianoP40-linux-x86_64.tar.xz (+ .sha256)
```

## Windows exe 构建

Windows 便携版沿用仓库现有脚本（PyInstaller onedir）：

```powershell
# 在 Windows + Python 3.11 环境、仓库根目录执行
.\install.ps1                      # 安装依赖（可用 -ModelSourceDir 从本地复制模型）
.\build_portable.ps1               # 生成 Windows 便携目录/exe
```

若只想从本地目录复制模型而不重新下载：

```powershell
.\install.ps1 -ModelSourceDir "D:\MusicToMidi-Windows-GPU-App\_internal\models"
```

`build_portable.ps1` 的模型路径由 `MUSIC_TO_MIDI_BUNDLE_*_DIR` 环境变量控制（见脚本第 560 行起）。

## 目录说明

- `transcribe.py`：钢琴转录 CLI（复用仓库 `src/core/*` 钢琴转录器与工具）。
- `gui.py`：钢琴专用 PyQt6 GUI（通过子进程调用同一 CLI，GUI 本身不导入 PyTorch）。
- `p40_check.py`：P40/sm_61、CUDA、PyTorch、驱动与常见兼容性检查。
- `requirements-p40.txt`：P40 平台依赖安装建议（重点是 PyTorch/CUDA 组合）。
- `portable_entry.py` / `PianoP40.spec`：PyInstaller 冻结入口与打包配置。
- `build_linux_portable.sh` / `_build_in_container.sh`：Linux 便携包构建脚本。
- `portable/`：便携包内的 `gui.sh`、`run.sh`、`p40-check.sh` 与 `使用说明.txt`。

> 设计取舍：为避免复制整套桌面/GUI/多乐器代码，本工具通过仓库根目录 `sys.path` 复用 `src/` 中已验证的钢琴转录实现；请在**仓库根目录**运行，或保证 `music-to-midi` 源码可被 Python 导入。

## NVIDIA P40 适配要点

Tesla P40 为 **GP102 / Pascal**，关键特性：

- Compute Capability：**6.1 (`sm_61`)**
- 显存：通常 24GB
- **无 Tensor Core**，现代 BF16/FP8/Transformer Engine 加速不可用；FP16 吞吐也不如 Turing+；**不支持 BF16 CUDA 运算**。
- 新版 PyTorch 官方 wheel 常只包含较新的 SM。**但 `sm_60`（Pascal）与 `sm_61` 二进制兼容**：PyTorch 2.7.0 + CUDA 12.6（`torch.cuda.get_arch_list() == ['sm_50','sm_60','sm_70','sm_75','sm_80','sm_86','sm_90']`）可直接在 P40 上运行，无需自编译。CUDA 12.8+ 的官方 wheel 已移除 Pascal，因此本项目固定 **cu126**。
- 若运行时报错 `no kernel image is available for execution on the device`，说明当前 PyTorch/CUDA 构建与 P40 不兼容。

### BF16 / FP32（“BF32”）回退设置

- 配置项：`cuda_bf16_policy`（`Config` 字段，CLI：`--cuda-bf16-policy`）
  - `auto`（默认）：仅在 CUDA 设备/运行时支持 BF16 时使用 BF16；**P40/sm_61 等不支持 BF16 的卡自动回退 FP32**（32-bit float）。对后续支持 BF16 的新 NVIDIA 卡保持兼容。
  - `fp32`：始终使用 FP32，适合 P40 或需要强制禁用 BF16 的场景。
  - `bf16`：在支持 BF16 时使用 BF16，否则回退 FP32。
- 当前已将该策略应用于 Aria-AMT 的 CUDA BF16 缓存/计算路径（`src/core/aria_amt_transcriber.py`）。其他 BF16 CUDA 路径如后续引入，应复用 `src.utils.gpu_utils.get_preferred_cuda_compute_dtype`。

### 推荐做法

1. **先检查环境**（在仓库根目录）：
   ```bash
   python piano_transcribe_p40/p40_check.py
   ```
2. **使用含 Pascal SASS 的 PyTorch**。已验证组合：
   ```bash
   pip install torch==2.7.0 torchaudio==2.7.0 torchvision==0.22.0 \
     --index-url https://download.pytorch.org/whl/cu126
   ```
   该 wheel 含 `sm_60`，可直接在 P40（`sm_61`）上执行。也可从源码编译并设置：
   ```bash
   export TORCH_CUDA_ARCH_LIST="6.1"
   ```
   若无法获得合适 GPU 构建，可使用 `--cpu` 运行（较慢，但功能可用）。

3. **安装基础依赖与钢琴引擎依赖**（示例）：
   ```bash
   # 创建虚拟环境后
   python -m pip install -r requirements.txt          # 按项目安装基础依赖（注意 torch 版本需适配 P40）
   # 或参考 piano_transcribe_p40/requirements-p40.txt 调整 torch/torchaudio

   # Aria-AMT（项目采用固定源码/--no-deps 策略，见 requirements.txt 注释）
   # TransKun 已在 requirements.txt 中固定；ByteDance 依赖见 requirements.txt
   ```

4. **准备模型文件**（按所选引擎）：
   ```bash
   python download_aria_amt_model.py
   python download_bytedance_piano_model.py
   python download_transkun_v2_aug_model.py
   # TransKun 2.0 的权重随 transkun 包提供，需确保包安装完整
   ```

5. **ffmpeg**：Aria-AMT/音频处理可能需要 ffmpeg。请确保系统 PATH 中有 `ffmpeg`，或项目可解析到 ffmpeg。

## 使用示例

在仓库根目录 `/path/to/music-to-midi` 运行：

```bash
# 检查 P40/CUDA/PyTorch
python piano_transcribe_p40/p40_check.py

# TransKun（GPU，自动检测；P40 需 sm_61 兼容 torch）
python piano_transcribe_p40/transcribe.py input.wav -o output_dir -e transkun

# 强制 CPU（P40 无兼容 torch 时的回退）
python piano_transcribe_p40/transcribe.py input.wav -o output_dir -e transkun --cpu

# ByteDance 带踏板
python piano_transcribe_p40/transcribe.py input.wav -o output_dir -e bytedance_pedal --cpu

# Aria-AMT，手动指定 BPM（可跳过 Beat This 节拍模型）
python piano_transcribe_p40/transcribe.py input.wav -o output_dir -e aria_amt --bpm 120

# P40：BF16 CUDA 运算在不支持的卡上回退 FP32（auto 默认自动处理；可显式指定）
python piano_transcribe_p40/transcribe.py input.wav -o output_dir -e aria_amt --cuda-bf16-policy fp32

# 查看帮助
python piano_transcribe_p40/transcribe.py --help
```

## 已做的 P40 相关适配

- `src/utils/gpu_utils.py`：CUDA 架构不兼容报错中增加 **sm_61/Pascal (P40 等)** 专项提示；新增 `get_cuda_compatible_arches` / `is_cuda_arch_compatible`（按 NVIDIA 二进制兼容规则把 `sm_60` 视为对 `sm_61` 可用）；新增 BF16 能力检测与 `cuda_bf16_policy` 精度选择（`auto` 下 P40/sm_61 等不支持 BF16 时回退 FP32，对支持 BF16 的新 NVIDIA 卡保持兼容）。
- `src/models/data_models.py`：新增配置项 `cuda_bf16_policy`（`auto`/`fp32`/`bf16`，默认 `auto`）。
- `src/core/aria_amt_transcriber.py`：CUDA 计算/KV cache dtype 按策略与设备能力选择；P40 上 BF16 CUDA 运算自动回退 FP32（32-bit float），并打印实际 dtype。
- `p40_check.py`：检测 `sm_61`、PyTorch 架构列表、**实际可用架构条目**、BF16 支持与回退提示。
- `transcribe.py`：提供 `--cpu`/`--gpu`、`--cuda-bf16-policy`、可选 BPM/跳过节拍检测、模型可用性检查；仅加载钢琴转录所需路径。
- `gui.py`：钢琴专用 PyQt6 界面，作为 CLI 的桌面前端；转写进程独立运行，GUI 不导入 PyTorch。
- `PianoP40.spec` + 构建脚本：onedir 便携包，按 `$ORIGIN/../../nvidia/*/lib` 布局打包 CUDA/cuDNN 动态库，内置静态 ffmpeg、模型权重与 PyQt6。

## 注意事项

- P40 显存大但算力/架构较老，部分模型在 CPU 上可能更稳定；请根据实际速度选择 `--cpu`/GPU。
- Aria-AMT 在 CUDA 路径使用上游推理代码；在 XPU/Windows/流式回调场景项目有专用路径。P40 上走标准 CUDA 路径时，需确保 torch/依赖版本兼容。
- 本抽取工具只聚焦钢琴转录 4 个模式，**不包含**完整桌面应用的多乐器、人声分离、六声部分离等流程；附带的是钢琴专用 GUI。
- 首次运行各引擎前需完成对应模型下载与许可证/来源确认（见项目根目录 `download_*.py` 与 `THIRD_PARTY_NOTICES.md`）。
