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

#: path -> (the `errors` mode that produced it, the tree or the raised exception).
#:
#: Keyed by PATH ALONE, not by `(path, errors)`. The two modes differ only for a
#: file that is not valid UTF-8: with none in the corpus, a per-mode key stored
#: every file twice and the sharing this module exists for never happened.
#: Measured on `doc_restated_counts --check`, which is the one caller that mixes
#: the modes: 67k parse_file calls over 6809 distinct files retained 13488
#: entries, 6679 of them a second copy of a file already held.
_TREES: dict[str, tuple[str, ast.Module | Exception]] = {}

#: A container rather than a rebindable module global so `enable()` can flip
#: the flag without a `global` statement (ruff PLW0603).
_STATE = {"enabled": False}

#: How many cached trees to accumulate between `gc.freeze()` calls.
_FREEZE_EVERY = 256

#: The `len(_TREES)` the last `gc.freeze()` ran at. A watermark rather than a
#: `len % _FREEZE_EVERY` test because a strict request that upgrades a lenient
#: slot REPLACES an entry instead of adding one, so the length can sit on a
#: multiple across many stores and re-freeze on each of them.
_FROZEN_AT = {"count": 0}


def enable() -> None:
    """Retain parsed trees for the rest of this process.

    Only worth calling from a gate that walks the same files more than once --
    see the module docstring for why it is a loss everywhere else.
    """
    _STATE["enabled"] = True


def _serves(
    held: tuple[str, ast.Module | Exception] | None, wanted: str
) -> ast.Module | Exception | None:
    """The cached entry that answers a request for *wanted*, or None to re-parse.

    Sharing is ONE-WAY, and the direction matters. `errors="ignore"` differs from
    `"strict"` only by not raising on a byte that is not valid UTF-8, so a tree
    the strict read produced is byte-for-byte the tree the lenient read would
    have produced, and a `SyntaxError` or `OSError` it raised is the one the
    lenient read would raise too. A lenient entry can therefore NOT answer a
    strict request -- doing so would hand a caller that asked to be told about
    mojibake a tree parsed from silently-dropped bytes -- and a strict
    `UnicodeDecodeError` cannot answer a lenient one, because that is the single
    case where the two genuinely disagree.

    Sharing runs FROM `"strict"` ONLY, never between two lenient modes. `ignore`
    drops an undecodable byte and `replace` substitutes U+FFFD, so their trees
    genuinely differ; an earlier revision of this function returned "not strict"
    for both and handed a `replace` caller the `ignore` tree -- the same silent
    wrong answer it was written to prevent, one mode over. Only the strict read
    is the answer every mode would have got.

    A strict request that finds a lenient entry re-parses and REPLACES it, so the
    slot upgrades to the answer that serves everyone and the next lenient caller
    still hits. A lenient request that finds a DIFFERENT lenient mode re-parses
    and stores nothing, because storing would evict the mode that is being used
    and make the pair thrash; no caller mixes two lenient modes today.
    """
    if held is None:
        return None
    mode, entry = held
    if mode == wanted:
        return entry
    if mode != "strict":
        return None  # lenient entry, different caller: never share sideways
    return None if isinstance(entry, UnicodeDecodeError) else entry


def parse_file(path: Path | str, *, errors: str = "strict") -> ast.Module:
    """Return the syntax tree of *path*, parsed once per process when enabled.

    Re-raises whatever the first attempt raised -- `SyntaxError`,
    `UnicodeDecodeError`, `OSError` -- so a caller keeps the `except` shape it
    had when it called `ast.parse(path.read_text(...))` itself.
    """
    key = str(path)
    entry = _serves(_TREES.get(key), errors)
    if entry is None:
        try:
            entry = ast.parse(Path(path).read_text(encoding="utf-8", errors=errors))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            entry = exc
        held = _TREES.get(key)
        # Store only what will be READ back: a strict entry (which serves every
        # mode) or the first entry for this path. A lenient entry must never
        # evict another lenient mode's -- see `_serves`.
        if _STATE["enabled"] and (
            errors == "strict" or held is None or held[0] == errors
        ):
            _TREES[key] = (errors, entry)
            if len(_TREES) - _FROZEN_AT["count"] >= _FREEZE_EVERY:
                _FROZEN_AT["count"] = len(_TREES)
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
    _FROZEN_AT["count"] = 0
    gc.unfreeze()
