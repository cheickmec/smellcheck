#!/usr/bin/env python3
"""Agent Skills shim — delegates to the ``smellcheck`` package.

This script is kept at the original path so that existing Agent Skills
integrations continue to work.  It adds the ``src/`` directory from
the repository root to ``sys.path`` so the import succeeds even when
the package is not pip-installed.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _ensure_importable() -> None:
    """Add the repo ``src/`` directory to sys.path when needed."""
    here = Path(__file__).resolve().parent
    # Walk up to the repo root (contains pyproject.toml)
    for parent in [here, *here.parents]:
        if (parent / "pyproject.toml").is_file():
            src = str(parent / "src")
            if src not in sys.path:
                sys.path.insert(0, src)
            return


_ensure_importable()

from smellcheck.detector import main  # noqa: E402

if __name__ == "__main__":
    main()
