#!/usr/bin/env bash
# Open the piano-only desktop GUI.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${DIR}/MusicToMidiPianoP40" --gui "$@"
