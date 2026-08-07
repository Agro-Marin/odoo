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
UNTERMINATED_JS = "window.auditG10 = window.auditG10Src\n"


def _file(url, content, last_modified=1.0):
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


class TestTemplateIifeAsiGuard(TransactionCase):
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
    def test_compiles_standalone_scss(self):
        asset = ScssStylesheetAsset.for_inline_compile("// preview")
        css = asset.compile("$c: red;\nbody { color: $c; }")
        self.assertIn("body{color:red}", css)

    def test_no_content_error_survives_missing_bundle(self):
        with self.assertRaisesRegex(ValueError, "<no bundle>"):
            WebAsset(None)


class TestRunCliPipeFailures(BaseCase):
    def test_nonzero_exit_names_the_tool(self):
        with self.assertRaises(CompileError) as ctx:
            _run_cli_pipe(["false"], "", 10)
        message = str(ctx.exception)
        self.assertIn("'false'", message)
        self.assertIn("return code 1", message)

    def test_non_utf8_output_degrades_to_replacement(self):
        with self.assertRaises(CompileError) as ctx:
            _run_cli_pipe(["sh", "-c", "printf '\\377\\376 broken'; exit 3"], "", 10)
        message = str(ctx.exception)
        self.assertIn("'sh'", message)
        self.assertIn("broken", message)

    def test_non_utf8_success_output_degrades(self):
        out = _run_cli_pipe(["sh", "-c", "printf '\\377 ok'"], "", 10)
        self.assertIn("ok", out)


class TestXmlTemplateTreeImmutable(TransactionCase):
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
