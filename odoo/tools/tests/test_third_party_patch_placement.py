import ast
import pathlib
import unittest

_CORE = pathlib.Path(__file__).resolve().parents[3] / "odoo"

# ARCHITECTURE.md states the rule plainly under "Where to add code":
#
#     A third-party patch -> odoo/_monkeypatches/<module>.py (see its README)
#
# and `_monkeypatches/__init__.py` enforces the *shape* of what lives there (a
# callable `patch_module()`, TypeError otherwise). Nothing enforced the
# *placement*, so the rule was prose, and prose rots: measured when this test
# landed there were ELEVEN third-party patches outside _monkeypatches/ -- nine
# the scan can see and two it structurally cannot (below).
#
# This is an exact-mode pin, not a prohibition. Several of these are defensible
# where they are; what was not defensible was that nobody could tell how many
# there were, or notice a new one.
#
# LIMITATION, stated because it is load-bearing rather than incidental:
# the scan resolves the assignment target's ROOT NAME to the import that bound
# it, so it only sees patches whose root is *statically* third-party. Two real
# patches are therefore invisible to it:
#
#   tools/pdf/__init__.py:59  pypdf.filters.decompress = ...
#   tools/pdf/__init__.py:89  DictionaryObject.get = ...
#
# because that file does `from . import _pypdf as pypdf`, and
# tools/pdf/_pypdf.py re-exports the genuine `pypdf.filters` module object. The
# patch lands on third-party state through an odoo-internal re-export, so it
# reads as internal. That is the same laundering shape that hides ORM layer
# crossings behind `orm/helpers.py` and addon-model reaches behind a string key
# -- a re-export defeats a name-based check. They are listed in
# KNOWN_PATCHES below so the count is honest.

#: (path, line-ish target) -> why it is here rather than in _monkeypatches/.
KNOWN_PATCHES: dict[tuple[str, str], str] = {
    ("http/wrappers.py", "HTTPException.get_response"): (
        "Makes werkzeug's HTTPException render through Odoo's Response. Tightly "
        "bound to the wrappers module it lives in; moving it to "
        "_monkeypatches/werkzeug.py would split one behaviour across two files."
    ),
    ("http/wrappers.py", "werkzeug.exceptions.abort"): (
        "Same behaviour, same argument: abort() must raise the patched HTTPException."
    ),
    ("http/wrappers.py", "werkzeug.exceptions._odoo_original_get_response"): (
        "Not a patch but the re-entrancy guard for one: stashes the original "
        "under an `if not hasattr(...)` so a reimport does not capture the "
        "already-patched function. Moves with the two patches above."
    ),
    ("http/wrappers.py", "werkzeug.exceptions._odoo_original_abort"): (
        "The same guard for abort()."
    ),
    ("tests/common.py", "freezegun.freeze_time"): (
        "Replaces freezegun's decorator so @freeze_time also patches Odoo's own "
        "clock sources. Lives beside the replacement class it installs; a "
        "_monkeypatches/freezegun.py would be the placement the rule asks for, "
        "but the patch is only meaningful once odoo.tests is imported. DEBT, "
        "small."
    ),
    ("libs/image/utils.py", "Image._initialized"): (
        "Forces PIL to re-run plugin registration. Load-order sensitive: it has "
        "to happen after odoo's own PIL imports, which _monkeypatches' "
        "import-hook timing does not guarantee."
    ),
    ("logutils.py", "logging.RUNBOT"): (
        "Registers a custom log level. logutils IS the logging module of this "
        "codebase; _monkeypatches/logging.py would invert that."
    ),
    ("logutils.py", "logging.Logger.runbot"): "The method for the level above.",
    ("tools/config.py", "optparse._"): (
        "Neutralises optparse's gettext so option help is not translated at "
        "import time. DEBT: this is a textbook _monkeypatches/optparse.py."
    ),
    ("tools/safe_eval.py", "dateutil.tz.gettz"): (
        "Pins tz lookup for sandboxed evaluation. DEBT: belongs in "
        "_monkeypatches/dateutil.py."
    ),
    # Invisible to the scan -- see LIMITATION above. Listed so the inventory is
    # complete even though the checker cannot find them.
    ("tools/pdf/__init__.py", "pypdf.filters.decompress"): (
        "LAUNDERED through `from . import _pypdf as pypdf`. DEBT, and the "
        "re-export makes it undetectable: a _monkeypatches/pypdf.py would be "
        "both correct placement and statically visible."
    ),
    ("tools/pdf/__init__.py", "DictionaryObject.get"): (
        "LAUNDERED the same way. DEBT."
    ),
}

_SKIP_TOP = {"addons", "_monkeypatches", "upgrade"}


#: ``odoo/tests/`` is the test FRAMEWORK, not a package's test directory. The
#: "tests" path filter below is meant to skip suites (``odoo/db/tests/``,
#: ``odoo/libs/xml/tests/``...), and it was silently swallowing 6,036 lines of
#: shipped framework code with it -- including a real patch
#: (``odoo/tests/common.py``: ``freezegun.freeze_time``). Scanning it is the
#: point: that module is imported by every integration test run.
def _is_test_suite(parts: tuple[str, ...]) -> bool:
    """True for a package's own test directory, False for ``odoo/tests/**``.

    A suite is a ``tests`` directory NESTED under a package (``db/tests/``,
    ``libs/xml/tests/``). ``odoo/tests/`` is the framework and stays in scope.
    """
    return "tests" in parts[1:]


