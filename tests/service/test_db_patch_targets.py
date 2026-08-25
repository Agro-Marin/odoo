"""A patch aimed at ``odoo.service.db`` itself is a patch that does nothing.

``service/db.py`` used to be one module, so ``patch("odoo.service.db.X")`` and
``patch.object(db_mod, "X")`` reached the definition every caller used. It is a
package now (ADR-0014), and the names on ``__init__`` are **re-exports**:
rebinding one leaves ``lifecycle.X`` — the binding the code actually calls —
untouched.

Sometimes that fails loudly (the package has no ``subprocess``, so
``patch.object`` raises ``AttributeError``). The dangerous half is silent:
``_create_empty_database`` *is* on the package, so patching it succeeds, does
nothing, and ``restore_db`` runs the real one against a real cluster while the
test reports green. That happened while doing the split — seven tests began
failing with ``KeyError: 'db_app_name'`` because a patch aimed at
``lifecycle._create_empty_database`` never reached ``restore``'s own bound name.
Those failed loudly only because the real function needed config the mock did
not have; a cheaper function would have gone unnoticed.

So: patch the module that *uses* the name. This checks that every patch target
in the tree does.
"""

import ast
import functools
import pathlib
import re

import pytest

_HERE = pathlib.Path(__file__).resolve()


def _repo_root() -> pathlib.Path:
    for parent in _HERE.parents:
        if (parent / "odoo-bin").is_file():
            return parent
    raise RuntimeError("no odoo-bin marker above this test")


ROOT = _repo_root()
PKG = ROOT / "odoo" / "service" / "db"
SUBMODULES = frozenset(p.stem for p in PKG.glob("*.py") if p.stem != "__init__")

#: Where a patch string may point. Anything else is aimed at the package.
_STRING_TARGET = re.compile(r'["\']odoo\.service\.db\.([A-Za-z_][\w.]*)["\']')

#: Names a file binds to the package itself. The addon suites use
#: ``db``/``db_service`` from ``from odoo.service import db``. Detected per file
#: rather than hard-coded, because the first version of this gate knew only
#: ``db_mod`` and so missed ``patch.object(db_service, "_drop_database")`` in
#: ``addons/base/tests/test_db_service_drop.py`` — which broke against a real
#: database, not here.
_ALIAS_BINDING = re.compile(
    r"^\s*(?:import\s+odoo\.service\.db\s+as\s+(\w+)"
    r"|from\s+odoo\.service\s+import\s+db(?:\s+as\s+(\w+))?)",
    re.MULTILINE,
)

#: A fixture that RETURNS the package binds it too, e.g. this suite's
#: ``def db_mod(): import odoo.service.db as mod; return mod``. Matched on the
#: import inside the body rather than on the fixture's NAME: ``db_mod`` was
#: hard-coded here, and ``test_dump_scanner.py`` deliberately binds that same
#: name to ``_dump_scanner`` (its fixture docstring says so), so a correct
#: ``patch.object(db_mod, "_assert_dump_sql_safe")`` there would have been
#: rejected with advice — "use <alias>.<submodule>" — that means nothing for a
#: module which has none.
_FIXTURE_BINDING = re.compile(
    r"^def\s+(\w+)\([^)]*\):(?:(?!\n(?:def|class)\s).)*?"
    r"import\s+odoo\.service\.db\b",
    re.MULTILINE | re.DOTALL,
)


def _package_aliases(text: str) -> set[str]:
    names = {m.group(1) or m.group(2) or "db" for m in _ALIAS_BINDING.finditer(text)}
    names.update(m.group(1) for m in _FIXTURE_BINDING.finditer(text))
    return names


def _object_targets(text: str):
    """``patch.object(<alias>, "name")`` / ``monkeypatch.setattr(<alias>, "name", …)``."""
    for alias in _package_aliases(text):
        pattern = re.compile(
            r"(?:patch\.object|monkeypatch\.setattr)\(\s*"
            + re.escape(alias)
            + r"\s*,\s*[\"']([A-Za-z_]\w*)[\"']"
        )
        yield from pattern.finditer(text)


#: Trees that may patch this package. Kept explicit so a new one is a decision.
SCANNED = (
    ROOT / "tests" / "service",
    ROOT / "odoo" / "addons",
    ROOT / "addons",
)

#: Package-level names it is CORRECT to patch, because the production caller
#: reads them off the package at call time rather than binding them.
#: ``web/controllers/database.py`` does ``from odoo.service import db`` and then
#: ``db.check_super(...)``; ``http/helpers.py`` does ``odoo.service.db.list_dbs``;
#: ``http/_serve.py`` imports ``list_dbs`` inside the function, which re-reads the
#: package attribute per call. Patching the package is what those need.
PACKAGE_LEVEL_OK = frozenset(
    {"check_super", "restore_db", "list_dbs", "dispatch", "dump_db"}
)


#: Cheap precondition for BOTH detectors, and strictly weaker than either: a
#: string target must spell ``odoo.service.db``, and an alias binding must spell
#: ``odoo.service``. Filtering on it therefore cannot change a verdict — it only
#: stops the scan regex-ing 64 MB to find the handful of files that can match.
_MIGHT_MATCH = "odoo.service"


