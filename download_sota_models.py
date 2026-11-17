import argparse
import os
import shutil
import sys
from pathlib import Path

from download_accompaniment_model import download_accompaniment_model
from download_aria_amt_model import download_aria_model
from download_beat_this_model import download_beat_this_model
from download_bytedance_piano_model import download_bytedance_piano_model
from download_miros_model import prepare_miros_model
from download_multistem_model import download_multistem_model
from download_muscriptor_model import download_muscriptor_model
from download_transkun_v2_aug_model import download_transkun_v2_aug_model
from download_vocal_model import download_vocal_model
from src.core.transkun_transcriber import (
    TRANSKUN_CONF_NAME,
    TRANSKUN_CONF_SHA256,
    TRANSKUN_CONF_SIZE,
    TRANSKUN_PACKAGE_NAME,
    TRANSKUN_PACKAGE_VERSION,
    TRANSKUN_WEIGHT_NAME,
    TRANSKUN_WEIGHT_SHA256,
    TRANSKUN_WEIGHT_SIZE,
    TranskunTranscriber,
)
from src.models.data_models import MuscriptorModel
from src.utils.chordmini_runtime import prepare_chordmini
from src.utils.fluidsynth_runtime import download_fluidsynth_windows
from src.utils.muscriptor_downloader import (
    preflight_muscriptor_download_access,
)
from src.utils.muscriptor_soundfont_downloader import download_muscriptor_soundfont
from src.utils.musescore_runtime import download_musescore_runtime
from src.utils.yourmt3_downloader import (
    OFFICIAL_YOURMT3_MODEL_KEYS,
    YOURMT3_MODELS,
    download_model,
    get_model_path,
)

# Historical aggregate-downloader API name.  It now resolves the Leap Instrumental
# accompaniment leg; no karaoke/chorus model is used by the current route.
download_chorus_model = download_accompaniment_model


def download_official_yourmt3_models() -> dict[str, Path]:
    """Download every official YourMT3+ mode exposed by the app UI."""
    downloaded = {}
    total = len(OFFICIAL_YOURMT3_MODEL_KEYS)

    print(f"Preparing {total} official YourMT3+ model modes...")
    for index, model_key in enumerate(OFFICIAL_YOURMT3_MODEL_KEYS, start=1):
        model_info = YOURMT3_MODELS[model_key]
        label = model_info.get("ui_label", model_key)
        checkpoint = model_info.get("checkpoint", "")
        print("")
        print(f"[{index}/{total}] {label}")
        print(f"checkpoint: {checkpoint}")

        download_model(model_key)
        model_path = get_model_path(model_key)
        if model_path is None:
            raise RuntimeError(
                f"Downloaded {label}, but no checkpoint can be resolved for '{model_key}'."
            )

        downloaded[model_key] = Path(model_path)
        print(f"ready: {model_path}")

    print("")
    print("All official YourMT3+ model modes are ready.")
    return downloaded


def validate_default_transkun_runtime() -> dict[str, object]:
    """Require the exact TransKun package and packaged V2 resource identities."""
    unavailable_reason = TranskunTranscriber.get_unavailable_reason()
    if unavailable_reason:
        raise RuntimeError(
            f"Default TransKun {TRANSKUN_PACKAGE_VERSION} runtime validation failed: "
            f"{unavailable_reason}"
        )

    transcriber = TranskunTranscriber()
    if not transcriber.is_model_available():
        raise RuntimeError(
            f"Default TransKun {TRANSKUN_PACKAGE_VERSION} packaged resources are "
            "missing or failed exact identity validation: "
            f"{TRANSKUN_WEIGHT_NAME} expected {TRANSKUN_WEIGHT_SIZE} bytes / "
            f"SHA-256 {TRANSKUN_WEIGHT_SHA256}; "
            f"{TRANSKUN_CONF_NAME} expected {TRANSKUN_CONF_SIZE} bytes / "
            f"SHA-256 {TRANSKUN_CONF_SHA256}."
        )

    return {
        "package": TRANSKUN_PACKAGE_NAME,
        "version": TRANSKUN_PACKAGE_VERSION,
        "weight_name": TRANSKUN_WEIGHT_NAME,
        "weight_size": TRANSKUN_WEIGHT_SIZE,
        "weight_sha256": TRANSKUN_WEIGHT_SHA256,
        "config_name": TRANSKUN_CONF_NAME,
        "config_size": TRANSKUN_CONF_SIZE,
        "config_sha256": TRANSKUN_CONF_SHA256,
    }


