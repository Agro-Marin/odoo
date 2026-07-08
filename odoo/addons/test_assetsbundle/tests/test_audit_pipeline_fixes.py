"""Regressions for the 2026-07 assetsbundle pipeline audit batch.

Pins the ASI-defusing join between the last legacy JS file and the template
IIFE (production and debug bodies), autoprefixing of plain ``.css`` assets in
an ``autoprefix`` bundle (the artifact URL claimed it; only Sass output got
it), the ``for_inline_compile`` constructor for bundle-less SCSS compiles,
the tool-named / decode-safe ``_run_cli_pipe`` failures, and the immutability
of the cached XML template parse tree across serialization.
"""

import re

from odoo.tests.common import BaseCase, TransactionCase

from odoo.addons.base.models.assetsbundle import (
    AssetsBundle,
    CompileError,
    ScssStylesheetAsset,
    WebAsset,
)
from odoo.addons.base.models.assetsbundle.common import _run_cli_pipe

XML_SPACE_ATTR = "{http://www.w3.org/XML/1998/namespace}space"

TEMPLATE_XML = "<templates><t t-name='audit.g10.tpl'><div>x</div></t></templates>"
# The last statement deliberately ends WITHOUT a semicolon: under ASI a
# parenthesized expression appended next — the template IIFE — parses as a
# CALL of the dangling expression unless the bundler inserts a ";".
UNTERMINATED_JS = "window.auditG10 = window.auditG10Src\n"


def _file(url, content, last_modified=1.0):
    """Build the files-dict entry shape produced by ir_qweb._get_asset_content."""
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


class TestTemplateIifeAsiGuard(TransactionCase):
    """The template IIFE joins the concatenation with ";", like every file.

    The per-file join is ``";\\n"`` precisely to defuse ASI, but the legacy
    template IIFE used to be appended bare: a last file ending in an
    unterminated expression silently CALLED the IIFE with itself as callee.
    """

    def _bundle(self, name, debug=False):
        return AssetsBundle(
            name,
            [
                _file("/test/audit_g10_asi.js", UNTERMINATED_JS),
                _file("/test/audit_g10_asi.xml", TEMPLATE_XML),
            ],
            env=self.env,
            css=False,
            debug_assets=debug,
        )

    def _assert_no_call_expression(self, content):
        # Erase block comments the way a JS parser skips them; the dangling
        # expression must NOT be followed by "(" — that reads as a call of
        # the template IIFE with the expression as callee.
        code = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        self.assertIsNone(
            re.search(r"auditG10Src\s*\(", code),
            "the template IIFE forms a call expression with the last file",
        )

    def test_minified_bundle_defuses_asi(self):
        content = self._bundle("test_assetsbundle.audit_g10_asi_min").js().raw.decode()
        self.assertIn("(function()", content, "template IIFE missing")
        self.assertIn("window.auditG10=window.auditG10Src;", content)
        self._assert_no_call_expression(content)

    def test_debug_bundle_defuses_asi(self):
        content = (
            self._bundle("test_assetsbundle.audit_g10_asi_dbg", debug=True)
            .js()
            .raw.decode()
        )
        self.assertIn("(function()", content, "template IIFE missing")
        self.assertRegex(content, r"auditG10Src\s*;")
        self._assert_no_call_expression(content)


