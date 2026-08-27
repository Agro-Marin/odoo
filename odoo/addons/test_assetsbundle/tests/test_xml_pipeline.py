import pathlib
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools import mute_logger
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_path

from .common import FileTouchable, asset_file, make_bundle
from odoo.addons.base.models.assetsbundle import (
    AssetsBundle,
    XMLAsset,
    XMLAssetError,
    XmlTemplatePipeline,
)
from odoo.addons.base.models.ir_qweb_assets import IrQweb

TEMPLATE_XML = "<templates><t t-name='audit.g10.tpl'><div>x</div></t></templates>"
XML_SPACE_ATTR = "{http://www.w3.org/XML/1998/namespace}space"


class TestXMLAssetsBundle(FileTouchable):
    def _get_asset(self, bundle, rtl=False, debug_assets=False):
        files, _ = self.env["ir.qweb"]._get_asset_content(bundle)
        return AssetsBundle(
            bundle, files, env=self.env, debug_assets=debug_assets, rtl=rtl
        )

    def test_01_broken_xml(self):
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.broken_xml")

            with self.assertRaisesRegex(
                XMLAssetError,
                "Invalid XML template: Opening and ending tag mismatch: SomeComponent line 4 and t, line 5, column 7' in file '/test_assetsbundle/static/invalid_src/xml/invalid_xml.xml",
            ):
                self.bundle.xml()

    def test_02_multiple_broken_xml(self):
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.multiple_broken_xml")

            with self.assertRaisesRegex(
                XMLAssetError,
                "Invalid XML template: Opening and ending tag mismatch: SomeComponent line 4 and t, line 5, column 7' in file '/test_assetsbundle/static/invalid_src/xml/invalid_xml.xml",
            ):
                self.bundle.xml()

    def test_02b_multiple_broken_xml_second_file(self):
        # multiple_broken_xml fails fast on the first bad file
        # (test_02, above), so second_invalid_xml.xml's own error is
        # otherwise never exercised. Build a bundle from that file
        # alone to assert on it too.
        path = file_path(
            "test_assetsbundle/static/invalid_src/xml/second_invalid_xml.xml"
        )
        content = pathlib.Path(path).read_text(encoding="utf-8")

        with mute_logger("odoo.addons.base.models.assetsbundle"):
            bundle = AssetsBundle(
                "test.second_invalid_xml_only",
                [asset_file("/m/static/src/second_invalid_xml.xml", content)],
                env=self.env,
            )
            with self.assertRaisesRegex(
                XMLAssetError,
                "Invalid XML template: XML declaration allowed only at the start of the document, line 2, column 6' in file '/m/static/src/second_invalid_xml.xml",
            ):
                bundle.xml()

    def test_04_template_wo_name(self):
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.wo_name")

            with self.assertRaisesRegex(
                XMLAssetError,
                "'Template name is missing.' in file '/test_assetsbundle/static/invalid_src/xml/template_wo_name.xml'",
            ):
                self.bundle.xml()

    def test_03_multiple_same_name(self):
        self.bundle = self._get_asset("test_assetsbundle.multiple_same_name")
        (block,) = self.bundle.xml()
        self.assertEqual(block["type"], "templates")
        self.assertEqual(
            [element.get("t-name") for element, _url, _key in block["templates"]],
            ["test_assetsbundle.multiple_name_xml"] * 2,
        )

    def test_05_file_not_found(self):
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.file_not_found")

            with self.assertRaisesRegex(
                XMLAssetError,
                "Could not find test_assetsbundle/static/invalid_src/xml/file_not_found.xml",
            ):
                self.bundle.xml()


class TestXmlInlineErrorPath(TransactionCase):
    def test_invalid_inherit_mode_inline(self):
        bundle = AssetsBundle("test_assetsbundle.xmlerr", [], env=self.env)
        bundle.templates.append(
            XMLAsset(
                bundle,
                inline='<templates><t t-name="x" t-inherit="p" t-inherit-mode="bogus"/></templates>',
            )
        )
        with (
            self.assertLogs("odoo.addons.base.models.assetsbundle", level="ERROR"),
            self.assertRaisesRegex(XMLAssetError, "Invalid inherit mode"),
        ):
            bundle.xml()


