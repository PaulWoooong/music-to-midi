#!/usr/bin/env python3
"""NVIDIA P40 (Pascal, sm_61) compatibility check for piano transcription."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _print(title: str, value) -> None:
    print(f"{title}: {value}")


def main() -> int:
    print("=== Piano Transcription P40 / sm_61 Check ===")
    _print("Python", sys.version.replace("\n", " "))
    _print("Platform", platform.platform())
    _print("Repo root", REPO_ROOT)
    _print("ffmpeg on PATH", shutil.which("ffmpeg") or "(not found)")

    # Torch / CUDA
    try:
        import torch

        _print("torch", torch.__version__)
        _print("torch.version.cuda", getattr(torch.version, "cuda", None))
        cuda_available = torch.cuda.is_available()
        _print("torch.cuda.is_available", cuda_available)
        if cuda_available:
            count = torch.cuda.device_count()
            _print("cuda device_count", count)
            try:
                arch_list = list(torch.cuda.get_arch_list())
            except Exception as exc:
                arch_list = [f"<error: {exc}>"]
            _print("torch.cuda.get_arch_list", arch_list)
            has_sm61 = any("sm_61" in str(a) or "compute_61" in str(a) for a in arch_list)
            _print("arch list contains sm_61", has_sm61)
            try:
                from src.utils.gpu_utils import get_cuda_compatible_arches, is_cuda_arch_compatible
            except Exception as exc:
                get_cuda_compatible_arches = None
                is_cuda_arch_compatible = None
                _print("arch compatibility helper", f"unavailable: {exc}")
            for i in range(count):
                props = torch.cuda.get_device_properties(i)
                cc = f"sm_{props.major}{props.minor}"
                _print(f"GPU[{i}] name", props.name)
                _print(f"GPU[{i}] compute capability", f"{props.major}.{props.minor} ({cc})")
                _print(f"GPU[{i}] total memory GiB", round(props.total_memory / (1024**3), 2))
                bf16_supported = False
                try:
                    checker = getattr(torch.cuda, "is_bf16_supported", None)
                    bf16_supported = bool(checker()) if callable(checker) else False
                except Exception:
                    bf16_supported = False
                _print(f"GPU[{i}] BF16 supported", bf16_supported)
                if get_cuda_compatible_arches is not None:
                    compatible = get_cuda_compatible_arches(f"cuda:{i}", arch_list)
                    arch_ok = is_cuda_arch_compatible(f"cuda:{i}", arch_list)
                    _print(f"GPU[{i}] usable arch entries", compatible or "none")
                    _print(f"GPU[{i}] CUDA arch compatible", arch_ok)
                else:
                    arch_ok = None
                if props.major == 6 and props.minor == 1:
                    print(
                        "  -> Detected Pascal sm_61 (P40/GP102 class). "
                        "BF16/Tensor Cores are not available on this architecture."
                    )
                    print(
                        "  -> BF16 CUDA ops use FP32 fallback on P40 (cuda_bf16_policy=auto/fp32). "
                        "Newer BF16-capable NVIDIA GPUs remain compatible with auto/bf16 policy."
                    )
                    if arch_ok is False:
                        print(
                            "  [WARN] No torch arch entry can run on sm_61. "
                            "GPU kernels may fail with: no kernel image is available for execution on the device."
                        )
                    elif arch_ok:
                        print(
                            "  -> torch arch list contains a binary-compatible entry "
                            "(sm_60 SASS or <= compute_61 PTX); P40 GPU execution is supported."
                        )
                elif not bf16_supported:
                    print(
                        f"  -> GPU[{i}] does not support BF16 CUDA ops; auto policy will fall back to FP32."
                    )
            # Probe op (may fail on incompatible arch)
            try:
                x = torch.zeros(1, device="cuda:0")
                x = x + 1
                torch.cuda.synchronize(0)
                _print("CUDA probe (small tensor op)", "OK")
            except Exception as exc:
                _print("CUDA probe (small tensor op)", f"FAILED: {exc}")
        else:
            print("CUDA not available. Use --cpu for transcription, or install a CUDA-enabled PyTorch.")
    except Exception as exc:
        _print("torch import", f"FAILED: {exc}")

    # Project-specific checks
    print("\n--- Project module checks (run from repo root) ---")
    try:
        from src.utils.gpu_utils import diagnose_gpu, get_accelerator_label

        _print("accelerator", get_accelerator_label())
        diag = diagnose_gpu()
        print(json.dumps({k: v for k, v in diag.items() if not k.startswith("tf_")}, ensure_ascii=False, indent=2))
    except Exception as exc:
        _print("src.utils.gpu_utils", f"FAILED: {exc}")

    for mod, label in [
        ("src.core.transkun_transcriber.TranskunTranscriber", "TransKun"),
        ("src.core.transkun_v2_aug_transcriber.TranskunV2AugTranscriber", "TransKun V2 Aug"),
        ("src.core.aria_amt_transcriber.AriaAmtTranscriber", "Aria-AMT"),
        ("src.core.bytedance_piano_transcriber.ByteDancePianoTranscriber", "ByteDance Piano"),
    ]:
        module_name, cls_name = mod.rsplit(".", 1)
        try:
            module = __import__(module_name, fromlist=[cls_name])
            cls = getattr(module, cls_name)
            available = cls.is_available()
            _print(f"{label} package/runtime available", available)
            if hasattr(cls, "get_unavailable_reason") and not available:
                _print(f"{label} unavailable reason", cls.get_unavailable_reason())
            # Model availability if instantiable
            try:
                inst = cls()
                if hasattr(inst, "is_model_available"):
                    _print(f"{label} model available", inst.is_model_available())
            except Exception as exc:
                _print(f"{label} model check", f"skipped/error: {exc}")
        except Exception as exc:
            _print(label, f"import/check failed: {exc}")

    print("\n=== Done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
