import unittest

from odoo.tools.assets.esm_graph import (
    _TRANSITIVE_IMPORT_RE,
    _scan_import_specifiers,
    find_escaping_relative_imports,
)
from odoo.tools.assets.esm_lexer import lex_module

SOURCE = """
import { a } from "./sibling";
export { b } from "../outside/thing";
export * from "../outside/star";
export const c = 1;
"""


class _Module:
    module_path = "@web/dir/mod"
    url = "/web/static/src/dir/mod.js"
    raw_content = SOURCE


class TestNamedReExportsAreSeen(unittest.TestCase):
    def test_the_regex_half_carries_named_re_exports(self):
        specs = {
            m.group("spec") or m.group("side")
            for m in _TRANSITIVE_IMPORT_RE.finditer(SOURCE)
        }
        self.assertIn("../outside/thing", specs)

    def test_the_lexer_alone_would_drop_them(self):
        lexed = lex_module(SOURCE)
        if lexed is None:
            self.skipTest("no node on PATH; the lexer half cannot be exercised")
        lexer_only = {imp["n"] for imp in lexed["imports"]}
        lexer_only.update(lexed.get("starFrom") or ())
        self.assertNotIn(
            "../outside/thing",
            lexer_only,
            "if the worker starts reporting named re-exports, the union in "
            "_scan_import_specifiers is merely redundant rather than load-bearing",
        )
        self.assertIn("../outside/star", lexer_only)

    def test_the_scan_reports_every_static_specifier(self):
        self.assertEqual(
            _scan_import_specifiers(SOURCE),
            {"./sibling", "../outside/thing", "../outside/star"},
        )

    def test_an_escaping_named_re_export_is_reported(self):
        escapes = find_escaping_relative_imports([_Module()])
        self.assertIn(
            "../outside/thing",
            {spec for _path, spec, _resolved in escapes},
            "the escape this check exists to find",
        )
