"""Launches the Second Brain chat app (entry point for the `secondbrain` command)."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain_tui import main  # noqa: E402

__all__ = ["main"]
