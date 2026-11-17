#!/usr/bin/env python3
"""Frozen entry point for the portable P40 piano transcription package.

Subcommands:
  (no arguments)  desktop GUI (piano-only)
  --gui           desktop GUI
  --p40-check     environment / GPU / engine compatibility report
  <input> ...     piano transcription CLI (same options as transcribe.py)
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _configure_runtime_environment() -> None:
    # Keep output stable for Chinese/English log messages in both TTY and pipes.
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    # Do not let stray user settings change the bundled compute policy.
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _dispatch() -> int:
    # Must run before any torch / multiprocessing import in the frozen process.
    multiprocessing.freeze_support()
    _configure_runtime_environment()

    argv = sys.argv[1:]
    if argv and argv[0] in {"--p40-check", "--check", "check"}:
        sys.argv = [sys.argv[0], *argv[1:]]
        from piano_transcribe_p40.p40_check import main as check_main

        return int(check_main())

    if not argv or argv[0] in {"--gui", "gui"}:
        from piano_transcribe_p40.gui import main as gui_main

        return int(gui_main(argv[1:] if argv else []))

    from piano_transcribe_p40.transcribe import main as transcribe_main

    return int(transcribe_main(argv))


if __name__ == "__main__":
    raise SystemExit(_dispatch())
