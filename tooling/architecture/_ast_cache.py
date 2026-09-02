"""The one door every gate under tooling/ uses to read a source file.

A gate that could not read a file has not measured it, and until this module
owned the contract 59 handlers under tooling/ answered a SyntaxError, a
UnicodeDecodeError or an OSError with `continue`, `pass` or a bare `return`,
seven more with a line on stderr that no count can reach. An unreadable file
therefore counted as a file with no findings: it lowered every ratchet it fed,
and `ratchet.py --update` would then invite someone to bank the drop. Three failure vectors were measured against the exact ruff.yml
commands over addons/ -- a syntax error trips ruff's `invalid-syntax`, an
undecodable file needs E902 in the gate's select, and a file that is merely
unreadable to one gate's own parser was caught by nothing at all.

parse_file, parse_source, literal_file and read_source raise SourceUnreadable,
whose message names the path. read_source is the door for the gates that read
JavaScript and prose rather than Python: fourteen of them dropped an undecodable
file with a bare `continue`, and a dropped .js file is a JS gate measuring a
smaller tree than it reports.

The narrow, deliberate opt-out is parse_file_or_failure, which hands the failure
back so a caller that must keep going turns it into its own finding rather than
into silence -- the shape tooling/lint/py_lint.py already uses for its
`unreadable-source` finding. No tree in this workspace holds a fixture directory
of intentionally broken sources: measured 2026-09-02, all 10,864 .py files under
odoo/ plus 7,746 under enterprise/, 2,143 under agromarin/ and 129 under
design-themes/ parse, all 1,576 __manifest__.py files literal_eval to a dict,
and all 9,544 .js files outside node_modules decode. A gate that starts
tolerating a bad file without reporting it is therefore hiding a new one.

Retaining trees is opt-in through enable(); the lenient `errors=` modes exist
for doc_restated_counts.py, which is the only caller that reads a tree twice.
"""

from __future__ import annotations

import ast
import gc
from pathlib import Path

_TREES: dict[str, tuple[str, ast.Module | Exception]] = {}

_STATE = {"enabled": False}

_FREEZE_EVERY = 256

_FROZEN_AT = {"count": 0}


class SourceUnreadable(Exception):
    def __init__(self, origin: Path | str, cause: BaseException) -> None:
        super().__init__(f"{origin}: {type(cause).__name__}: {cause}")
        self.origin = str(origin)
        self.cause = cause


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
            entry = ast.parse(
                Path(path).read_text(encoding="utf-8", errors=errors), filename=key
            )
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            entry = exc.with_traceback(None)
        held = _TREES.get(key)
        if _STATE["enabled"] and (
            errors == "strict" or held is None or held[0] == errors
        ):
            _TREES[key] = (errors, entry)
            if len(_TREES) - _FROZEN_AT["count"] >= _FREEZE_EVERY:
                _FROZEN_AT["count"] = len(_TREES)
                gc.freeze()
    if isinstance(entry, Exception):
        raise SourceUnreadable(key, entry) from entry
    return entry


def read_source(path: Path | str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise SourceUnreadable(path, exc) from exc


def parse_source(text: str, origin: Path | str) -> ast.Module:
    try:
        return ast.parse(text, filename=str(origin))
    except (SyntaxError, ValueError) as exc:
        raise SourceUnreadable(origin, exc) from exc


def literal_file(path: Path | str) -> object:
    try:
        return ast.literal_eval(Path(path).read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, UnicodeDecodeError, OSError) as exc:
        raise SourceUnreadable(path, exc) from exc


def parse_file_or_failure(
    path: Path | str, *, errors: str = "strict"
) -> tuple[ast.Module | None, SourceUnreadable | None]:
    try:
        return parse_file(path, errors=errors), None
    except SourceUnreadable as failure:
        return None, failure


def clear() -> None:
    _TREES.clear()
    _FROZEN_AT["count"] = 0
    gc.unfreeze()