class TestXmlParseFailureIsCached(TransactionCase):
    def _broken_bundle(self):
        return AssetsBundle(
            "test.badxml",
            [
                asset_file(
                    "/m/static/src/a.xml", "<templates><t t-name='x'></templates>"
                )
            ],
            env=self.env,
        )

    def test_parse_is_attempted_once(self):
        asset = self._broken_bundle().templates[0]
        with patch.object(
            type(asset), "_raw_source", wraps=asset._raw_source
        ) as raw_source:
            for _ in range(4):
                with self.assertRaises(XMLAssetError):
                    _ = asset.template_elements
        self.assertEqual(raw_source.call_count, 1)

    def test_the_error_still_surfaces_every_time(self):
        asset = self._broken_bundle().templates[0]
        errors = []
        for _ in range(3):
            with self.assertRaises(XMLAssetError) as caught:
                _ = asset.template_elements
            errors.append(str(caught.exception))
        self.assertEqual(len(set(errors)), 1)
        self.assertIn("Invalid XML template", errors[0])


class TestXmlTemplateTreeImmutable(TransactionCase):
    def test_cached_tree_not_mutated(self):
        bundle = AssetsBundle(
            "test_assetsbundle.audit_g10_mut",
            [asset_file("/test/audit_g10_mut.xml", TEMPLATE_XML)],
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

    def test_xml_template_elements_shapes(self):
        from odoo.addons.base.models.assetsbundle import XMLAsset

        bundle = AssetsBundle("test.xmlshapes", [], env=self.env)
        cases = {
            '<templates><t t-name="a"/><t t-name="b"/></templates>': ["a", "b"],
            '<odoo><t t-name="c"/></odoo>': ["c"],
            '<t t-name="solo"/>': ["solo"],
        }
        for src, expected in cases.items():
            asset = XMLAsset(bundle, inline=src, url="/web/static/src/_probe.xml")
            names = [el.get("t-name") for el in asset.template_elements]
            self.assertEqual(names, expected, f"for {src!r}")
            self.assertIs(asset.template_elements, asset.template_elements)

    def test_template_elements_skip_processing_instructions(self):
        bundle = AssetsBundle("test.xmlpi", [], env=self.env)
        asset = XMLAsset(
            bundle,
            inline=(
                '<templates><?xml-stylesheet href="x"?>'
                '<t t-name="audit.pi"><div/></t></templates>'
            ),
        )
        elems = asset.template_elements
        self.assertEqual(len(elems), 1)
        self.assertEqual(elems[0].get("t-name"), "audit.pi")
        bundle.templates = [asset]
        blocks = bundle.xml()
        self.assertEqual(blocks[0]["type"], "templates")


class TestXmlBundleUrlEscaping(TransactionCase):
    def test_url_with_backtick_cannot_break_the_template_literal(self):
        files = [
            {
                "url": "/test/evil`${1 + 1}.xml",
                "filename": None,
                "content": (
                    "<templates>"
                    "<t t-name='probe.tpl'><div>${body}</div></t>"
                    "</templates>"
                ),
                "last_modified": 1.0,
            }
        ]
        bundle = AssetsBundle(
            "test_assetsbundle.urlesc", files, env=self.env, css=False, js=True
        )
        js = bundle._xml.generate_xml_bundle()
        self.assertIn(r"\${body}", js)
        self.assertNotIn("`/test/evil`", js)
        self.assertIn(json.dumps("/test/evil`${1 + 1}.xml"), js)


class TestEsmTemplateBundleForms(BaseCase):
    _TPL = '<templates><t t-name="my.module.Widget">hi</t></templates>'

    def _bundle(self):
        bundle = SimpleNamespace(name="my.bundle", env=None)
        bundle.templates = [XMLAsset(bundle, inline=self._TPL)]
        return XmlTemplatePipeline(bundle)

    def test_debug_form_uses_native_import(self):
        out = self._bundle().generate_esm_template_bundle(use_import=True)
        self.assertIn("import {", out)
        self.assertIn('from "@web/core/templates";', out)
        self.assertIn('registerTemplate("my.module.Widget"', out)

    def test_production_form_uses_loader_get(self):
        out = self._bundle().generate_esm_template_bundle(use_import=False)
        self.assertIn('odoo.loader.modules.get("@web/core/templates")', out)
        self.assertNotIn("import {", out)
        self.assertIn('registerTemplate("my.module.Widget"', out)

    def test_empty_templates_yield_empty_string(self):
        bundle = SimpleNamespace(name="my.bundle", env=None, templates=[])
        self.assertEqual(XmlTemplatePipeline(bundle).generate_esm_template_bundle(), "")


class TestTemplateBlockFollowsModuleCode(BaseCase):
    _MODULE_CODE = "console.log('module code');\n"
    _TEMPLATE_CODE = 'registerTemplate("my.module.Widget", "/u", `hi`);\n'

    def test_template_block_follows_module_code(self):
        combined = IrQweb._combine_bundle_with_templates(
            self._MODULE_CODE, self._TEMPLATE_CODE
        )
        self.assertLess(
            combined.index("module code"),
            combined.index("registerTemplate"),
            "the template block must follow the module code: boot/start.js "
            "relies on `await whenReady()` to let it run before the mount",
        )

    def test_a_sourcemap_directive_stays_last(self):
        combined = IrQweb._combine_bundle_with_templates(
            "code;\n//# sourceMappingURL=x.map\n", self._TEMPLATE_CODE
        )
        self.assertLess(
            combined.index("registerTemplate"),
            combined.index("sourceMappingURL"),
            "a sourcemap directive left mid-file detaches the map",
        )

    def test_no_templates_leaves_the_bundle_untouched(self):
        self.assertEqual(
            IrQweb._combine_bundle_with_templates(self._MODULE_CODE, ""),
            self._MODULE_CODE,
        )


class TestTemplateInheritance(TransactionCase):
    def _bundle(self, *templates):
        return make_bundle(
            self,
            "test_assetsbundle.inherit",
            *((f"/m/static/src/t{i}.xml", t) for i, t in enumerate(templates)),
            css=False,
        )

    def test_an_extension_registers_against_its_parent(self):
        bundle = self._bundle(
            '<templates><t t-name="a.Parent"><div/></t></templates>',
            '<templates><t t-name="a.Child" t-inherit="a.Parent"'
            ' t-inherit-mode="extension"><xpath expr="//div" position="inside">'
            "<span/></xpath></t></templates>",
        )
        rendered = bundle._xml.generate_xml_bundle()

        self.assertIn('registerTemplate("a.Parent"', rendered)
        self.assertIn('registerTemplateExtension("a.Parent"', rendered)
        self.assertNotIn('registerTemplate("a.Child"', rendered)

    def test_a_primary_inherit_registers_under_its_own_name(self):
        bundle = self._bundle(
            '<templates><t t-name="a.Parent"><div/></t></templates>',
            '<templates><t t-name="a.Child" t-inherit="a.Parent"'
            ' t-inherit-mode="primary"><xpath expr="//div" position="inside">'
            "<span/></xpath></t></templates>",
        )
        rendered = bundle._xml.generate_xml_bundle()

        self.assertIn('registerTemplate("a.Child"', rendered)
        self.assertNotIn("registerTemplateExtension", rendered)

    def test_a_primary_parent_from_outside_the_bundle_is_checked_at_runtime(self):
        bundle = self._bundle(
            '<templates><t t-name="a.Child" t-inherit="b.Elsewhere"'
            ' t-inherit-mode="primary"><xpath expr="//div" position="inside">'
            "<span/></xpath></t></templates>",
        )
        rendered = bundle._xml.generate_xml_bundle()

        self.assertIn("checkPrimaryTemplateParents(", rendered)
        self.assertIn("b.Elsewhere", rendered)

    def test_an_extension_with_no_parent_anywhere_reports_itself(self):
        bundle = self._bundle(
            '<templates><t t-name="a.Child" t-inherit="b.Missing"'
            ' t-inherit-mode="extension"><xpath expr="//div" position="inside">'
            "<span/></xpath></t></templates>",
        )
        rendered = bundle._xml.generate_xml_bundle()

        self.assertIn("console.error(", rendered)
        self.assertIn("Missing (extension) parent templates", rendered)
        self.assertIn("b.Missing", rendered)

    def test_a_resolved_parent_raises_no_complaint(self):
        bundle = self._bundle(
            '<templates><t t-name="a.Parent"><div/></t></templates>',
            '<templates><t t-name="a.Child" t-inherit="a.Parent"'
            ' t-inherit-mode="extension"><xpath expr="//div" position="inside">'
            "<span/></xpath></t></templates>",
        )
        rendered = bundle._xml.generate_xml_bundle()

        self.assertNotIn("console.error(", rendered)
        self.assertNotIn("checkPrimaryTemplateParents(", rendered)

    def test_a_bundle_whose_templates_render_to_nothing_yields_no_module(self):
        bundle = AssetsBundle(
            "test_assetsbundle.inherit_empty",
            [asset_file("/m/static/src/t.xml", "<templates/>")],
            env=self.env,
            css=False,
        )
        self.assertTrue(bundle.templates, "precondition: there IS an xml asset")
        self.assertEqual(bundle._xml.generate_esm_template_bundle(), "")
