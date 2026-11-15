"""Pinned runtime staging must preserve the official AppDir structure."""

import base64
import hashlib
import io
import json
import os
import subprocess
import urllib.error
from pathlib import Path

import pytest

import src.utils.musescore_runtime as runtime


@pytest.mark.parametrize(
    ("machine", "expected_arch", "expected_suffix"),
    [
        ("x86_64", "x86_64", "-x86_64.AppImage"),
        ("amd64", "x86_64", "-x86_64.AppImage"),
        ("aarch64", "aarch64", "-aarch64.AppImage"),
        ("arm64", "aarch64", "-aarch64.AppImage"),
    ],
)
def test_linux_release_metadata_follows_host_architecture(
    monkeypatch, machine, expected_arch, expected_suffix
):
    monkeypatch.setattr(runtime.platform, "machine", lambda: machine)
    release = runtime._linux_release_for_current_host()
    assert str(release["appimage"]).endswith(expected_suffix)
    assert int(release["bytes"]) > 0
    assert len(str(release["sha256"])) == 64


def test_linux_release_metadata_rejects_unknown_architecture(monkeypatch):
    monkeypatch.setattr(runtime.platform, "machine", lambda: "riscv64")
    with pytest.raises(runtime.MuseScoreRuntimeError, match=r"supports Linux .*aarch64"):
        runtime._linux_release_for_current_host()


def test_pinned_musescore_arm64_metadata_is_unique_and_verified():
    x86 = runtime.MUSESCORE_LINUX_RELEASES["x86_64"]
    arm = runtime.MUSESCORE_LINUX_RELEASES["aarch64"]
    assert x86["appimage"] != arm["appimage"]
    assert x86["sha256"] != arm["sha256"]
    for release in (x86, arm):
        assert release["appimage"].endswith(".AppImage")
        assert int(release["bytes"]) > 0
        assert len(str(release["sha256"])) == 64


@pytest.mark.parametrize("platform,expected", [("win32", "windows"), ("linux", "offscreen")])
def test_musescore_child_uses_its_own_qt_plugins_without_changing_parent(
    monkeypatch, platform, expected
):
    inherited = {
        "QT_QPA_PLATFORM": "offscreen" if platform == "win32" else "windows",
        "MU_QT_QPA_PLATFORM": "parent-only",
        "QT_PLUGIN_PATH": "/parent/pyqt/plugins",
        "QT_QPA_PLATFORM_PLUGIN_PATH": "/parent/pyqt/platforms",
        "QT_QPA_PLATFORMTHEME": "parent-only",
        "QML_IMPORT_PATH": "/parent/pyqt/qml",
        "QML2_IMPORT_PATH": "/parent/pyqt/qml2",
    }
    for name, value in inherited.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("QT_DEBUG_PLUGINS", "1")
    monkeypatch.setattr(runtime.sys, "platform", platform)
    environment = runtime.get_musescore_subprocess_env()
    assert environment["QT_QPA_PLATFORM"] == expected
    assert environment["MU_QT_QPA_PLATFORM"] == expected
    assert all(
        name not in environment
        for name in inherited
        if "PLATFORM" not in name or name.endswith(("PATH", "THEME"))
    )
    assert environment["QT_DEBUG_PLUGINS"] == "1"
    assert all(os.environ[name] == value for name, value in inherited.items())


@pytest.mark.skipif(
    os.environ.get("MUSIC_TO_MIDI_TEST_MUSESCORE") != "1",
    reason="requires explicit real MuseScore acceptance",
)
def test_real_musescore_starts_from_a_foreign_qt_environment(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen" if os.name == "nt" else "windows")
    monkeypatch.setenv("MU_QT_QPA_PLATFORM", "parent-only")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/parent/pyqt/plugins")
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "/parent/pyqt/platforms")
    binary = runtime.get_musescore_executable()
    assert runtime.musescore_version(binary)[:3] == tuple(
        int(part) for part in runtime.MUSESCORE_VERSION.split(".")
    )


