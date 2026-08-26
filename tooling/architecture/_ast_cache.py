from __future__ import annotations

import ast
import gc
from pathlib import Path

_TREES: dict[str, tuple[str, ast.Module | Exception]] = {}

_STATE = {"enabled": False}

_FREEZE_EVERY = 256

_FROZEN_AT = {"count": 0}


def enable() -> None:
    _STATE["enabled"] = True


def _serves(
    held: tuple[str, ast.Module | Exception] | None, wanted: str
) -> ast.Module | Exception | None:
    if held is None:
        return None
    mode, entry = held
    if mode == wanted:
        return entry
    if mode != "strict":
        return None
    return None if isinstance(entry, UnicodeDecodeError) else entry


def parse_file(path: Path | str, *, errors: str = "strict") -> ast.Module:
    key = str(path)
    entry = _serves(_TREES.get(key), errors)
    if entry is None:
        try:
            entry = ast.parse(Path(path).read_text(encoding="utf-8", errors=errors))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            entry = exc
        held = _TREES.get(key)
        if _STATE["enabled"] and (
            errors == "strict" or held is None or held[0] == errors
        ):
            _TREES[key] = (errors, entry)
            if len(_TREES) - _FROZEN_AT["count"] >= _FREEZE_EVERY:
                _FROZEN_AT["count"] = len(_TREES)
                gc.freeze()
    if isinstance(entry, Exception):
        raise entry.with_traceback(None)
    return entry


def clear() -> None:
    _TREES.clear()
    _FROZEN_AT["count"] = 0
    gc.unfreeze()
