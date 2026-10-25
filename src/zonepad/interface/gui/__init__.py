from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from zonepad import __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zonepad-gui", description="ZonaPad — calibração guiada")
    parser.add_argument("--version", action="version", version=f"zonepad {__version__}")
    parser.add_argument("--smoke", action="store_true", help="monta a janela e encerra")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """Start the optional Qt GUI after handling terminal-only arguments."""
    args = _parser().parse_args(argv)
    try:
        from .app import run_app
    except ImportError as exc:
        if exc.name is not None and exc.name.startswith("PySide6"):
            sys.stderr.write("GUI indisponível: instale com `python -m pip install -e '.[gui]'`.\n")
            return 2
        raise
    return run_app(smoke=args.smoke)
