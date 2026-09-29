"""Hilfsfunktion: reine Module der Integration ohne Home Assistant laden."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

_PKG = "dienstplan_pure"

if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "custom_components" / "dienstplan")]
    sys.modules[_PKG] = _pkg


def load(name: str):
    return importlib.import_module(f"{_PKG}.{name}")
