import unittest

from lxml import etree

from odoo.tools.view_validation import (
    check_class_accessibility,
    check_fa_class_accessibility,
)


class TestRootNodeAccessibility(unittest.TestCase):
    def test_fa_class_on_a_root_element_does_not_raise(self):
        root = etree.fromstring('<form class="fa-star"><field name="name"/></form>')
        self.assertIsNone(root.getparent(), "the fixture must be a root element")

        self.assertEqual(check_class_accessibility(root, root.get("class")), [])

    def test_a_root_with_nothing_describing_it_still_warns(self):
        root = etree.fromstring('<form class="fa-star"><span/></form>')
        self.assertIsNone(root.getparent())

        warnings = check_class_accessibility(root, root.get("class"))

        self.assertEqual(len(warnings), 1)
        self.assertIn("must have title", warnings[0])

    def test_fa_class_on_a_child_element_is_unchanged(self):
        parent = etree.fromstring('<form><span class="fa-star"/></form>')
        node = parent[0]

        self.assertEqual(
            check_class_accessibility(node, node.get("class")),
            check_fa_class_accessibility(
                node, f"A <{node.tag}> with fa class ({node.get('class')})"
            ),
        )

    def test_a_root_whose_parent_text_would_have_excused_it(self):
        root = etree.fromstring('<div class="fa-star"/>')
        self.assertTrue(check_class_accessibility(root, "fa-star"))

    def test_a_child_excused_by_its_parent_text_stays_excused(self):
        parent = etree.fromstring('<div>Some label<span class="fa-star"/></div>')
        self.assertEqual(check_class_accessibility(parent[0], "fa-star"), [])
