#!/usr/bin/env python3
"""Extracted piano transcription CLI, adapted for NVIDIA P40 (sm_61) workflows.

Run from the repository root:
  python piano_transcribe_p40/transcribe.py INPUT_AUDIO -o OUTPUT_DIR -e transkun
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.models.data_models import BeatInfo, Config, ProcessingMode  # noqa: E402
from src.utils.gpu_utils import clear_gpu_memory, get_accelerator_type, is_gpu_available  # noqa: E402
from src.utils.runtime_paths import get_ffmpeg_executable  # noqa: E402

ENGINES = {
    "transkun": {
        "mode": ProcessingMode.PIANO_TRANSKUN.value,
        "label": "TransKun",
        "suffix": "piano_transkun",
        "module": "src.core.transkun_transcriber",
        "class": "TranskunTranscriber",
    },
    "transkun_v2_aug": {
        "mode": ProcessingMode.PIANO_TRANSKUN_V2_AUG.value,
        "label": "TransKun V2 Aug",
        "suffix": "piano_transkun_v2_aug",
        "module": "src.core.transkun_v2_aug_transcriber",
        "class": "TranskunV2AugTranscriber",
    },
    "aria_amt": {
        "mode": ProcessingMode.PIANO_ARIA_AMT.value,
        "label": "Aria-AMT",
        "suffix": "piano_aria",
        "module": "src.core.aria_amt_transcriber",
        "class": "AriaAmtTranscriber",
    },
    "bytedance_pedal": {
        "mode": ProcessingMode.PIANO_BYTEDANCE_PEDAL.value,
        "label": "ByteDance Piano",
        "suffix": "piano_bytedance_pedal",
        "module": "src.core.bytedance_piano_transcriber",
        "class": "ByteDancePianoTranscriber",
    },
}


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def ensure_wav(audio_path: Path, output_dir: Path) -> Path:
    audio_path = audio_path.resolve()
    if audio_path.suffix.lower() == ".wav":
        return audio_path
    output_dir.mkdir(parents=True, exist_ok=True)
    wav_path = output_dir / f"{audio_path.stem}.wav"
    ffmpeg = get_ffmpeg_executable()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(audio_path),
        "-ar",
        "44100",
        "-ac",
        "2",
        "-sample_fmt",
        "s16",
        str(wav_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffmpeg not found ({ffmpeg}); cannot convert non-WAV input.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg conversion failed: {exc.stderr or exc}") from exc
    if not wav_path.is_file() or wav_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg did not produce a valid WAV: {wav_path}")
    return wav_path


def detect_beat(audio_path: Path, config: Config, bpm_override: Optional[float], skip: bool) -> BeatInfo:
    if bpm_override is not None:
        bpm = float(bpm_override)
        return BeatInfo(bpm=bpm, beat_times=[], downbeats=None, time_signature=None, tempo_map=[], source_bpm=None)
    if skip:
        return BeatInfo(bpm=120.0, beat_times=[], downbeats=None, time_signature=None, tempo_map=[], source_bpm=None)
    try:
        from src.core.beat_detector import BeatDetector

        detector = BeatDetector(config)
        return detector.detect(str(audio_path))
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Beat detection unavailable (%s); falling back to 120 BPM. Use --bpm or --skip-beat-detect to control this.",
            exc,
        )
        return BeatInfo(bpm=120.0, beat_times=[], downbeats=None, time_signature=None, tempo_map=[], source_bpm=None)


def normalize_tempo(midi_path: str, beat_info: BeatInfo) -> str:
    from src.core.midi_tempo import rewrite_midi_tempo_preserving_seconds, write_midi_time_signature_preserving_ticks

    tempo = float(beat_info.bpm)
    if beat_info.source_bpm is not None and beat_info.source_bpm != tempo:
        from src.core.midi_tempo import rewrite_midi_tempo_for_project_speed

        rewrite_midi_tempo_for_project_speed(Path(midi_path), Path(midi_path), float(beat_info.source_bpm), tempo)
    else:
        rewrite_midi_tempo_preserving_seconds(Path(midi_path), Path(midi_path), tempo)
    write_midi_time_signature_preserving_ticks(
        Path(midi_path), Path(midi_path), beat_info.time_signature, label="P40 piano CLI"
    )
    return midi_path


def build_transcriber(engine: str, config: Config):
    spec = ENGINES[engine]
    module = __import__(spec["module"], fromlist=[spec["class"]])
    cls = getattr(module, spec["class"])
    # Aria-AMT takes (checkpoint_path, language, config) in this project; others take (config)
    if engine == "aria_amt":
        return cls(language=getattr(config, "language", "en_US"), config=config)
    return cls(config=config)


def check_availability(engine: str, transcriber) -> Tuple[bool, str]:
    if not transcriber.is_available():
        reason = ""
        if hasattr(transcriber, "get_unavailable_reason"):
            reason = transcriber.get_unavailable_reason()
        elif hasattr(type(transcriber), "get_unavailable_reason"):
            reason = type(transcriber).get_unavailable_reason()
        return False, reason or f"{ENGINES[engine]['label']} runtime is unavailable."
    if hasattr(transcriber, "is_model_available") and not transcriber.is_model_available():
        hints = {
            "aria_amt": "Run: python download_aria_amt_model.py",
            "bytedance_pedal": "Run: python download_bytedance_piano_model.py",
            "transkun_v2_aug": "Run: python download_transkun_v2_aug_model.py",
            "transkun": "Reinstall: python -m pip install --force-reinstall transkun==2.0.1",
        }
        return False, f"{ENGINES[engine]['label']} model/checkpoint not available. {hints.get(engine, '')}"
    return True, ""


def p40_preflight(use_gpu: bool) -> None:
    if not use_gpu:
        return
    try:
        import torch

        if not torch.cuda.is_available():
            return
        from src.utils.gpu_utils import get_cuda_compatible_arches, is_cuda_arch_compatible

        props = torch.cuda.get_device_properties(0)
        arch_list = []
        try:
            arch_list = list(torch.cuda.get_arch_list())
        except Exception:
            pass
        if props.major == 6 and props.minor == 1:
            arch_ok = is_cuda_arch_compatible("cuda:0", arch_list)
            if arch_ok is False:
                logging.getLogger(__name__).warning(
                    "Detected %s (sm_61/P40 class) but no PyTorch arch entry can run on it: %s. "
                    "GPU execution may fail; consider --cpu or an sm_61-compatible PyTorch build.",
                    props.name,
                    arch_list,
                )
            elif arch_ok:
                compatible = get_cuda_compatible_arches("cuda:0", arch_list)
                logging.getLogger(__name__).info(
                    "P40/sm_61 compatibility confirmed via %s (from torch arch list %s).",
                    compatible,
                    arch_list,
                )
    except Exception:
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Piano transcription CLI (P40/sm_61 adapted)")
    parser.add_argument("input", type=Path, help="Input audio file")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("output_piano_p40"), help="Output directory")
    parser.add_argument(
        "-e",
        "--engine",
        choices=list(ENGINES.keys()),
        default="transkun",
        help="Piano transcription engine",
    )
    parser.add_argument("--cpu", action="store_true", help="Force CPU")
    parser.add_argument("--gpu", dest="gpu", action="store_true", help="Use GPU if available (default)")
    parser.add_argument("--no-gpu", dest="gpu", action="store_false")
    parser.set_defaults(gpu=True)
    parser.add_argument("--gpu-device", type=int, default=0, help="CUDA/XPU device index")
    parser.add_argument("--bpm", type=float, default=None, help="Override tempo BPM (skips beat detection)")
    parser.add_argument("--skip-beat-detect", action="store_true", help="Skip beat detection and use 120 BPM (or --bpm)")
    parser.add_argument(
        "--cuda-bf16-policy",
        choices=["auto", "fp32", "bf16"],
        default="auto",
        help="BF16 CUDA compute policy: auto=use BF16 only when supported (P40/sm_61 falls back to FP32), fp32=always FP32, bf16=BF16 when supported else FP32",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    log = logging.getLogger("piano_p40")

    if not args.input.is_file():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 2

    use_gpu = bool(args.gpu and not args.cpu)
    p40_preflight(use_gpu)

    config = Config()
    config.use_gpu = use_gpu
    config.gpu_device = args.gpu_device
    config.cuda_bf16_policy = args.cuda_bf16_policy
    config.processing_mode = ENGINES[args.engine]["mode"]
    config.language = "en_US"

    log.info(
        "Engine=%s GPU=%s accelerator=%s cuda_bf16_policy=%s",
        args.engine,
        use_gpu,
        get_accelerator_type() if use_gpu else "cpu",
        config.cuda_bf16_policy,
    )

    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        wav_path = ensure_wav(args.input, args.output_dir)

        beat_info = detect_beat(wav_path, config, args.bpm, args.skip_beat_detect)
        log.info("Tempo: %.3f BPM (source=%s)", beat_info.bpm, beat_info.source_bpm)

        transcriber = build_transcriber(args.engine, config)
        ok, reason = check_availability(args.engine, transcriber)
        if not ok:
            print(f"Engine not ready: {reason}", file=sys.stderr)
            return 3

        stem = args.input.stem
        midi_path = args.output_dir / f"{stem}_{ENGINES[args.engine]['suffix']}.mid"

        def progress(p: float, msg: str) -> None:
            pct = max(0.0, min(1.0, float(p))) * 100
            print(f"[{pct:5.1f}%] {msg}")

        start = time.time()
        out = transcriber.transcribe(str(wav_path), str(midi_path), progress_callback=progress)
        out = normalize_tempo(out, beat_info)
        elapsed = time.time() - start

        # Note count (best effort)
        note_count = "?"
        try:
            import mido

            mf = mido.MidiFile(out)
            note_count = sum(
                1 for tr in mf.tracks for m in tr if not m.is_meta and m.type == "note_on" and m.velocity > 0
            )
        except Exception:
            pass

        print(f"Done: {out}")
        print(f"Notes: {note_count} | Time: {elapsed:.1f}s | Tempo: {beat_info.bpm:.3f} BPM")
        return 0
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        log.exception("Transcription failed")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            clear_gpu_memory()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
