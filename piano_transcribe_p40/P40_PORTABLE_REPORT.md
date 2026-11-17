# MusicToMidi 钢琴转录 P40 便携包 — 交付报告

> 日期：2026-11-16
> 目标平台：NVIDIA Tesla P40（Pascal / Compute Capability 6.1 / `sm_61`）
> 构建主机：Linux Mint 22.3（Cinnamon，glibc 2.39，Python 3.12.3）

---

## 1. 目标

1. 从桌面版中抽取**钢琴转录**功能，适配 NVIDIA P40（`sm_61`）。
2. P40 不支持 CUDA BF16 运算，需要在 BF16 路径自动回退 FP32（32-bit float），同时对支持 BF16 的新显卡保持兼容。
3. 提供 Linux 便携执行包：内置 Python、PyTorch/CUDA、模型与 ffmpeg，**运行时无需联网、无需 Docker**。模型直接从本地目录打包，不重新下载。
4. 提供钢琴专用桌面 GUI（PyQt6）：只暴露 4 个钢琴引擎，复用同一套运行时与推理代码。
5. 保留 Windows exe 与 Ubuntu 源码安装方式，并支持从本地目录复制模型。

---

## 2. 交付物

| 路径 | 大小 | 说明 |
|---|---|---|
| `dist-p40/MusicToMidiPianoP40/` | 6.6 GB | 可直接运行的便携目录（含钢琴专用 GUI 与 CLI） |
| `dist-p40/MusicToMidiPianoP40-linux-x86_64.tar.xz` | 2.7 GB | 分发压缩包 |
| `dist-p40/MusicToMidiPianoP40-linux-x86_64.tar.xz.sha256` | — | SHA256 校验文件 |

SHA256：

```
e7aef31eed9c532cbb88ad300c7eef598094eaba486020c1c8a026ce3b908fe1  MusicToMidiPianoP40-linux-x86_64.tar.xz
```

便携包内包含：

- Python 3.12 运行时（PyInstaller onedir）
- PyTorch 2.7.0 + CUDA 12.6（cu126）、torchaudio、torchvision
- PyQt6 6.7.1 / Qt 6.7.1（钢琴专用桌面 GUI，manylinux_2_28 构建）
- 4 个钢琴引擎：TransKun、TransKun V2 Aug、Aria-AMT、ByteDance Piano
- Beat This `final0.ckpt` 节拍检测模型
- 全部模型权重：`_internal/models/{aria_amt,bytedance_piano,transkun_v2_aug,beat_this}`
- 静态 ffmpeg：`_internal/tools/ffmpeg/bin/ffmpeg`
- CUDA/cuDNN 动态库：`_internal/nvidia/*/lib`、`_internal/cusparselt`
- Qt 平台插件与 xcb 依赖：`_internal/PyQt6/Qt6/plugins/platforms/`、`_internal/libxcb-*.so*`
- 启动脚本：`gui.sh`、`run.sh`、`p40-check.sh`、`使用说明.txt`

---

## 3. 运行要求

| 项目 | 要求 |
|---|---|
| 系统 | Linux x86_64 |
| 桌面（GUI） | X11 或 Wayland 会话；纯服务器可用 CLI |
| glibc | 当前原生包要求 **>= 2.39**（Mint 22 / Ubuntu 24.04+） |
| 显卡 | Tesla P40（24GB）；也支持 sm_70/75/80/86/90 |
| 驱动 | NVIDIA Linux 驱动 **>= 560.28.03**（支持 CUDA 12.6 运行时） |
| 其他 | 无需安装 Python、CUDA Toolkit、ffmpeg；无需 Docker、无需联网 |

> PyTorch cu126 wheel 内置 `sm_60` SASS。NVIDIA 二进制兼容规则下，`sm_60` cubin 可在 `sm_61`（P40）上执行，因此**不需要**包含字面 `sm_61` 的 wheel。

---

## 4. 快速使用

```bash
tar -xJf MusicToMidiPianoP40-linux-x86_64.tar.xz
cd MusicToMidiPianoP40

./p40-check.sh                                   # 环境 / 模型自检
./gui.sh                                         # 图形界面（钢琴专用）
./run.sh input.wav -o output -e transkun         # 默认 TransKun
./run.sh input.wav -o output -e transkun_v2_aug
./run.sh input.mp3 -o output -e aria_amt
./run.sh input.mp4 -o output -e bytedance_pedal  # 内置 ffmpeg 自动转 WAV
./run.sh --help
```

> 直接运行 `./MusicToMidiPianoP40`（不带参数）会打开 GUI；带参数时按 CLI 执行。

GUI 功能：选择音频/视频、输出目录、引擎、速度模式（自动 Beat This / 固定 120 BPM / 手动 BPM）、CUDA 精度策略、CPU 或 GPU 序号；运行中实时显示日志与进度，可取消，完成后可直接打开输出目录。GUI 通过子进程调用同一 CLI，因此 GPU/模型行为与命令行完全一致。

