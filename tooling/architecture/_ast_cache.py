"""One parse per file per run, for the gates that walk the same tree twice.

Retaining syntax trees is OFF by default, because for almost every gate here it
is a straight loss: they walk the corpus once, so a cache never gets a hit and
only pays. Measured on `naming_vocabulary --count`, storing the 6.5k trees it
reads exactly once took it from 9.6s to 10.5s outright, and to 24.2s once the
cyclic collector began rescanning the retained trees on every pass.

`doc_restated_counts` is the case that justifies the module. It imports six
sibling gates to cross-check the figures restated in `doc/architecture/`, so one
`--check` walks the same ~6k sources eight times over: 66k `ast.parse` calls for
6k distinct files, 55s of that gate's 145s, and 12% of the whole gate sweep. It
calls `enable()` and drops to 94s.

Caching at THIS layer rather than at the gate's own entry point is deliberate.
`doc_restated_counts.field_hook_exemptions` calls `field_hook_naming.measure()`
twice on purpose, with `_DEDICATED_USES` patched to `sys.maxsize` in between, to
recover the uncapped count; a `functools.cache` on `measure` would hand the
second call the capped answer and silently restate a wrong figure. The syntax
trees are identical across those two calls even though the results are not, so
the parse is the one thing that is always safe to reuse.

The trees are SHARED, not copied. Every consumer in `tooling/architecture/`
reads them through `ast.walk` and none mutates one; a caller that needs to
mutate must `copy.deepcopy` first, or it will corrupt every later reader.
"""

from __future__ import annotations

import ast
import gc
from pathlib import Path

#: (path, errors) -> the parsed tree, or the exception the first parse raised.
_TREES: dict[tuple[str, str], ast.Module | Exception] = {}

#: A container rather than a rebindable module global so `enable()` can flip
#: the flag without a `global` statement (ruff PLW0603).
_STATE = {"enabled": False}

#: How many cached trees to accumulate between `gc.freeze()` calls.
_FREEZE_EVERY = 256


def enable() -> None:
    """Retain parsed trees for the rest of this process.

    Only worth calling from a gate that walks the same files more than once --
    see the module docstring for why it is a loss everywhere else.
    """
    _STATE["enabled"] = True


def parse_file(path: Path | str, *, errors: str = "strict") -> ast.Module:
    """Return the syntax tree of *path*, parsed once per process when enabled.

    Re-raises whatever the first attempt raised -- `SyntaxError`,
    `UnicodeDecodeError`, `OSError` -- so a caller keeps the `except` shape it
    had when it called `ast.parse(path.read_text(...))` itself.
    """
    key = (str(path), errors)
    entry = _TREES.get(key)
    if entry is None:
        try:
            entry = ast.parse(Path(path).read_text(encoding="utf-8", errors=errors))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            entry = exc
        if _STATE["enabled"]:
            _TREES[key] = entry
            if len(_TREES) % _FREEZE_EVERY == 0:
                # A tree is thousands of tracked objects that the cache keeps
                # alive to the end of the run, so each gen-2 pass rescans the
                # whole cache and the scan grows with it: that alone is the
                # 145s -> 129s-instead-of-94s gap. `gc.freeze()` moves what is
                # tracked now into a permanent generation that is never
                # scanned, which recovers it WITHOUT giving up cycle collection
                # for the rest of the process the way `gc.disable()` would.
                gc.freeze()
    if isinstance(entry, Exception):
        # Clear the traceback before re-raising: raising one stored instance
        # repeatedly chains a new frame onto it at every call site.
        raise entry.with_traceback(None)
    return entry


def clear() -> None:
    """Drop the cache and unfreeze. For tests that rewrite a file mid-process."""
    _TREES.clear()
    gc.unfreeze()