class TestPlainCssAutoprefix(TransactionCase):
    """Plain ``.css`` assets in an ``autoprefix`` bundle get prefixed too.

    The artifact URL (``.autoprefixed``) and ``unique_descriptor`` claim the
    whole bundle is prefixed, but ``_autoprefix_css`` used to run only on the
    Sass-compiled output — plain CSS assets were never prefixed.
    """

    PLAIN_CSS = ".audit-g10-plain { appearance: none; }"

    def _bundle(self, debug=False):
        return AssetsBundle(
            "test_assetsbundle.audit_g10_prefix",
            [_file("/test/audit_g10_prefix.css", self.PLAIN_CSS)],
            env=self.env,
            js=False,
            autoprefix=True,
            debug_assets=debug,
        )

    def test_plain_css_prefixed_in_production(self):
        content = self._bundle().css().raw.decode()
        self.assertIn(
            "-webkit-appearance:none;-moz-appearance:none;appearance:none", content
        )

    def test_plain_css_prefixed_in_debug(self):
        # The debug body is rebuilt from each asset's ``content`` by
        # ``CssPipeline.sourcemap_bundle`` — it must carry the prefixes too.
        content = self._bundle(debug=True).css().raw.decode()
        self.assertIn("-webkit-appearance:none", content)

    def test_mixed_bundle_scss_not_double_prefixed(self):
        files = [
            _file("/test/audit_g10_mix.scss", ".mix-scss { appearance: none; }"),
            _file("/test/audit_g10_mix.css", ".mix-css { appearance: none; }"),
        ]
        bundle = AssetsBundle(
            "test_assetsbundle.audit_g10_mix",
            files,
            env=self.env,
            js=False,
            autoprefix=True,
        )
        content = bundle.css().raw.decode()
        # The exact single-prefix shape: a second autoprefix pass over the
        # compiled Sass fragment would re-expand the bare ``appearance`` and
        # break the closed ``{...}`` sequence.
        self.assertRegex(
            content,
            r"\.mix-scss\{-webkit-appearance:none;"
            r"-moz-appearance:none;appearance:none\}",
        )
        self.assertRegex(
            content,
            r"\.mix-css\{-webkit-appearance:none;"
            r"-moz-appearance:none;appearance:none[;}]",
        )


class TestForInlineCompile(TransactionCase):
    """``for_inline_compile`` is the one sanctioned bundle-less construction."""

    def test_compiles_standalone_scss(self):
        asset = ScssStylesheetAsset.for_inline_compile("// preview")
        css = asset.compile("$c: red;\nbody { color: $c; }")
        # bundle=None selects the production "compressed" output style.
        self.assertIn("body{color:red}", css)

    def test_no_content_error_survives_missing_bundle(self):
        # The inline-or-url ValueError itself used to crash on bundle.name
        # when bundle was None — the guard must name the failure instead.
        with self.assertRaisesRegex(ValueError, "<no bundle>"):
            WebAsset(None)


class TestRunCliPipeFailures(BaseCase):
    """Non-zero exits name the tool; non-UTF-8 output degrades, not raises."""

    def test_nonzero_exit_names_the_tool(self):
        with self.assertRaises(CompileError) as ctx:
            _run_cli_pipe(["false"], "", 10)
        message = str(ctx.exception)
        self.assertIn("'false'", message)
        self.assertIn("return code 1", message)

    def test_non_utf8_output_degrades_to_replacement(self):
        # errors="replace": invalid bytes must not surface as a
        # UnicodeDecodeError that bypasses every caller's CompileError policy.
        with self.assertRaises(CompileError) as ctx:
            _run_cli_pipe(["sh", "-c", "printf '\\377\\376 broken'; exit 3"], "", 10)
        message = str(ctx.exception)
        self.assertIn("'sh'", message)
        self.assertIn("broken", message)

    def test_non_utf8_success_output_degrades(self):
        out = _run_cli_pipe(["sh", "-c", "printf '\\377 ok'"], "", 10)
        self.assertIn("ok", out)


class TestXmlTemplateTreeImmutable(TransactionCase):
    """Serialization stamps xml:space on a COPY, not the cached parse tree."""

    def test_cached_tree_not_mutated(self):
        bundle = AssetsBundle(
            "test_assetsbundle.audit_g10_mut",
            [_file("/test/audit_g10_mut.xml", TEMPLATE_XML)],
            env=self.env,
            css=False,
        )
        rendered = bundle._xml.generate_xml_bundle()
        self.assertIn('xml:space="preserve"', rendered)
        (asset,) = bundle.templates
        for element in asset.template_elements:
            self.assertIsNone(
                element.get(XML_SPACE_ATTR),
                "get_template mutated the cached template element",
            )