常用参数：

| 参数 | 说明 |
|---|---|
| `-e, --engine` | `transkun` / `transkun_v2_aug` / `aria_amt` / `bytedance_pedal` |
| `-o, --output-dir` | 输出目录（默认 `output_piano_p40`） |
| `--bpm N` | 指定速度，跳过节拍检测 |
| `--skip-beat-detect` | 固定 120 BPM |
| `--cuda-bf16-policy` | `auto`（默认）/ `fp32` / `bf16` |
| `--cpu` | 强制 CPU |
| `--gpu-device N` | 多卡时指定 GPU 序号 |

输出命名：

```
输入名_piano_transkun.mid
输入名_piano_transkun_v2_aug.mid
输入名_piano_aria.mid
输入名_piano_bytedance_pedal.mid
```

---

## 5. 构建

### 5.1 原生构建（推荐，无需 Docker）

```bash
# 首次准备构建环境
python3 -m venv .venv-p40
.venv-p40/bin/pip install torch==2.7.0 torchaudio==2.7.0 torchvision==0.22.0 \
    --index-url https://download.pytorch.org/whl/cu126
.venv-p40/bin/pip install -r piano_transcribe_p40/requirements-p40.txt \
    pyinstaller "imageio-ffmpeg>=0.6,<1" "PyQt6==6.7.1"
.venv-p40/bin/pip install --no-deps \
    "ariautils @ https://github.com/EleutherAI/aria-utils/archive/7c815755c6889a784b6a1b3343e9e8daa3e7d128.zip" \
    "aria-amt @ https://github.com/EleutherAI/aria-amt/archive/a1ab73fc901d1759ec3bc173c146b3c6a3040261.zip"

# 构建
P40_MODEL_SOURCE="/path/to/MusicToMidi-Windows-GPU-App/_internal/models" \
  ./piano_transcribe_p40/build_linux_portable.sh

# 可选：Docker 构建（Debian 11 / glibc 2.31，兼容 Ubuntu 20.04/22.04）
P40_BUILD_MODE=docker P40_MODEL_SOURCE="/path/to/models" \
  ./piano_transcribe_p40/build_linux_portable.sh

# 添加启动脚本并生成 tar.xz
./piano_transcribe_p40/package_linux_portable.sh dist-p40
```

### 5.2 本地模型来源

`v1.10.0` 目录内是 `MusicToMidi-Windows-GPU-Portable.wim.001…013` 分卷，不能直接作为模型目录。实际使用的是相邻已解包目录：

```
/media/paul/02D010A3D0109F4B/MusicToMidi-Linux-GPU-Portable/MusicToMidi-Windows-GPU-App/_internal/models
```

模型权重跨平台通用，Linux 包直接复制该目录内容。

### 5.3 Windows exe / Ubuntu 源码安装

```powershell
# Windows
.\install.ps1 -ModelSourceDir "D:\MusicToMidi-Windows-GPU-App\_internal\models"
.\build_portable.ps1
```

```bash
# Ubuntu（从本地复制模型，不重新下载）
bash install.sh --model-source-dir /path/to/models
```

`download_sota_models.py` 新增 `--model-source-dir`，安装脚本会自动透传。

---

## 6. 关键改动

| 文件 | 改动 |
|---|---|
| `src/utils/gpu_utils.py` | 新增 `is_cuda_bf16_supported`、`get_preferred_cuda_compute_dtype`；新增 `get_cuda_compatible_arches` / `is_cuda_arch_compatible`，按 NVIDIA 二进制兼容规则把 `sm_60` 视为对 `sm_61` 可用 |
| `src/models/data_models.py` | `Config.cuda_bf16_policy`（`auto` / `fp32` / `bf16`，默认 `auto`） |
| `src/core/aria_amt_transcriber.py` | CUDA KV cache dtype 遵循策略；新增受控 autocast 覆盖，保证计算 dtype 与 cache 一致；日志打印实际 dtype |
| `piano_transcribe_p40/transcribe.py` | P40 钢琴转录 CLI；`--cpu/--gpu`、`--cuda-bf16-policy`、BPM 覆盖/跳过节拍检测 |
| `piano_transcribe_p40/p40_check.py` | P40 / CUDA / 架构兼容 / BF16 / 引擎与模型可用性检查 |
| `piano_transcribe_p40/gui.py` | 钢琴专用 PyQt6 GUI；子进程调用 CLI，自身不导入 PyTorch |
| `piano_transcribe_p40/portable_entry.py` | PyInstaller 入口；无参数/`--gui` → GUI，`--p40-check` → 检查，其余 → CLI |
| `piano_transcribe_p40/PianoP40.spec` | onedir 打包配置（模型、ffmpeg、nvidia libs、PyQt6 与 Qt 插件） |
| `piano_transcribe_p40/build_linux_portable.sh` | 原生 / Docker 双模式构建 |
| `piano_transcribe_p40/_build_in_container.sh` | 容器内构建流程（可选） |
| `piano_transcribe_p40/package_linux_portable.sh` | 写入启动脚本并生成 tar.xz + sha256 |
| `piano_transcribe_p40/portable/` | 包内 `gui.sh`、`run.sh`、`p40-check.sh`、`使用说明.txt` |
| `install.sh` / `install.ps1` | 新增本地模型源参数 |
| `download_sota_models.py` | 新增 `--model-source-dir` |
| `.gitignore` | 忽略 `.venv-p40/`、`dist-p40*/` |

