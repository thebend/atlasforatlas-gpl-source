"""OpenWorld pipeline shared helpers.

Single import convention (docs/log/2026-10-19-cleanup.md §1.2 #20): absolute
imports from the repo root, which `uv run` puts on sys.path. Scripts keep
one bootstrap line for bare-`python3` runs from anywhere:

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.common.dates import parse
"""
from __future__ import annotations