def _copy_tree(src: Path, dst: Path, label: str) -> bool:
    if not src.exists():
        return False
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                if target.exists() and target.is_file():
                    target.unlink()
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"copied local {label}: {src} -> {dst}")
    return True


def copy_models_from_source(source_dir: str | Path) -> Path:
    source = Path(source_dir).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Model source directory not found: {source}")
    home = Path.home()
    cache_root = home / ".cache" / "music_ai_models"
    music_models = home / ".music-to-midi" / "models"
    repo = Path(__file__).resolve().parent

    mappings = [
        (["aria_amt"], cache_root / "aria_amt", "Aria-AMT"),
        (["bytedance_piano"], cache_root / "bytedance_piano", "ByteDance Piano"),
        (["transkun_v2_aug"], cache_root / "transkun_v2_aug", "TransKun V2 Aug"),
        (["yourmt3_all", "yourmt3"], cache_root / "yourmt3_all", "YourMT3+"),
        (["audio-separator", "audio_separator"], music_models / "audio-separator", "audio-separator models"),
        (["beat_this"], music_models / "beat_this", "Beat This"),
        (["chordmini"], music_models / "chordmini", "ChordMini"),
        (["muscriptor_small"], repo / "models" / "muscriptor_small", "MuScriptor-small"),
        (["muscriptor_medium"], repo / "models" / "muscriptor_medium", "MuScriptor-medium"),
        (["muscriptor_large"], repo / "models" / "muscriptor_large", "MuScriptor-large"),
        (["muscriptor_assets"], repo / "models" / "muscriptor_assets", "MuScriptor assets"),
    ]
    for names, dst, label in mappings:
        for name in names:
            src = source / name
            if src.exists():
                _copy_tree(src, dst, label)
                break

    for name in ["ai4m-miros", "miros", "MIROS"]:
        src = source / name
        if src.exists():
            _copy_tree(src, repo / "external" / "ai4m-miros", "MIROS source/weights")
            _copy_tree(src, repo / "ai4m-miros", "MIROS source/weights (root)")
            break

    for name in ["fluidsynth", "musescore"]:
        src = source / name
        if src.exists():
            _copy_tree(src, repo / "tools" / name, name)

    print(f"Local model copy completed from: {source}")
    return source


def _muscriptor_assets_locally_ready() -> bool:
    try:
        from src.utils.muscriptor_downloader import get_cached_muscriptor_paths
        from src.utils.muscriptor_soundfont_downloader import is_muscriptor_soundfont_available
        for model_size in MuscriptorModel:
            get_cached_muscriptor_paths(model_size, validate_hashes=True)
        return bool(is_muscriptor_soundfont_available())
    except Exception:
        return False


