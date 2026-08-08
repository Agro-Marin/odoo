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

#: Names a file binds to the package itself. ``db_mod`` is this suite's fixture;
#: the addon suites use ``db``/``db_service`` from ``from odoo.service import
#: db``. Detected per file rather than hard-coded, because the first version of
#: this gate knew only ``db_mod`` and so missed
#: ``patch.object(db_service, "_drop_database")`` in
#: ``addons/base/tests/test_db_service_drop.py`` — which broke against a real
#: database, not here.
_ALIAS_BINDING = re.compile(
    r"^\s*(?:import\s+odoo\.service\.db\s+as\s+(\w+)"
    r"|from\s+odoo\.service\s+import\s+db(?:\s+as\s+(\w+))?)",
    re.MULTILINE,
)


def _package_aliases(text: str) -> set[str]:
    names = {"db_mod"} if "def db_mod(" in text or "db_mod" in text else set()
    for m in _ALIAS_BINDING.finditer(text):
        names.add(m.group(1) or m.group(2) or "db")
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


def _sources():
    for root in SCANNED:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if path.resolve() == _HERE:
                continue  # this file quotes the bad forms as examples
            yield path, path.read_text(encoding="utf-8", errors="replace")


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
    assert list(_object_targets('db_mod\npatch.object(db_mod, "_drop_database")'))
    assert list(
        _object_targets(
            'db_mod\nmonkeypatch.setattr(db_mod, "_STDERR_DRAIN_JOIN_S", 1)'
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
