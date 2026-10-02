#!/usr/bin/env python
"""Mentat engine launcher.

The Mentat app launches `python server.py --port 8765`; this shim preserves that
contract while the engine itself now lives in the `mentat2` package
(`mentat2.fronts.server`). v1's server is preserved as `server.v1.bak.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mentat2.fronts.server import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