def download_sota_models(model_source_dir: str | Path | None = None) -> dict[str, object]:
    """Prepare the full SOTA model set used by the app's public workflows."""
    if model_source_dir:
        copy_models_from_source(model_source_dir)

    if model_source_dir and _muscriptor_assets_locally_ready():
        print("Local MuScriptor checkpoints/assets detected; skipping gated Hugging Face preflight.")
    else:
        print("Preflighting all gated MuScriptor checkpoint permissions...")
        preflight_muscriptor_download_access()
        print("All gated MuScriptor checkpoint permissions are ready.")
    print("")

    print("Preparing exact TransKun 2.0.1 package and built-in V2 resources...")
    transkun_runtime = validate_default_transkun_runtime()
    print(
        "ready: "
        f"{transkun_runtime['package']}=={transkun_runtime['version']} "
        f"({transkun_runtime['weight_name']}, {transkun_runtime['config_name']})"
    )

    print("")
    print("Preparing exact Beat This final0 beat/downbeat checkpoint...")
    beat_this_checkpoint = download_beat_this_model()
    print(f"ready: {beat_this_checkpoint}")

    print("")
    yourmt3_models = download_official_yourmt3_models()

    print("")
    print("Preparing pinned MIROS source plus finetuned and pretrained weights...")
    miros_repo = prepare_miros_model()
    print(f"ready: {miros_repo}")

    print("")
    print("Preparing BS-RoFormer SW Fixed six-stem separation assets...")
    six_stem_model, six_stem_config = download_multistem_model()
    print(f"ready: {six_stem_model}")
    print(f"ready: {six_stem_config}")

    print("")
    print("Preparing BS-RoFormer Leap XE 90-band vocals assets...")
    vocal_model = download_vocal_model()
    print(f"ready: {vocal_model}")

    print("")
    print("Preparing pinned Leap Instrumental accompaniment assets...")
    accompaniment_model = download_chorus_model()
    print(f"ready: {accompaniment_model}")

    print("")
    print("Preparing official TransKun V2 Aug checkpoint assets...")
    transkun_v2_aug_dir = download_transkun_v2_aug_model()
    print(f"ready: {transkun_v2_aug_dir}")

    print("")
    print("Preparing exact Aria-AMT checkpoint assets...")
    aria_checkpoint = download_aria_model()
    print(f"ready: {aria_checkpoint}")

    print("")
    print("Preparing exact ByteDance pedal-aware piano checkpoint assets...")
    bytedance_checkpoint = download_bytedance_piano_model()
    print(f"ready: {bytedance_checkpoint}")

    print("\nPreparing all gated MuScriptor checkpoints...")
    muscriptor_models = {}
    for model_size in MuscriptorModel:
        muscriptor_weights, muscriptor_config = download_muscriptor_model(model_size)
        muscriptor_models[model_size.value] = {
            "weights": muscriptor_weights,
            "config": muscriptor_config,
        }
        print(f"ready ({model_size.value}): {muscriptor_weights}")

    print("\nPreparing MuScriptor official playback SoundFont...")
    muscriptor_soundfont = download_muscriptor_soundfont()
    print(f"ready: {muscriptor_soundfont}")

    print("\nPreparing pinned ChordMini BTC chord analysis...")
    chordmini_runtime = prepare_chordmini()
    print(f"ready: {chordmini_runtime}")

    print("\nVerifying the real FluidSynth playback runtime...")
    fluidsynth_executable = download_fluidsynth_windows()
    print(f"ready: {fluidsynth_executable}")

    print("\nPreparing pinned MuseScore Studio 4 sheet-music runtime...")
    musescore_executable = download_musescore_runtime()
    print(f"ready: {musescore_executable}")

    return {
        "chordmini": {"runtime": chordmini_runtime},
        "transkun": transkun_runtime,
        "beat_this": {
            "checkpoint": beat_this_checkpoint,
        },
        "yourmt3": yourmt3_models,
        "miros": {
            "repo_dir": miros_repo,
        },
        "six_stem": {
            "model": six_stem_model,
            "config": six_stem_config,
        },
        "vocal_leap_xe": {
            "primary_model": vocal_model,
        },
        "accompaniment_leap_instrumental": {
            "primary_model": accompaniment_model,
        },
        "transkun_v2_aug": {
            "model_dir": transkun_v2_aug_dir,
        },
        "aria_amt": {
            "checkpoint": aria_checkpoint,
        },
        "bytedance_piano": {
            "checkpoint": bytedance_checkpoint,
        },
        "muscriptor": {
            "models": muscriptor_models,
            # Backward-compatible aliases for callers that still consume the
            # original Large-only aggregate result.
            "weights": muscriptor_models[MuscriptorModel.LARGE.value]["weights"],
            "config": muscriptor_models[MuscriptorModel.LARGE.value]["config"],
            "soundfont": muscriptor_soundfont,
            "fluidsynth": fluidsynth_executable,
            "musescore": musescore_executable,
        },
        # Deprecated compatibility keys retained for aggregate-downloader callers.
        "vocal_rvc": {
            "primary_model": vocal_model,
        },
        "karaoke": {
            "primary_model": accompaniment_model,
        },
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download/copy and validate SOTA models")
    parser.add_argument(
        "--model-source-dir",
        default=None,
        help="Copy model files from this local directory instead of downloading when possible.",
    )
    args = parser.parse_args(argv)
    download_sota_models(model_source_dir=args.model_source_dir)


if __name__ == "__main__":
    main()
