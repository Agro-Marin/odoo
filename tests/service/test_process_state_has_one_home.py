import ast
import pathlib
import re

import pytest

import odoo

ROOT = pathlib.Path(odoo.__file__).parent
SINGLETONS = ("server", "server_phoenix")

# The state module itself, and the accessors it publishes.
HOME = ROOT / "service" / "_process_state.py"


def _python_files():
    for path in ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or path == HOME:
            continue
        yield path


@pytest.fixture(scope="module")
def sources():
    return [(p, p.read_text(encoding="utf-8")) for p in _python_files()]


class TestNoOtherModuleBindsThem:
    def test_no_module_assigns_a_module_level_server_or_phoenix(self, sources):
        bad = []
        for path, text in sources:
            if "server_phoenix" not in text and not re.search(
                r"^server\b", text, re.MULTILINE
            ):
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in tree.body:
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else [node.target]
                    if isinstance(node, ast.AnnAssign)
                    else []
                )
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in SINGLETONS:
                        rel = path.relative_to(ROOT.parent)
                        bad.append(f"{rel}:{node.lineno} binds {target.id}")
        assert not bad, (
            "a second module-level binding is a second answer the moment either "
            "is written:\n  " + "\n  ".join(bad)
        )


class TestEveryReaderGoesThroughTheModule:
    _DOTTED = re.compile(r"\b(?:odoo\.service\.)?lifecycle\.(server_phoenix|server)\b")
    _FROM = re.compile(
        r"^\s*from\s+(?:odoo\.service\.)?lifecycle\s+import\s+.*\b(server|server_phoenix)\b",
        re.MULTILINE,
    )

    def test_nobody_still_reads_them_off_lifecycle(self, sources):
        """`lifecycle.server` is where they used to live, and two call sites
        outside tests/service kept reading it there after the move -- one in
        HttpCase, which broke every HTTP test's setUpClass."""
        bad = [
            f"{path.relative_to(ROOT.parent)}:"
            f"{text[: m.start()].count(chr(10)) + 1} {m.group(0).strip()}"
            for path, text in sources
            for pattern in (self._DOTTED, self._FROM)
            for m in pattern.finditer(text)
        ]
        assert not bad, (
            "these read the singletons off `lifecycle`, where they no longer "
            "are:\n  " + "\n  ".join(bad)
        )

    def test_a_from_import_of_the_singleton_is_refused_anywhere(self, sources):
        """`from ... import server` freezes whatever it was at import time."""
        pattern = re.compile(
            r"^\s*from\s+[\w.]*_process_state\s+import\s+.*\b(server|server_phoenix)\b",
            re.MULTILINE,
        )
        bad = [
            f"{path.relative_to(ROOT.parent)}: {m.group(0).strip()}"
            for path, text in sources
            for m in pattern.finditer(text)
        ]
        assert not bad, (
            "bind the module and read the attribute; a name imported before "
            "start() runs is None forever:\n  " + "\n  ".join(bad)
        )


class TestTheHomeStillPublishesThem:
    def test_the_module_defines_both_and_their_setters(self):
        from odoo.service import _process_state

        for name in SINGLETONS:
            assert hasattr(_process_state, name)
        assert callable(_process_state.set_server)
        assert callable(_process_state.set_phoenix)

    def test_the_setters_are_what_writes_reach_for(self, sources):
        """A bare `global server_phoenix` outside the home is the old shape."""
        bad = [
            str(path.relative_to(ROOT.parent))
            for path, text in sources
            if re.search(r"^\s*global\s+(server|server_phoenix)\b", text, re.MULTILINE)
        ]
        assert not bad, bad