---

## 7. 验证记录

构建环境：PyTorch 2.7.0+cu126（CUDA 12.6），`torch.cuda.get_arch_list() = ['sm_50','sm_60','sm_70','sm_75','sm_80','sm_86','sm_90']`。测试机 GPU 为 RTX 4060 Laptop（sm_89），**未在真实 P40 上实测**。

| 验证项 | 结果 |
|---|---|
| `--p40-check` | 4 个引擎 runtime/model 全部 available；`CUDA arch compatible: True` |
| TransKun（冻结包） | 成功，28 notes |
| TransKun V2 Aug（冻结包） | 成功，28 notes |
| Aria-AMT（冻结包） | 成功，26 notes |
| ByteDance Piano（冻结包） | 成功，28 notes（含踏板） |
| MP4 输入 + `PATH` 无系统 ffmpeg | 成功，证明使用内置静态 ffmpeg |
| Beat This 自动节拍 | 40 秒音频检测 50 BPM、33 beats、16 downbeats |
| `--cuda-bf16-policy fp32` | 成功；日志 `decoder cache dtype: torch.float32` |
| 源码模式 `fp32` / `auto` | 均成功，26 notes |
| GUI 源码模式离屏渲染 | 截图成功（Qt 6.7.1） |
| GUI 源码模式端到端 | 通过 GUI 启动转写，生成 28 notes MIDI |
| 冻结包 GUI 离屏渲染 | 截图成功；Qt 插件 `libqxcb.so`/`libqoffscreen.so` 齐全，xcb 依赖全部解析 |
| 冻结包 CLI 回归 | 加 GUI 后仍正常，28 notes |

测试音频：`/tmp/opencode/p40test/piano_test.wav`（8 秒）与 `piano_beat40.wav`（40 秒）。

---

## 8. 已知限制

1. **未在真实 P40 上实测**：当前机器为 sm_89；P40 可用性基于 cu126 的 `sm_60` 二进制兼容与 CUDA 探针推断。P40 上 `p40_check` 会显示 `arch list contains sm_61: False`，但 `CUDA arch compatible: True`（预期行为）。
2. **glibc 下限**：原生包在 glibc 2.39 构建，Ubuntu 22.04（2.35）/20.04（2.31）无法运行；需要旧系统兼容时用 `P40_BUILD_MODE=docker` 构建 glibc 2.31 版本。
3. **驱动要求**：目标机 NVIDIA 驱动需 >= 560.28.03 才能提供 CUDA 12.6 运行时接口。
4. **模型来源**：依赖已解包的 Windows 便携版 `_internal/models`；仅 `.wim` 分卷时需先解包。
5. 便携包不含完整桌面应用的多乐器、人声分离、六声部分离等功能，仅提供钢琴转录 4 个引擎（GUI 为钢琴专用界面）。

---

## 9. 故障排查

| 现象 | 处理 |
|---|---|
| `no kernel image is available for execution on the device` | 运行 `./p40-check.sh`；确认 `CUDA arch compatible` 为 `True` |
| `CUDA driver version is insufficient` | 升级 NVIDIA 驱动到 560.28.03+ |
| 无 GPU / 驱动过旧 | 加 `--cpu`（较慢但可用） |
| 首次启动较慢 | 正常现象（加载/解压动态库） |
| 找不到模型 | 确认 `_internal/models/` 未被删除或移动 |
| GUI 无法启动（`could not load the Qt platform plugin "xcb"`） | 在桌面会话中运行；确认已安装 `libxcb-cursor0`（包内已带多数 xcb 库），或设置 `QT_QPA_PLATFORM=wayland` |
| 无显示服务器的机器 | 使用 `./run.sh`（CLI），GUI 需要 X11/Wayland |

---

## 10. 相关文档

- `piano_transcribe_p40/README.md`：功能、构建、使用与适配说明
- `piano_transcribe_p40/requirements-p40.txt`：P40 依赖建议
- `THIRD_PARTY_NOTICES.md`：第三方许可证与来源
