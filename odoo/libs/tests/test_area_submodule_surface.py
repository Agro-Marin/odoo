import ast
import functools
import importlib
import json
import pathlib
import subprocess
import sys
import textwrap
import types

import pytest

_LIBS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _LIBS.parents[1]

# `libs_facade_check.py` enforces that code imports odoo.libs **areas**
# (`odoo.libs.numbers`), never the module that implements them today
# (`odoo.libs.numbers.float_utils`). It is structurally blind to one spelling:
#
#     from odoo.libs.numbers import float_utils
#
# because `imported_modules()` records `node.module` -- here `odoo.libs.numbers`,
# a legal area -- and treats everything in the `import` list as a *symbol*. Its
# own docstring says as much: "the names are symbols and are not paths."
#
# ARCHITECTURE.md notes the discriminator "is on disk". That is necessary but
# NOT sufficient, which is worth recording because the obvious fix does not
# work: `odoo/libs/json/fast_clone.py` exists, yet `from odoo.libs.json import
# fast_clone` yields a **function** (`__init__.py` does `from .fast_clone import
# fast_clone`), so a disk-presence rule reports 8 false positives there while
# missing `web.urls`. I tried exactly that rule; it got 11 of 23 sites wrong in
# both directions. Only the runtime binding is authoritative -- which a static
# CI checker cannot consult, and a test can.
#
# The surface splits in two, and the distinction is the point:
#
#   DECLARED   -- the area lists the submodule in its own `__all__`. That is the
#                 area publishing it; importing it is using the public surface.
#   ACCIDENTAL -- Python binds a submodule onto its parent package as a side
#                 effect of importing it, so every area leaks its internals
#                 whether it meant to or not. Importing one of these is real
#                 leaf coupling, and it is what the gate exists to stop.
#
# The accidental count is 36, measured from DISK. Two earlier versions measured
# it from the areas' runtime attributes and were order-dependent: a submodule
# binds onto its parent when anything imports it, and a full Tier-1 run also
# imports odoo/libs/<area>/tests/, binding `tests` onto the area too. Both
# passed in isolation and failed inside the full run.

#: Submodules an area deliberately publishes in `__all__`.
DECLARED_SUBMODULE_EXPORTS: dict[str, set[str]] = {
    "filesystem": {"appdirs", "mimetypes", "osutil"},
    # `import_map` left on 2026-08-09 with `libs/constants.py`: it read
    # ODOO_EXTERNAL_LIBS, a table of Odoo asset paths, so neither it nor the
    # table was ever libs material. Both are under `tools/assets/` now, and
    # `web` publishes only the genuinely generic URL helpers.
    "web": {"urls"},
}

#: Leaf-module imports spelled `from odoo.libs.<area> import <submodule>` that
#: reach ACCIDENTAL surface. Invisible to libs_facade_check; pinned here.
KNOWN_ACCIDENTAL_LEAF_IMPORTS: dict[str, str] = {
    "datetime.tz": "safe_eval and others take the tz module wholesale",
    "numbers.float_utils": "float helpers imported as a module rather than by name",
    "_vendor.sessions": "vendored requests sessions",
    "profiling.nplusone": "profiler wiring",
    "profiling.orm_profiler": "profiler wiring",
}


def _areas() -> list[str]:
    return sorted(
        p.name
        for p in _LIBS.iterdir()
        if p.is_dir() and (p / "__init__.py").is_file() and p.name != "tests"
    )