def test_runtime_staging_preserves_relative_cyclic_and_dangling_links(tmp_path, monkeypatch):
    target = tmp_path / "cache" / runtime.MUSESCORE_VERSION
    license_bytes = b"GPL test fixture"
    prepared = []
    executable_relative = Path("bin/MuseScore4.exe" if os.name == "nt" else "AppRun")

    def prepare(temp_root, *, printer):
        distribution = temp_root / "extracted"
        executable = distribution / executable_relative
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"pinned runtime fixture")
        executable.chmod(0o755)
        (distribution / "share").mkdir()
        (distribution / "share/icon.png").write_bytes(b"original icon")
        (distribution / "usr").symlink_to(".", target_is_directory=True)
        (distribution / "icon.png").symlink_to(Path("share/icon.png"))
        (distribution / "manual.gz").symlink_to(Path("share/missing-manual.gz"))
        prepared.append(distribution)
        return distribution

    def download_license(_url, destination, **_kwargs):
        destination.write_bytes(license_bytes)

    monkeypatch.setattr(runtime, "_cache_root", lambda: target)
    monkeypatch.setattr(runtime, "_prepare_windows_runtime", prepare)
    monkeypatch.setattr(runtime, "_prepare_linux_runtime", prepare)
    monkeypatch.setattr(runtime, "_download_verified", download_license)
    monkeypatch.setattr(
        runtime,
        "musescore_version",
        lambda _path: tuple(int(part) for part in runtime.MUSESCORE_VERSION.split(".")),
    )
    monkeypatch.setattr(runtime, "MUSESCORE_LICENSE_BYTES", len(license_bytes))
    monkeypatch.setattr(
        runtime, "MUSESCORE_LICENSE_SHA256", hashlib.sha256(license_bytes).hexdigest()
    )

    executable = runtime.download_musescore_runtime(printer=lambda _message: None)

    assert executable == target / executable_relative
    assert executable.read_bytes() == b"pinned runtime fixture"
    assert (target / "usr").is_symlink()
    assert os.readlink(target / "usr") == "."
    assert os.readlink(target / "icon.png") == str(Path("share/icon.png"))
    assert (target / "icon.png").read_bytes() == b"original icon"
    assert os.readlink(target / "manual.gz") == str(Path("share/missing-manual.gz"))
    assert not (target / "manual.gz").exists()
    assert (target / "LICENSE.txt").read_bytes() == license_bytes
    assert not prepared[0].exists()
    assert runtime.download_musescore_runtime(printer=lambda _message: None) == executable
    assert len(prepared) == 1


@pytest.mark.parametrize(
    ("output", "returncode", "expected"),
    [
        ("/lib/x86_64-linux-gnu/libpipewire-0.3.so.0\nMuseScore4 4.7.4\n", 0, (4, 7, 4)),
        ("MuseScore4 4.7.4\r\n", 0, (4, 7, 4)),
        ("MuseScore Studio 4.7.4\n", 0, (4, 7, 4)),
        ("MuseScore version 3.6.2\n", 0, (3, 6, 2)),
        ("Other Editor 4.7.4\n", 0, None),
        ("/lib/x86_64-linux-gnu/libpipewire-0.3.so.0\n", 0, None),
        ("Failed to start MuseScore4 4.7.4\n", 0, None),
        ("", 0, None),
        ("MuseScore4 4.7.4\n", 1, None),
    ],
)
def test_version_requires_successful_musescore_identity_line(
    tmp_path, monkeypatch, output, returncode, expected
):
    executable = tmp_path / "renderer"
    executable.write_bytes(b"runtime fixture")
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, returncode, output),
    )
    assert runtime.musescore_version(executable) == expected


@pytest.mark.parametrize("version", [(3, 6, 2), (4, 0), (4, 7, 4), (4, 7, 5)])
def test_runtime_rejects_versions_without_the_cli_shutdown_fix(tmp_path, monkeypatch, version):
    executable = tmp_path / "renderer"
    executable.write_bytes(b"runtime fixture")
    monkeypatch.setattr(runtime, "musescore_version", lambda _path: version)
    with pytest.raises(runtime.MuseScoreRuntimeError, match=r"4\.7\.6\+ is required"):
        runtime.validate_musescore_runtime(executable)


