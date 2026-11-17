#!/usr/bin/env bash
# Launch the portable P40 piano transcription CLI.
#
# Examples:
#   ./run.sh input.wav -o output -e transkun
#   ./run.sh song.mp4 -o output -e bytedance_pedal --skip-beat-detect
#   ./run.sh --help
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${DIR}/MusicToMidiPianoP40" "$@"