@functools.cache
def _runtime_surface() -> dict[str, dict[str, list[str]]]:
    """Per-area {declared, accidental} submodule attributes, probed OUT OF PROCESS.

    This has to import every submodule to tell a module from a same-named
    symbol, and doing that in-process is not neutral: it populates
    ``sys.modules`` and broke the neighbouring lazy-facade suite
    (``test_facade_is_lazy.py`` went 6 passed -> 3 failed purely because this
    file ran first). A subprocess keeps the measurement accurate and the
    parent's import state untouched -- the same reason
    ``odoo/tools/tests/test_all_tools_modules_import.py`` shells out.
    """
    program = textwrap.dedent(
        """
        import importlib, json, pathlib, sys, types
        libs = pathlib.Path(sys.argv[1])
        out = {}
        for p in sorted(libs.iterdir()):
            if not (p.is_dir() and (p / "__init__.py").is_file()) or p.name == "tests":
                continue
            try:
                mod = importlib.import_module("odoo.libs." + p.name)
            except Exception:
                continue
            for f in sorted(p.glob("*.py")):
                if f.stem != "__init__":
                    try:
                        importlib.import_module("odoo.libs.%s.%s" % (p.name, f.stem))
                    except Exception:
                        pass
            exported = set(getattr(mod, "__all__", []))
            declared, accidental = [], []
            prefix = "odoo.libs.%s." % p.name
            for name, value in vars(mod).items():
                if not isinstance(value, types.ModuleType):
                    continue
                if not getattr(value, "__name__", "").startswith(prefix):
                    continue
                (declared if name in exported else accidental).append(name)
            out[p.name] = {"declared": sorted(declared), "accidental": sorted(accidental)}
        json.dump(out, sys.stdout)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program, str(_LIBS)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=_REPO,
        check=True,
    )
    return json.loads(result.stdout)


def _submodule_attributes(area: str) -> tuple[set[str], set[str]]:
    """(declared, accidental) submodules reachable as attributes of the area."""
    entry = _runtime_surface().get(area, {"declared": [], "accidental": []})
    return set(entry["declared"]), set(entry["accidental"])


def _leaf_imports_via_area() -> dict[str, int]:
    """`from odoo.libs.<area> import <name>` where <name> is really a module."""
    is_module: set[str] = set()
    for area in _areas():
        declared, accidental = _submodule_attributes(area)
        is_module |= {f"{area}.{n}" for n in declared | accidental}

    counts: dict[str, int] = {}
    for root in (_REPO / "odoo", _REPO / "addons"):
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.level or not node.module:
                    continue
                if not node.module.startswith("odoo.libs.") or node.module.count(".") != 2:
                    continue
                area = node.module.split(".")[2]
                for alias in node.names:
                    key = f"{area}.{alias.name}"
                    if key in is_module:
                        counts[key] = counts.get(key, 0) + 1
    return counts


def test_declared_submodule_exports_are_pinned():
    actual = {a: _submodule_attributes(a)[0] for a in _areas()}
    actual = {a: names for a, names in actual.items() if names}
    assert actual == DECLARED_SUBMODULE_EXPORTS, (
        f"an area changed which submodules it publishes in __all__: {actual}. "
        f"Publishing a submodule is a real interface decision -- it makes the "
        f"implementation module part of the area's contract, which is the "
        f"opposite of what ARCHITECTURE.md says the libs boundary is."
    )


def _accidental_from_disk(area: str) -> set[str]:
    """Submodules on disk that the area does not declare in ``__all__``.

    Computed from the filesystem, NOT from the area's runtime attributes.
    Reading attributes is order-dependent in two ways that both bit this test:
    a submodule binds onto its parent when anything imports it, and a full
    Tier-1 run also imports ``odoo/libs/<area>/tests/``, which binds ``tests``
    onto the area as well. Disk is the stable denominator.
    """
    mod = importlib.import_module(f"odoo.libs.{area}")
    exported = set(getattr(mod, "__all__", []))
    on_disk = {p.stem for p in (_LIBS / area).glob("*.py") if p.stem != "__init__"}
    return on_disk - exported


def test_accidental_submodule_surface_is_bounded():
    total = sum(len(_accidental_from_disk(a)) for a in _areas())
    # Not a prohibition: Python binds a submodule onto its parent on import, so
    # this cannot reach zero without lazy areas. It is a *budget*, so a new leak
    # is visible rather than free.
    assert total <= 36, (
        f"accidental submodule surface grew to {total} (was 36). Each one is a "
        f"leaf module importable as `from odoo.libs.<area> import <name>`, "
        f"which libs_facade_check cannot see."
    )


def test_leaf_imports_through_accidental_surface_are_pinned():
    counts = _leaf_imports_via_area()
    declared_keys = {
        f"{area}.{name}"
        for area, names in DECLARED_SUBMODULE_EXPORTS.items()
        for name in names
    }
    accidental_hits = {k: v for k, v in counts.items() if k not in declared_keys}
    assert set(accidental_hits) == set(KNOWN_ACCIDENTAL_LEAF_IMPORTS), (
        f"leaf-module imports through ACCIDENTAL area surface changed: "
        f"{sorted(accidental_hits)} vs pinned "
        f"{sorted(KNOWN_ACCIDENTAL_LEAF_IMPORTS)}. These are exactly the "
        f"imports libs_facade_check is blind to; import the area and use the "
        f"symbol, or promote the submodule into __all__ deliberately."
    )


def test_the_scan_is_not_vacuous():
    # If the area walk or the AST scan breaks, every assertion above passes
    # while measuring nothing.
    assert len(_areas()) >= 15
    assert _leaf_imports_via_area(), "found no leaf-via-area imports at all"


def test_disk_presence_alone_would_misclassify():
    # Pins the reason this lives in a test rather than in libs_facade_check:
    # `json/fast_clone.py` exists on disk, but the name resolves to a function.
    assert (_LIBS / "json" / "fast_clone.py").is_file()
    from odoo.libs import json as json_area

    assert not isinstance(json_area.fast_clone, types.ModuleType), (
        "odoo.libs.json.fast_clone is now a module; the shadowing that makes a "
        "disk-presence rule unsafe may be gone, in which case libs_facade_check "
        "could grow a static version of this check."
    )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