@pytest.mark.parametrize("version", [(4, 7, 6), (4, 8, 0)])
def test_runtime_accepts_supported_shutdown_versions(tmp_path, monkeypatch, version):
    executable = tmp_path / "renderer"
    executable.write_bytes(b"runtime fixture")
    monkeypatch.setattr(runtime, "musescore_version", lambda _path: version)
    assert runtime.validate_musescore_runtime(executable) == executable.resolve()


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload
        self._sent = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, _size: int = -1) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._payload


def test_appimage_download_falls_back_to_the_next_mirror(tmp_path, monkeypatch):
    payload = b"aarch64 appimage fixture"
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise urllib.error.URLError("primary mirror unreachable")
        return _FakeResponse(payload)

    monkeypatch.setattr(runtime.urllib.request, "urlopen", fake_urlopen)
    destination = tmp_path / "MuseScore-aarch64.AppImage"

    runtime._download_verified(
        ("https://primary.invalid/appimage", "https://mirror.invalid/appimage"),
        destination,
        expected_size=len(payload),
        expected_sha256=expected_sha256,
        printer=lambda _message: None,
    )

    assert [url for url, _timeout in calls] == [
        "https://primary.invalid/appimage",
        "https://mirror.invalid/appimage",
    ]
    assert destination.read_bytes() == payload


def test_appimage_download_retries_a_mismatched_mirror(tmp_path, monkeypatch):
    payload = b"aarch64 appimage fixture"
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            return _FakeResponse(b"unexpected mirror content")
        return _FakeResponse(payload)

    monkeypatch.setattr(runtime.urllib.request, "urlopen", fake_urlopen)
    destination = tmp_path / "MuseScore-aarch64.AppImage"

    runtime._download_verified(
        ("https://primary.invalid/appimage", "https://mirror.invalid/appimage"),
        destination,
        expected_size=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        printer=lambda _message: None,
    )

    assert calls == [
        "https://primary.invalid/appimage",
        "https://mirror.invalid/appimage",
    ]
    assert destination.read_bytes() == payload


def test_appimage_download_reports_every_failed_mirror(tmp_path, monkeypatch):
    def fake_urlopen(_request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(runtime.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(runtime.MuseScoreRuntimeError, match="every configured mirror"):
        runtime._download_verified(
            ("https://primary.invalid/appimage", "https://mirror.invalid/appimage"),
            tmp_path / "MuseScore-aarch64.AppImage",
            expected_size=1,
            expected_sha256="0" * 64,
            printer=lambda _message: None,
        )


def test_license_download_falls_back_to_the_github_contents_api(tmp_path, monkeypatch):
    payload = b"GPL fixture via GitHub contents API"
    destination = tmp_path / "LICENSE.txt"
    requested_urls = []

    def failing_download(_url, _destination, **_kwargs):
        raise runtime.MuseScoreRuntimeError("raw.githubusercontent.com unreachable")

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        response = {"content": base64.b64encode(payload).decode("ascii")}
        return io.BytesIO(json.dumps(response).encode("utf-8"))

    monkeypatch.setattr(runtime, "_download_verified", failing_download)
    monkeypatch.setattr(runtime.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(runtime, "MUSESCORE_LICENSE_BYTES", len(payload))
    monkeypatch.setattr(runtime, "MUSESCORE_LICENSE_SHA256", hashlib.sha256(payload).hexdigest())

    runtime._download_license_verified(destination, printer=lambda _message: None)

    assert destination.read_bytes() == payload
    assert requested_urls == [
        "https://api.github.com/repos/musescore/MuseScore/contents/"
        f"{runtime.MUSESCORE_LICENSE_NAME}?ref={runtime.MUSESCORE_SOURCE_REVISION}"
    ]
