#!/usr/bin/env bash
# Add launchers/instructions to a built bundle and create a .tar.xz archive.
#
# Usage:
#   ./piano_transcribe_p40/package_linux_portable.sh [DIST_DIR]
#
# DIST_DIR defaults to <repo>/dist-p40 and must already contain
# MusicToMidiPianoP40/ produced by build_linux_portable.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${1:-${ROOT_DIR}/dist-p40}"
BUNDLE="${DIST_DIR}/MusicToMidiPianoP40"

if [[ ! -x "${BUNDLE}/MusicToMidiPianoP40" ]]; then
    echo "error: ${BUNDLE}/MusicToMidiPianoP40 not found; run build_linux_portable.sh first." >&2
    exit 1
fi

echo "==> Copying launchers and usage notes"
for name in run.sh p40-check.sh gui.sh; do
    install -m 0755 "${SCRIPT_DIR}/portable/${name}" "${BUNDLE}/${name}"
done
install -m 0644 "${SCRIPT_DIR}/portable/使用说明.txt" "${BUNDLE}/使用说明.txt"

echo "==> Creating archive (multi-threaded xz)"
ARCHIVE="${DIST_DIR}/MusicToMidiPianoP40-linux-x86_64.tar.xz"
tar -C "${DIST_DIR}" -I 'xz -T0 -6' -cf "${ARCHIVE}" MusicToMidiPianoP40
sha256sum "${ARCHIVE}" > "${ARCHIVE}.sha256"

echo "==> Done"
ls -lh "${ARCHIVE}" "${ARCHIVE}.sha256"