def _module_level_statements(tree: ast.Module):
    """Yield statements at module scope, descending into if/try/with only.

    A patch guarded by `try:` or `if os.name == "posix":` is still applied on
    import; a patch inside a function or class is not, and is out of scope.
    """
    stack = list(tree.body)
    while stack:
        stmt = stack.pop()
        yield stmt
        if isinstance(stmt, ast.If | ast.Try | ast.With):
            stack.extend(stmt.body)
            stack.extend(getattr(stmt, "orelse", []))
            stack.extend(getattr(stmt, "finalbody", []))
            for handler in getattr(stmt, "handlers", []):
                stack.extend(handler.body)


def _foreign_names(tree: ast.Module) -> dict[str, str]:
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("odoo"):
                    bound[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and not node.module.startswith("odoo"):
                for alias in node.names:
                    bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bound


def find_patches() -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for path in sorted(_CORE.rglob("*.py")):
        parts = path.relative_to(_CORE).parts
        if (
            parts[0] in _SKIP_TOP
            or _is_test_suite(parts)
            or path.name.startswith("test_")
        ):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        foreign = _foreign_names(tree)
        if not foreign:
            continue
        rel = path.relative_to(_CORE).as_posix()
        for stmt in _module_level_statements(tree):
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            else:
                continue
            for target in targets:
                if not isinstance(target, ast.Attribute):
                    continue
                base = target
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name) and base.id in foreign:
                    found.append((rel, ast.unparse(target), stmt.lineno))
    return found


class TestThirdPartyPatchPlacement(unittest.TestCase):
    def test_every_patch_outside_monkeypatches_is_acknowledged(self):
        found = {(rel, target) for rel, target, _ in find_patches()}
        detectable_known = {
            k for k in KNOWN_PATCHES if "LAUNDERED" not in KNOWN_PATCHES[k]
        }
        new = sorted(found - detectable_known)
        gone = sorted(detectable_known - found)
        self.assertFalse(
            new,
            f"third-party module patched at import time outside _monkeypatches/: "
            f"{new}. ARCHITECTURE.md says these belong in "
            f"odoo/_monkeypatches/<module>.py. If this one genuinely cannot "
            f"move, add it to KNOWN_PATCHES with the reason.",
        )
        self.assertFalse(
            gone,
            f"KNOWN_PATCHES lists patches that no longer exist: {gone}. Good "
            f"news -- delete the entries so the pin cannot silently bless a new "
            f"patch in the same place.",
        )

    def test_the_framework_package_is_in_scope(self):
        # odoo/tests/ is shipped framework code, not a suite. It was excluded by
        # a "tests" path filter aimed at suites, hiding a real patch for as long
        # as this checker existed.
        scanned = {rel for rel, _, _ in find_patches()}
        self.assertIn(
            "tests/common.py",
            scanned,
            "odoo/tests/ has dropped out of scope again — that is 6k lines of "
            "framework code, imported by every integration run, unscanned.",
        )

    def test_package_test_suites_stay_out_of_scope(self):
        parts_suite = ("db", "tests", "conftest.py")
        parts_framework = ("tests", "common.py")
        self.assertTrue(_is_test_suite(parts_suite))
        self.assertFalse(_is_test_suite(parts_framework))

    def test_scan_is_not_vacuous(self):
        # If the walk or the import resolution breaks, find_patches() returns []
        # and the assertion above passes while checking nothing.
        self.assertGreaterEqual(len(find_patches()), 5)

    def test_nested_module_level_blocks_are_walked(self):
        # The pdf patches sit after a try/except; an implementation that only
        # looked at tree.body would still find those, but one that stopped at
        # the first `if` would not. Pin the descent explicitly.
        tree = ast.parse(
            "import optparse\n"
            "if True:\n"
            "    try:\n"
            "        optparse.something = 1\n"
            "    except Exception:\n"
            "        pass\n"
        )
        targets = [
            ast.unparse(t)
            for stmt in _module_level_statements(tree)
            if isinstance(stmt, ast.Assign)
            for t in stmt.targets
        ]
        self.assertIn("optparse.something", targets)

    def test_function_bodies_are_out_of_scope(self):
        tree = ast.parse("import optparse\ndef f():\n    optparse.patched_here = 1\n")
        assigns = [
            s for s in _module_level_statements(tree) if isinstance(s, ast.Assign)
        ]
        self.assertEqual(assigns, [])

    def test_the_laundered_pdf_patches_are_still_there(self):
        # They cannot be detected (see LIMITATION), so assert them directly:
        # otherwise the inventory quietly drifts out of date.
        src = (_CORE / "tools" / "pdf" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("pypdf.filters.decompress =", src)
        self.assertIn("DictionaryObject.get =", src)
        self.assertIn("from . import _pypdf as pypdf", src)


if __name__ == "__main__":
    unittest.main()