@functools.cache
def _sources() -> tuple[tuple[pathlib.Path, str], ...]:
    """Every candidate file, read ONCE per process and shared by all tests.

    Each of the three tests below used to walk and read the whole of
    ``tests/service``, ``odoo/addons`` and ``addons`` for itself: 9 409 files,
    64.2 MB, three times, of which 53 can possibly match. That was ~7.3 of the
    service suite's ~14.8 CPU-seconds; caching plus the pre-filter returns about
    5 of them.
    """
    out = []
    for root in SCANNED:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if path.resolve() == _HERE:
                continue  # this file quotes the bad forms as examples
            text = path.read_text(encoding="utf-8", errors="replace")
            if _MIGHT_MATCH in text:
                out.append((path, text))
    return tuple(out)


@functools.cache
def _module_uses(sub: str, name: str) -> bool:
    """Does ``odoo.service.db.<sub>`` actually bind *name*?"""
    tree = ast.parse((PKG / f"{sub}.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
        elif isinstance(node, ast.Import):
            if any((a.asname or a.name).split(".")[0] == name for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if any((a.asname or a.name) == name for a in node.names):
                return True
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return True
    return False


def test_the_package_is_a_package():
    assert SUBMODULES, "odoo/service/db/ has no submodules; the split was undone"
    assert {"lifecycle", "dump", "restore", "listing", "rpc"} == SUBMODULES


def test_no_string_patch_aims_at_the_package():
    bad = []
    for path, text in _sources():
        for m in _STRING_TARGET.finditer(text):
            head = m.group(1).split(".")[0]
            if head in SUBMODULES or head in PACKAGE_LEVEL_OK:
                continue
            line = text[: m.start()].count("\n") + 1
            bad.append(f"{path.relative_to(ROOT)}:{line} -> {m.group(0)}")
    assert not bad, (
        "patch target(s) aimed at the odoo.service.db package rather than the "
        "module that uses the name. The package re-exports it, so the patch "
        "binds an alias and the real call site is untouched — silently:\n  "
        + "\n  ".join(bad)
        + "\n\nUse odoo.service.db.<lifecycle|dump|restore|listing|rpc>.<name>, "
        "or add the name to PACKAGE_LEVEL_OK with the caller that justifies it."
    )


def test_no_object_patch_aims_at_the_package():
    bad = []
    for path, text in _sources():
        for m in _object_targets(text):
            if m.group(1) in PACKAGE_LEVEL_OK:
                continue
            line = text[: m.start()].count("\n") + 1
            bad.append(f"{path.relative_to(ROOT)}:{line} -> {m.group(1)}")
    assert not bad, (
        "patch.object/setattr aimed at the odoo.service.db package (under "
        "whatever name the file binds it to). The name there is a re-export, so "
        "the patch binds an alias and the real call site is untouched. Use "
        "<alias>.<submodule>:\n  " + "\n  ".join(bad)
    )


def test_every_submodule_target_is_real():
    """A target naming a module that does not bind the name patches nothing."""
    bad = []
    for path, text in _sources():
        for m in _STRING_TARGET.finditer(text):
            parts = m.group(1).split(".")
            if parts[0] not in SUBMODULES or len(parts) < 2:
                continue
            if not _module_uses(parts[0], parts[1]):
                line = text[: m.start()].count("\n") + 1
                bad.append(f"{path.relative_to(ROOT)}:{line} -> {m.group(0)}")
        for m in re.finditer(
            r"patch\.object\(\s*db_mod\.(\w+)\s*,\s*[\"'](\w+)[\"']", text
        ):
            if m.group(1) in SUBMODULES and not _module_uses(m.group(1), m.group(2)):
                line = text[: m.start()].count("\n") + 1
                bad.append(f"{path.relative_to(ROOT)}:{line} -> {m.group(0)}")
    assert not bad, (
        "patch target(s) naming a submodule that does not bind the name — the "
        "patch would create the attribute and nothing would read it:\n  "
        + "\n  ".join(bad)
    )


def test_the_guard_would_catch_a_regression():
    """Non-vacuity: the detectors must fire on the forms they exist to reject."""
    assert _STRING_TARGET.search('patch("odoo.service.db._create_empty_database")')
    # A fixture that RETURNS the package binds it, whatever the fixture is called.
    db_mod_fixture = (
        "def db_mod():\n    import odoo.service.db as mod\n    return mod\n"
    )
    assert list(
        _object_targets(db_mod_fixture + 'patch.object(db_mod, "_drop_database")')
    )
    assert list(
        _object_targets(
            db_mod_fixture + 'monkeypatch.setattr(db_mod, "_STDERR_DRAIN_JOIN_S", 1)'
        )
    )
    # ...and the NAME alone does not, or the gate rejects correct code. Verified
    # against the real thing: test_dump_scanner.py binds ``db_mod`` to
    # ``_dump_scanner``, and a patch through it must not be flagged.
    assert not list(
        _object_targets(
            "def db_mod():\n"
            "    return _dump_scanner\n"
            'patch.object(db_mod, "_assert_dump_sql_safe")'
        )
    )
    # The alias form the first version of this gate missed entirely.
    assert list(
        _object_targets(
            "from odoo.service import db as db_service\n"
            'patch.object(db_service, "_drop_database")'
        )
    )
    assert not list(
        _object_targets(
            "from odoo.service import db as db_service\n"
            'patch.object(db_service.lifecycle, "_drop_database")'
        )
    )
    assert _module_uses("lifecycle", "_create_empty_database")
    assert not _module_uses("listing", "_create_empty_database")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
