"""Copy pre-downloaded model assets from a local cache mirror and verify offline.

The Linux installer never downloads model weights. It copies them from a local
directory that mirrors the runtime cache layout, for example::

    <source>/
      music_ai_models/
        aria_amt/
        bytedance_piano/
        yourmt3_all/
        transkun_v2_aug/
        chordmini/
        musescore/              # optional MuseScore runtime cache
        fluidsynth/             # optional Windows FluidSynth cache
      music-to-midi/
        models/
          audio-separator/
          beat_this/
      huggingface/
        hub/
          models--MuScriptor--muscriptor-large/
          models--MuScriptor--muscriptor-medium/
          models--MuScriptor--muscriptor-small/
          models--MuScriptor--assets/
      ai4m-miros/
      yourmt3/                  # optional YourMT3 metadata/temp cache

The source layout is checked before the first byte is copied, and the copied
assets are then strictly validated with their pinned identities. The helper
never contacts the network: a missing or invalid local asset stops the
installation with an actionable error.
"""

from __future__ import annotations

import argparse
import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parent
MODELS_SOURCE_ENV = "MUSIC_TO_MIDI_MODELS_SOURCE"
MIROS_DIR_ENV = "MUSIC_TO_MIDI_MIROS_DIR"

MUSIC_AI_MODELS_REQUIRED = (
    "aria_amt",
    "bytedance_piano",
    "yourmt3_all",
    "transkun_v2_aug",
    "chordmini",
)
MUSIC_TO_MIDI_REQUIRED = (
    "models/audio-separator",
    "models/beat_this",
)
HF_MUSCRIPTOR_REPOS = (
    "models--MuScriptor--muscriptor-large",
    "models--MuScriptor--muscriptor-medium",
    "models--MuScriptor--muscriptor-small",
    "models--MuScriptor--assets",
)
MIROS_REQUIRED = ("main.py", "transcribe.py")


class LocalModelError(RuntimeError):
    """Raised when the local model mirror is missing or invalid."""


@dataclass(frozen=True)
class MirrorCopy:
    """One merge copy from the local mirror into a runtime cache location."""

    label: str
    source: Path
    destination: Path
    children: tuple[str, ...] = ()


def resolve_source_root(source: str | Path | None = None) -> Path:
    """Resolve the local mirror root, defaulting to ``$MUSIC_TO_MIDI_MODELS_SOURCE``."""

    if source is None:
        source = os.environ.get(MODELS_SOURCE_ENV, "").strip() or "~/models"
    path = Path(source).expanduser()
    if not path.is_dir():
        raise LocalModelError(
            f"本地模型目录不存在：{path}\n"
            f"请先将模型按缓存镜像结构放入该目录，或设置 {MODELS_SOURCE_ENV} 指向正确的目录。"
        )
    return path.resolve()


def _first_directory(root: Path, candidates: Iterable[str]) -> Path | None:
    for relative in candidates:
        candidate = root / relative
        if candidate.is_dir():
            return candidate
    return None


def _missing_entries(base: Path, entries: Iterable[str]) -> list[Path]:
    return [base / relative for relative in entries if not (base / relative).exists()]


def _resolve_mirror(
    source_root: Path,
    candidates: tuple[str, ...],
    label: str,
    *,
    required: bool,
    errors: list[str],
) -> Path | None:
    resolved = _first_directory(source_root, candidates)
    if resolved is not None:
        return resolved
    if required:
        expected = " / ".join(str(source_root / relative) for relative in candidates)
        errors.append(f"{label}: 缺少目录（支持位置：{expected}）")
    return None


def _require_entries(
    base: Path,
    entries: Iterable[str],
    label: str,
    errors: list[str],
) -> None:
    missing = _missing_entries(base, entries)
    if missing:
        detail = "\n".join(f"  - {path}" for path in missing)
        errors.append(f"{label}: 缺少必需内容：\n{detail}")


def _default_hf_home(cache_home: Path) -> Path:
    configured = os.environ.get("HF_HOME", "").strip()
    return Path(configured).expanduser() if configured else cache_home / "huggingface"


def _default_hf_hub_cache(hf_home: Path) -> Path:
    configured = os.environ.get("HF_HUB_CACHE", "").strip()
    return Path(configured).expanduser() if configured else hf_home / "hub"


