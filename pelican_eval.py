#!/usr/bin/env python3
"""Pelican Bicycle Eval: repeatable SVG comparisons and optional proxy diagnostics.

Usage:
    python3 pelican_eval.py render MANIFEST [gallery options]
    python3 pelican_eval.py proxy-check [proxy-check options]
    python3 pelican_eval.py proxy-check render [proxy-check options]

Commands:
    render       Build a self-contained comparison gallery from existing SVGs.
    proxy-check  Run or re-render the model x channel integrity diagnostic.

Use ``pelican_eval.py <command> --help`` for command-specific options.
"""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
COMMANDS = {
    "render": ROOT / "pelican_gallery.py",
    "proxy-check": ROOT / "pelican_proxy_check.py",
}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    command = args.pop(0)
    target = COMMANDS.get(command)
    if target is None:
        choices = ", ".join(COMMANDS)
        raise SystemExit(f"unknown command: {command}\navailable commands: {choices}")
    os.execv(sys.executable, [sys.executable, str(target), *args])


if __name__ == "__main__":
    sys.exit(main())
