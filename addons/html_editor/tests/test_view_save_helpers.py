import copy

from lxml import etree
from lxml import html as lxml_html

from odoo.tests import TransactionCase, tagged


def _xml(fragment):
    return etree.fromstring(fragment)


@tagged("post_install", "-at_install")
class TestViewSaveHelpers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.View = cls.env["ir.ui.view"]


    def test_editing_attributes_are_stripped(self):
        element = lxml_html.fromstring(
            '<div class="a o_editable b" contenteditable="true"'
            ' data-oe-model="m" data-oe-id="3" style="color:red">x</div>'
        )
        cleaned = self.View._get_cleaned_non_editing_attributes(element.attrib.items())
        self.assertNotIn("data-oe-model", cleaned)
        self.assertNotIn("data-oe-id", cleaned)
        self.assertNotIn("contenteditable", cleaned)
        self.assertEqual(cleaned["class"], "a b")
        self.assertEqual(cleaned["style"], "color:red")

    def test_explicitly_disabled_contenteditable_is_kept(self):
        element = lxml_html.fromstring(
            '<div class="keepme" contenteditable="false">y</div>'
        )
        cleaned = self.View._get_cleaned_non_editing_attributes(element.attrib.items())
        self.assertEqual(cleaned["contenteditable"], "false")
        self.assertEqual(cleaned["class"], "keepme")


    def test_archs_equal_ignores_attribute_order(self):
        self.assertTrue(
            self.View._are_archs_equal(
                _xml('<a class="c" id="i"><b/></a>'),
                _xml('<a id="i" class="c"><b/></a>'),
            )
        )

    def test_archs_differ_on_tag_text_or_children(self):
        self.assertFalse(self.View._are_archs_equal(_xml("<a/>"), _xml("<z/>")))
        self.assertFalse(
            self.View._are_archs_equal(_xml("<a>t1</a>"), _xml("<a>t2</a>"))
        )
        self.assertFalse(
            self.View._are_archs_equal(_xml("<a><b/></a>"), _xml("<a><b/><c/></a>"))
        )

    def test_archs_compare_recursively(self):
        self.assertFalse(
            self.View._are_archs_equal(
                _xml("<a><b><c>deep</c></b></a>"),
                _xml("<a><b><c>other</c></b></a>"),
            )
        )


    def test_field_ref_drops_branding_and_restores_t_field(self):
        element = lxml_html.fromstring(
            '<span data-oe-expression="rec.name" data-oe-model="m" class="k">txt</span>'
        )
        result = self.View.to_field_ref(element)
        self.assertEqual(result.get("t-field"), "rec.name")
        self.assertEqual(result.get("class"), "k")
        self.assertIsNone(result.get("data-oe-model"))

    def test_empty_oe_structure_keeps_attributes_only(self):
        element = lxml_html.fromstring(
            '<div class="s" data-oe-type="html">hola<b>x</b></div>'
        )
        result = self.View.to_empty_oe_structure(element)
        self.assertEqual(result.get("class"), "s")
        self.assertEqual(len(result), 0)
        self.assertFalse(result.text)


    def _view(self):
        return self.env["ir.ui.view"].create(
            {
                "name": "Editable view",
                "type": "qweb",
                "arch": '<div><section class="old" id="s">'
                "<p>before</p></section></div>",
            }
        )

    def test_replacement_swaps_content_and_allowed_attributes(self):
        view = self._view()
        replacement = _xml(
            '<section class="new" style="color:red"><p>after</p></section>'
        )
        arch = view.replace_arch_section("//section", replacement)
        section = arch.xpath("//section")[0]
        self.assertEqual(section.get("class"), "new")
        self.assertEqual(section.get("style"), "color:red")
        self.assertEqual(section.get("id"), "s")
        self.assertEqual([child.text for child in section], ["after"])

    def test_replacement_removes_allowed_attributes_left_out(self):
        view = self._view()
        replacement = _xml("<section><p>after</p></section>")
        arch = view.replace_arch_section("//section", replacement)
        section = arch.xpath("//section")[0]
        self.assertIsNone(section.get("class"))
        self.assertEqual(section.get("id"), "s")

    def test_replacement_without_xpath_targets_the_root(self):
        view = self._view()
        replacement = _xml("<div><span>root content</span></div>")
        arch = view.replace_arch_section(None, replacement)
        self.assertEqual(arch.tag, "div")
        self.assertEqual([child.tag for child in arch], ["span"])

    def test_replacement_does_not_mutate_the_stored_arch(self):
        view = self._view()
        before = view.arch
        replacement = _xml("<section><p>after</p></section>")
        view.replace_arch_section("//section", copy.deepcopy(replacement))
        self.assertEqual(view.arch, before)
