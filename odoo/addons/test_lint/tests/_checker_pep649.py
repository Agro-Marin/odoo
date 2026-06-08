"""PEP 649 annotation-resolution checker.

Python 3.14 evaluates annotations lazily through a per-object
``__annotate__`` descriptor (PEP 649).  Every tool that inspects a
function or class -- ``inspect.signature``, ``typing.get_type_hints``,
IDE completion backends, Sphinx autodoc, pydantic-style validators --
eventually runs that descriptor, which looks up identifiers in the
defining module's globals.

The footgun: symbols imported under ``if TYPE_CHECKING:`` are *not* in
module globals at runtime.  When an identifier from such a block
appears in a runtime-visible annotation, the resolution raises
``NameError``.  Code still runs; introspection silently breaks.

This checker walks a curated list of modules, tries
``inspect.signature`` on every public callable and method, and reports
any ``NameError`` / ``AttributeError`` coming from annotation
resolution.  It is intentionally a runtime check (not an AST check):
the goal is to reproduce exactly the failure mode real tools hit.

Fix pattern: move the import out of ``if TYPE_CHECKING:`` to runtime.
Stdlib imports (``collections.abc``, ``types``) are always safe.
Odoo-local types are safe when the module's existing imports already
pull the target in; otherwise a structural cycle must be broken first.
"""

import importlib
import inspect


def _probe(obj: object, label: str) -> str | None:
    """Return a diagnostic if ``inspect.signature(obj)`` fails on annotations."""
    try:
        inspect.signature(obj)  # type: ignore[arg-type]
    except (NameError, AttributeError) as e:
        return f"{label}: {type(e).__name__}: {e}"
    except TypeError, ValueError:
        # Built-in or otherwise non-signature-able; not what we hunt.
        return None
    return None


def scan_module(modname: str) -> list[str]:
    """Import ``modname`` and probe its public callables.

    Only symbols whose ``__module__`` is ``modname`` are probed; re-exports
    would otherwise re-report failures that belong to the source module.
    Returns a list of failure messages; empty list means clean.
    """
    try:
        m = importlib.import_module(modname)
    except Exception as e:
        return [f"{modname}: import-fail: {type(e).__name__}: {e}"]

    fails: list[str] = []
    for name in dir(m):
        if name.startswith("_"):
            continue
        obj = getattr(m, name)
        if getattr(obj, "__module__", None) != modname:
            continue
        if callable(obj):
            err = _probe(obj, f"{modname}.{name}")
            if err:
                fails.append(err)
        if inspect.isclass(obj):
            for mname, mval in vars(obj).items():
                if callable(mval) and not mname.startswith("__"):
                    err = _probe(mval, f"{modname}.{name}.{mname}")
                    if err:
                        fails.append(err)
    return fails


def scan_modules(modnames: list[str]) -> dict[str, list[str]]:
    """Run :func:`scan_module` over ``modnames``; return only modules with failures."""
    return {m: fails for m in modnames if (fails := scan_module(m))}