def _default_miros_dir(repo_dir: Path) -> Path:
    configured = os.environ.get(MIROS_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return repo_dir / "external" / "ai4m-miros"


def build_copy_plan(
    source_root: Path,
    *,
    cache_home: Path | None = None,
    runtime_data_dir: Path | None = None,
    repo_dir: Path | None = None,
) -> dict[str, object]:
    """Validate the source mirror and return the destination paths used."""

    source_root = Path(source_root).expanduser().resolve()
    cache_home = Path(cache_home).expanduser() if cache_home is not None else Path.home() / ".cache"
    runtime_data_dir = (
        Path(runtime_data_dir).expanduser()
        if runtime_data_dir is not None
        else Path.home() / ".music-to-midi"
    )
    repo_dir = Path(repo_dir).expanduser() if repo_dir is not None else REPO_ROOT
    hf_home = _default_hf_home(cache_home)
    hf_hub_cache = _default_hf_hub_cache(hf_home)
    miros_destination = _default_miros_dir(repo_dir)

    errors: list[str] = []
    copies: list[MirrorCopy] = []

    music_ai_models = _resolve_mirror(
        source_root,
        ("music_ai_models", ".cache/music_ai_models", "cache/music_ai_models"),
        "music_ai_models",
        required=True,
        errors=errors,
    )
    if music_ai_models is not None:
        _require_entries(music_ai_models, MUSIC_AI_MODELS_REQUIRED, "music_ai_models", errors)
        copies.append(
            MirrorCopy(
                label="music_ai_models",
                source=music_ai_models,
                destination=cache_home / "music_ai_models",
            )
        )

    yourmt3_cache = _resolve_mirror(
        source_root,
        ("yourmt3", ".cache/yourmt3", "cache/yourmt3"),
        "yourmt3",
        required=False,
        errors=errors,
    )
    if yourmt3_cache is not None:
        copies.append(
            MirrorCopy(
                label="yourmt3",
                source=yourmt3_cache,
                destination=cache_home / "yourmt3",
            )
        )

    app_data = _resolve_mirror(
        source_root,
        ("music-to-midi", ".music-to-midi"),
        "music-to-midi",
        required=True,
        errors=errors,
    )
    if app_data is not None:
        _require_entries(app_data, MUSIC_TO_MIDI_REQUIRED, "music-to-midi", errors)
        copies.append(
            MirrorCopy(
                label="music-to-midi",
                source=app_data,
                destination=runtime_data_dir,
                children=("models",),
            )
        )

    huggingface = _resolve_mirror(
        source_root,
        ("huggingface", ".cache/huggingface", "cache/huggingface"),
        "huggingface",
        required=True,
        errors=errors,
    )
    if huggingface is not None:
        hub_dir = huggingface / "hub"
        if not hub_dir.is_dir():
            hub_dir = huggingface
        _require_entries(hub_dir, HF_MUSCRIPTOR_REPOS, "huggingface/hub", errors)
        copies.append(
            MirrorCopy(
                label="huggingface",
                source=hub_dir,
                destination=hf_hub_cache,
                children=HF_MUSCRIPTOR_REPOS,
            )
        )

    miros_source = _resolve_mirror(
        source_root,
        ("ai4m-miros", "external/ai4m-miros", "miros"),
        "ai4m-miros",
        required=True,
        errors=errors,
    )
    if miros_source is not None:
        _require_entries(miros_source, MIROS_REQUIRED, "ai4m-miros", errors)
        copies.append(
            MirrorCopy(
                label="ai4m-miros",
                source=miros_source,
                destination=miros_destination,
            )
        )

    if errors:
        raise LocalModelError(
            "本地模型目录内容不完整，安装已停止（不会改为联网下载）：\n\n"
            + "\n\n".join(errors)
            + f"\n\n来源目录：{source_root}"
        )

    return {
        "source_root": source_root,
        "cache_home": cache_home,
        "runtime_data_dir": runtime_data_dir,
        "hf_home": hf_home,
        "hf_hub_cache": hf_hub_cache,
        "miros_dir": miros_destination,
        "copies": copies,
    }


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _copy_tree(source: Path, destination: Path, *, printer: Callable[[str], None]) -> None:
    if _same_path(source, destination):
        printer(f"  已是最新位置，跳过：{destination}")
        return
    printer(f"  复制 {source} -> {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)


def copy_local_models(
    source: str | Path | None = None,
    *,
    cache_home: Path | None = None,
    runtime_data_dir: Path | None = None,
    repo_dir: Path | None = None,
    printer: Callable[[str], None] = print,
) -> dict[str, object]:
    """Merge the local mirror into runtime caches without deleting other files."""

    source_root = resolve_source_root(source)
    plan = build_copy_plan(
        source_root,
        cache_home=cache_home,
        runtime_data_dir=runtime_data_dir,
        repo_dir=repo_dir,
    )
    printer(f"本地模型来源：{source_root}")
    for copy in plan["copies"]:
        if copy.children:
            for relative in copy.children:
                _copy_tree(copy.source / relative, copy.destination / relative, printer=printer)
        else:
            _copy_tree(copy.source, copy.destination, printer=printer)
    return plan


def check_local_models(
    source: str | Path | None = None,
    *,
    cache_home: Path | None = None,
    runtime_data_dir: Path | None = None,
    repo_dir: Path | None = None,
    printer: Callable[[str], None] = print,
) -> dict[str, object]:
    """Validate the source layout without copying anything."""

    source_root = resolve_source_root(source)
    plan = build_copy_plan(
        source_root,
        cache_home=cache_home,
        runtime_data_dir=runtime_data_dir,
        repo_dir=repo_dir,
    )
    printer(f"本地模型目录结构检查通过：{source_root}")
    for copy in plan["copies"]:
        printer(f"  {copy.label}: {copy.source} -> {copy.destination}")
    return plan


@contextmanager
def _temporary_environment(overrides: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        os.environ.update(overrides)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def verify_local_models(
    *,
    plan: dict[str, object] | None = None,
    repo_dir: Path | None = None,
    printer: Callable[[str], None] = print,
) -> None:
    """Strictly validate every copied asset without network fallback."""

    from src.model_profiles import ALL_PROFILE_IDS, inspect_model_profiles
    from src.utils.chordmini_runtime import get_chordmini_runtime

    if plan is None:
        plan = build_copy_plan(
            resolve_source_root(),
            cache_home=Path.home() / ".cache",
            runtime_data_dir=Path.home() / ".music-to-midi",
            repo_dir=repo_dir if repo_dir is not None else REPO_ROOT,
        )

    environment = {
        "MUSIC_TO_MIDI_ENABLED_PROFILES": ",".join(ALL_PROFILE_IDS),
        "MUSIC_TO_MIDI_REQUIRE_ENABLED_PROFILES": "1",
        "MUSIC_TO_MIDI_MIROS_DIR": str(plan["miros_dir"]),
        "HF_HOME": str(plan["hf_home"]),
        "HF_HUB_CACHE": str(plan["hf_hub_cache"]),
    }

    printer("离线校验全部模型配置与 ChordMini 资源...")
    with _temporary_environment(environment):
        snapshot = inspect_model_profiles(refresh=True)
        try:
            get_chordmini_runtime()
        except (OSError, RuntimeError) as exc:
            raise LocalModelError(f"ChordMini 离线校验失败：{exc}") from exc

    if not snapshot.ready:
        unavailable = [
            f"  - {item.id}: {item.unavailable_reason or 'unknown failure'}"
            for item in snapshot.profiles
            if item.enabled and not item.available
        ]
        detail = "\n".join(unavailable) or snapshot.readiness_error or "unknown failure"
        raise LocalModelError("复制后的本地模型未通过离线校验（安装器不会联网补全）：\n" + detail)

    for item in snapshot.profiles:
        if item.enabled:
            printer(f"  ✔ {item.id}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy pre-downloaded Music to MIDI models from a local cache mirror"
    )
    parser.add_argument(
        "--source",
        default=None,
        help=("local mirror root; defaults to $MUSIC_TO_MIDI_MODELS_SOURCE or ~/models"),
    )
    parser.add_argument(
        "--cache-home",
        default=None,
        help="cache root that receives music_ai_models/ and huggingface/ (default: ~/.cache)",
    )
    parser.add_argument(
        "--runtime-data-dir",
        default=None,
        help="application data directory that receives models/ (default: ~/.music-to-midi)",
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="project checkout that receives external/ai4m-miros (default: this file's directory)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate the source layout and exit without copying",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="copy only; skip the expensive offline readiness validation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        destination_kwargs = {
            "cache_home": Path(args.cache_home) if args.cache_home else None,
            "runtime_data_dir": (Path(args.runtime_data_dir) if args.runtime_data_dir else None),
            "repo_dir": Path(args.repo_dir) if args.repo_dir else None,
        }
        if args.check_only:
            check_local_models(args.source, **destination_kwargs)
            return 0
        plan = copy_local_models(args.source, **destination_kwargs)
        if not args.skip_verify:
            verify_local_models(
                plan=plan,
                repo_dir=Path(args.repo_dir) if args.repo_dir else None,
            )
    except LocalModelError as exc:
        print(f"错误：{exc}", flush=True)
        return 2
    except OSError as exc:
        print(f"错误：复制本地模型失败：{exc}", flush=True)
        return 2
    if args.skip_verify:
        print("本地模型复制完成（已跳过离线身份校验）。", flush=True)
    else:
        print("本地模型复制与离线校验完成。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
