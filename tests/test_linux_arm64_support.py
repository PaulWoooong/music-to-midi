"""Linux arm64 (aarch64) source-install contract.

The project keeps its x86-64 defaults while selecting arm64-compatible
replacements for packages that have no official aarch64 wheel at the pinned
x86-64 version.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _install_sh() -> str:
    return (REPO_ROOT / "install.sh").read_text(encoding="utf-8")


def test_installer_detects_and_normalizes_supported_architectures():
    script = _install_sh()

    assert 'HOST_ARCH="$(uname -m)"' in script
    assert "x86_64|amd64" in script
    assert "aarch64|arm64" in script
    assert "不支持的 CPU 架构" in script


def test_installer_uses_arm64_onnxruntime_and_filters_the_x86_pin():
    script = _install_sh()

    assert 'ORT_GPU_REQUIREMENT="onnxruntime-gpu==1.31.1"' in script
    assert 'ORT_GPU_REQUIREMENT="onnxruntime-gpu==1.23.2"' in script
    assert "grep -vE '^[[:space:]]*onnxruntime-gpu" in script
    assert '"$ORT_GPU_REQUIREMENT"' in script


def test_installer_builds_upstream_diffq_on_arm64():
    script = _install_sh()

    assert 'DIFFQ_REQUIREMENT="diffq==0.2.4"' in script
    assert 'DIFFQ_REQUIREMENT="diffq-fixed==0.2.4"' in script
    assert '"$DIFFQ_REQUIREMENT"' in script


def test_installer_installs_native_build_and_resample_runtime_dependencies():
    script = _install_sh()

    assert "libsamplerate0" in script
    assert "build-essential" in script


def test_installer_keeps_the_cuda_128_contract_on_both_architectures():
    script = _install_sh()

    assert "https://download.pytorch.org/whl/cu128" in script
    assert "torch.version.cuda" in script
    assert '"CUDAExecutionProvider" not in providers' in script
    assert "python3.12" in script and "python3.11" in script


def test_arm64_cuda_bundle_replaces_torch_nvrtc_for_sm121():
    spec = (REPO_ROOT / "MusicToMidi.spec").read_text(encoding="utf-8")

    assert "from tools.nvrtc_arch_override import apply_override" in spec
    assert 'in {"aarch64", "arm64"}' in spec
    assert "not IS_XPU" in spec


def test_installer_applies_the_nvrtc_override_to_the_source_venv():
    script = _install_sh()

    assert "tools/nvrtc_arch_override.py" in script
    assert '"$VENV_DIR"' in script


def test_frozen_linux_bundle_compiles_inductor_workers_in_process():
    main_py = (REPO_ROOT / "src/main.py").read_text(encoding="utf-8")

    assert 'getattr(sys, "frozen", False) and sys.platform.startswith("linux")' in main_py
    assert '"TORCHINDUCTOR_COMPILE_THREADS", "1"' in main_py


def test_gui_runtime_self_test_exercises_a_runtime_compiled_cuda_kernel():
    main_py = (REPO_ROOT / "src/main.py").read_text(encoding="utf-8")

    assert "dtype=torch.complex64" in main_py
    assert "NVRTC" in main_py


def test_accelerator_validator_matches_the_arm64_onnxruntime_pin(monkeypatch):
    import tools.validate_accelerator_runtime as validator

    monkeypatch.setattr(validator.sys, "platform", "linux")
    monkeypatch.setattr(validator.platform, "machine", lambda: "aarch64")
    assert validator._cuda_onnxruntime_version() == "1.31.1"

    monkeypatch.setattr(validator.platform, "machine", lambda: "x86_64")
    assert validator._cuda_onnxruntime_version() == "1.23.2"

    # Windows remains x86_64-only for packaged CUDA builds.
    monkeypatch.setattr(validator.sys, "platform", "win32")
    monkeypatch.setattr(validator.platform, "machine", lambda: "ARM64")
    assert validator._cuda_onnxruntime_version() == "1.23.2"


def test_accelerator_validator_accepts_untagged_arm64_cuda_wheels(monkeypatch):
    import tools.validate_accelerator_runtime as validator

    versions = {
        "torch": "2.7.0+cu128",
        "torchaudio": "2.7.0",
        "torchvision": "0.22.0",
    }

    monkeypatch.setattr(validator.sys, "platform", "linux")
    monkeypatch.setattr(validator.platform, "machine", lambda: "aarch64")
    assert validator._cuda_flavor_mismatches(versions) == {}

    # x86_64 wheels are tagged, so an untagged pair is still rejected there.
    monkeypatch.setattr(validator.platform, "machine", lambda: "x86_64")
    assert validator._cuda_flavor_mismatches(versions) == {
        "torchaudio": "2.7.0",
        "torchvision": "0.22.0",
    }
