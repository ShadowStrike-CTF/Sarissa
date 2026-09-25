# Sarissa — `python -m sarissa` and PyInstaller entry point.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

"""Thin wrapper: all launch logic (port 7331, uvicorn, browser open) lives in sarissa.main."""

import os
import sys

# Windowed (console=False) exe: stdout/stderr are None, and uvicorn's log formatter
# calls sys.stdout.isatty() at startup — crashes before binding. Point them at devnull.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Absolute import: PyInstaller runs this file as a top-level script, not as a package module.
from sarissa.main import main  # noqa: E402

if __name__ == "__main__":
    main()
