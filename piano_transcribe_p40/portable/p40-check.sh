#!/usr/bin/env bash
# Report GPU / CUDA / BF16 / engine availability for this portable bundle.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${DIR}/MusicToMidiPianoP40" --p40-check "$@"
