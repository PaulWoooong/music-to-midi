"""Contract tests for the offline local model mirror copier."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import prepare_local_models as local_models


@pytest.fixture(autouse=True)
def _clear_huggingface_environment(monkeypatch):
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)


def _touch(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_mirror(root: Path) -> None:
    for name in local_models.MUSIC_AI_MODELS_REQUIRED:
        _touch(root / "music_ai_models" / name / "asset.bin", name)
    for name in local_models.MUSIC_TO_MIDI_REQUIRED:
        _touch(root / "music-to-midi" / name / "asset.bin", name)
    _touch(root / "music-to-midi" / "logs" / "old.log", "do not copy")
    for repo in local_models.HF_MUSCRIPTOR_REPOS:
        _touch(root / "huggingface" / "hub" / repo / "snapshots" / "rev" / "config.json", repo)
    _touch(root / "ai4m-miros" / "main.py", "main")
    _touch(root / "ai4m-miros" / "transcribe.py", "transcribe")


def test_copy_merges_into_runtime_caches_without_deleting_unrelated_files():
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        cache_home = temp / "home" / ".cache"
        runtime_data_dir = temp / "home" / ".music-to-midi"
        repo_dir = temp / "repo"
        _make_mirror(source)

        _touch(cache_home / "music_ai_models" / "aria_amt" / "keep.txt", "keep")
        _touch(runtime_data_dir / "models" / "audio-separator" / "keep.txt", "keep")
        _touch(cache_home / "huggingface" / "hub" / "unrelated" / "keep.txt", "keep")

        plan = local_models.copy_local_models(
            source,
            cache_home=cache_home,
            runtime_data_dir=runtime_data_dir,
            repo_dir=repo_dir,
            printer=lambda _: None,
        )

        assert (cache_home / "music_ai_models" / "aria_amt" / "asset.bin").is_file()
        assert (cache_home / "music_ai_models" / "aria_amt" / "keep.txt").is_file()
        assert (cache_home / "music_ai_models" / "bytedance_piano" / "asset.bin").is_file()
        assert (runtime_data_dir / "models" / "beat_this" / "asset.bin").is_file()
        assert (runtime_data_dir / "models" / "audio-separator" / "keep.txt").is_file()
        assert not (runtime_data_dir / "logs" / "old.log").exists()
        for repo in local_models.HF_MUSCRIPTOR_REPOS:
            assert (
                cache_home / "huggingface" / "hub" / repo / "snapshots" / "rev" / "config.json"
            ).is_file()
        assert (repo_dir / "external" / "ai4m-miros" / "main.py").is_file()
        assert plan["miros_dir"] == repo_dir / "external" / "ai4m-miros"


def test_copy_only_touches_muscriptor_huggingface_repositories():
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        cache_home = temp / "home" / ".cache"
        _make_mirror(source)
        _touch(
            source / "huggingface" / "hub" / "models--other--unrelated" / "blob.bin",
            "do not copy",
        )

        local_models.copy_local_models(
            source,
            cache_home=cache_home,
            runtime_data_dir=temp / "home" / ".music-to-midi",
            repo_dir=temp / "repo",
            printer=lambda _: None,
        )

        assert not (cache_home / "huggingface" / "hub" / "models--other--unrelated").exists()


def test_relative_huggingface_symlinks_survive_the_copy():
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        cache_home = temp / "home" / ".cache"
        _make_mirror(source)

        repo = source / "huggingface" / "hub" / local_models.HF_MUSCRIPTOR_REPOS[0]
        blob = _touch(repo / "blobs" / "deadbeef", "weights")
        snapshot = repo / "snapshots" / "rev" / "model.safetensors"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.symlink_to(Path("../../blobs/deadbeef"))

        local_models.copy_local_models(
            source,
            cache_home=cache_home,
            runtime_data_dir=temp / "home" / ".music-to-midi",
            repo_dir=temp / "repo",
            printer=lambda _: None,
        )

        copied = (
            cache_home
            / "huggingface"
            / "hub"
            / local_models.HF_MUSCRIPTOR_REPOS[0]
            / "snapshots"
            / "rev"
            / "model.safetensors"
        )
        assert copied.is_symlink()
        assert copied.read_text(encoding="utf-8") == "weights"


def test_missing_required_asset_fails_before_any_copy():
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        _make_mirror(source)
        chordmini = source / "music_ai_models" / "chordmini"
        (chordmini / "asset.bin").unlink()
        chordmini.rmdir()
        cache_home = temp / "home" / ".cache"

        with pytest.raises(local_models.LocalModelError) as excinfo:
            local_models.copy_local_models(
                source,
                cache_home=cache_home,
                runtime_data_dir=temp / "home" / ".music-to-midi",
                repo_dir=temp / "repo",
                printer=lambda _: None,
            )

        message = str(excinfo.value)
        assert "chordmini" in message
        assert "不会改为联网下载" in message
        assert not cache_home.exists()


def test_missing_source_root_reports_the_configured_path():
    with TemporaryDirectory() as temp_dir:
        missing = Path(temp_dir) / "missing-models"
        with pytest.raises(local_models.LocalModelError) as excinfo:
            local_models.resolve_source_root(missing)
        assert str(missing) in str(excinfo.value)


def test_source_environment_variable_is_used(monkeypatch):
    with TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "models"
        _make_mirror(source)
        monkeypatch.setenv(local_models.MODELS_SOURCE_ENV, str(source))
        assert local_models.resolve_source_root() == source.resolve()


def test_dot_cache_mirror_layout_is_accepted():
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        _make_mirror(source)
        (source / ".cache").mkdir()
        (source / "music_ai_models").rename(source / ".cache" / "music_ai_models")
        (source / "huggingface").rename(source / ".cache" / "huggingface")
        (source / "yourmt3").mkdir()

        plan = local_models.build_copy_plan(
            source,
            cache_home=temp / "home" / ".cache",
            runtime_data_dir=temp / "home" / ".music-to-midi",
            repo_dir=temp / "repo",
        )

        assert plan["copies"]
        labels = {copy.label for copy in plan["copies"]}
        assert labels == {
            "music_ai_models",
            "yourmt3",
            "music-to-midi",
            "huggingface",
            "ai4m-miros",
        }


def test_optional_yourmt3_cache_is_copied_when_present():
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        _make_mirror(source)
        _touch(source / "yourmt3" / "metadata.json", "{}")
        cache_home = temp / "home" / ".cache"

        local_models.copy_local_models(
            source,
            cache_home=cache_home,
            runtime_data_dir=temp / "home" / ".music-to-midi",
            repo_dir=temp / "repo",
            printer=lambda _: None,
        )

        assert (cache_home / "yourmt3" / "metadata.json").is_file()


def test_configured_huggingface_hub_cache_is_respected(monkeypatch):
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        _make_mirror(source)
        hub_cache = temp / "custom-hf" / "hub"
        monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

        plan = local_models.copy_local_models(
            source,
            cache_home=temp / "home" / ".cache",
            runtime_data_dir=temp / "home" / ".music-to-midi",
            repo_dir=temp / "repo",
            printer=lambda _: None,
        )

        assert plan["hf_hub_cache"] == hub_cache
        assert (hub_cache / local_models.HF_MUSCRIPTOR_REPOS[0]).is_dir()


def test_configured_miros_directory_is_respected(monkeypatch):
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        _make_mirror(source)
        configured = temp / "custom-miros"
        monkeypatch.setenv(local_models.MIROS_DIR_ENV, str(configured))

        plan = local_models.copy_local_models(
            source,
            cache_home=temp / "home" / ".cache",
            runtime_data_dir=temp / "home" / ".music-to-midi",
            repo_dir=temp / "repo",
            printer=lambda _: None,
        )

        assert plan["miros_dir"] == configured
        assert (configured / "main.py").is_file()


def test_check_only_validates_the_layout_without_copying():
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        cache_home = temp / "home" / ".cache"
        _make_mirror(source)

        plan = local_models.check_local_models(
            source,
            cache_home=cache_home,
            runtime_data_dir=temp / "home" / ".music-to-midi",
            repo_dir=temp / "repo",
            printer=lambda _: None,
        )

        assert plan["copies"]
        assert not cache_home.exists()
        assert not (temp / "repo").exists()


def test_cli_check_only_returns_zero_without_copying():
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        cache_home = temp / "home" / ".cache"
        _make_mirror(source)

        exit_code = local_models.main(
            [
                "--source",
                str(source),
                "--cache-home",
                str(cache_home),
                "--runtime-data-dir",
                str(temp / "home" / ".music-to-midi"),
                "--repo-dir",
                str(temp / "repo"),
                "--check-only",
            ]
        )

        assert exit_code == 0
        assert not cache_home.exists()


def test_cli_skip_verify_copies_the_whole_mirror():
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "models"
        cache_home = temp / "home" / ".cache"
        _make_mirror(source)

        exit_code = local_models.main(
            [
                "--source",
                str(source),
                "--cache-home",
                str(cache_home),
                "--runtime-data-dir",
                str(temp / "home" / ".music-to-midi"),
                "--repo-dir",
                str(temp / "repo"),
                "--skip-verify",
            ]
        )

        assert exit_code == 0
        assert (cache_home / "music_ai_models" / "aria_amt" / "asset.bin").is_file()
        assert (temp / "repo" / "external" / "ai4m-miros" / "main.py").is_file()
