"""Regression coverage for `ir.ui.view` (base module audit, Tranche 4).

Covers audit finding IUV-T2: the tail-text re-attachment performed by the
node-removal branch of `_postprocess_access_rights`
(`models/ir_ui_view.py:1647-1655`). When a node carrying a `__groups_key__`
the current user cannot access is removed, its XML tail text must be moved to
the previous sibling's tail (or, for a first child, to the parent's text) so
that surrounding non-whitespace text is neither orphaned nor duplicated.
"""

from lxml import etree

from odoo.tests import common, tagged
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestViewTailText(common.TransactionCase):
    """Assert `_postprocess_access_rights` re-attaches tail text on node removal."""

    @classmethod
    def setUpClass(cls):
        """Create a restricted user and resolve the restricted group key."""
        super().setUpClass()
        cls.View = cls.env["ir.ui.view"]
        # A user with only the internal-user group: lacks base.group_system.
        cls.restricted_user = new_test_user(
            cls.env,
            login="tailtext_restricted",
            groups="base.group_user",
        )
        # The __groups_key__ value the code expects on a guarded node.
        # _postprocess_view stamps this same key (groups.key) at :1844 and
        # _postprocess_access_rights resolves it via from_key() at :1641.
        group_definitions = cls.env["res.groups"]._get_group_definitions()
        cls.restricted_key = group_definitions.parse("base.group_system").key
        # Sanity check: the restricted user does not satisfy the key, so the
        # guarded node will be removed by _postprocess_access_rights.
        assert not group_definitions.from_key(cls.restricted_key).matches(
            cls.restricted_user._get_group_ids()
        )

    def _postprocess_as_restricted(self, tree):
        """Run `_postprocess_access_rights` as the restricted user.

        :param _Element tree: the arch tree to filter in place.
        :return: the same (mutated) tree.
        :rtype: _Element
        """
        view = self.View.with_user(self.restricted_user)
        return view._postprocess_access_rights(tree)

    def test_middle_node_removal_reattaches_tail_to_previous(self):
        """Removing a guarded middle sibling moves its tail to the previous one."""
        # <root>A<a/>B<b __groups_key__/>C<c/>D</root>
        # The guarded <b> carries the non-whitespace tail "C". After removal
        # that text must land on <a>'s tail, giving "A<a/>BC<c/>D".
        root = etree.Element("root")
        root.text = "A"
        a = etree.SubElement(root, "a")
        a.tail = "B"
        b = etree.SubElement(root, "b")
        b.set("__groups_key__", self.restricted_key)
        b.tail = "C"
        c = etree.SubElement(root, "c")
        c.tail = "D"

        self._postprocess_as_restricted(root)

        # The guarded node is gone, the others survive.
        self.assertEqual([child.tag for child in root], ["a", "c"])
        self.assertIsNone(root.find("b"))
        # Tail of the removed node was appended to the previous sibling's tail.
        self.assertEqual(root.find("a").tail, "BC")
        # The following sibling keeps its own tail unchanged (no duplication).
        self.assertEqual(root.find("c").tail, "D")
        self.assertEqual(root.text, "A")
        # The text content is preserved exactly once, in order.
        self.assertEqual("".join(root.itertext()), "ABCD")

    def test_first_node_removal_reattaches_tail_to_parent_text(self):
        """Removing a guarded first child moves its tail to the parent text."""
        # <root>HEAD<a __groups_key__/>MID<b/>TAIL</root>
        # <a> has no previous sibling, so its tail "MID" must be appended to
        # root.text, yielding "HEADMID<b/>TAIL".
        root = etree.Element("root")
        root.text = "HEAD"
        a = etree.SubElement(root, "a")
        a.set("__groups_key__", self.restricted_key)
        a.tail = "MID"
        b = etree.SubElement(root, "b")
        b.tail = "TAIL"

        self._postprocess_as_restricted(root)

        self.assertEqual([child.tag for child in root], ["b"])
        # No previous sibling: tail merged into the parent's leading text.
        self.assertEqual(root.text, "HEADMID")
        self.assertEqual(root.find("b").tail, "TAIL")
        self.assertEqual("".join(root.itertext()), "HEADMIDTAIL")

    def test_removal_without_tail_leaves_neighbours_untouched(self):
        """Removing a guarded node with no tail does not alter sibling text."""
        # The `if tail:` guard at :1651 must skip the re-attachment when the
        # removed node has no (falsy) tail, leaving the previous sibling intact.
        root = etree.Element("root")
        root.text = "X"
        a = etree.SubElement(root, "a")
        a.tail = "Y"
        b = etree.SubElement(root, "b")
        b.set("__groups_key__", self.restricted_key)
        # b.tail intentionally left as None (no tail to re-attach).
        c = etree.SubElement(root, "c")
        c.tail = "Z"

        self._postprocess_as_restricted(root)

        self.assertEqual([child.tag for child in root], ["a", "c"])
        # Previous sibling tail unchanged: nothing was appended.
        self.assertEqual(root.find("a").tail, "Y")
        self.assertEqual(root.find("c").tail, "Z")
        self.assertEqual("".join(root.itertext()), "XYZ")

    def test_consecutive_guarded_nodes_accumulate_tails(self):
        """Two consecutive guarded nodes fold both tails onto one survivor."""
        # <root>P<a/>Q<b __groups_key__/>R<c __groups_key__/>S<d/>T</root>
        # Both <b> and <c> are removed in document order. <b>'s tail "R" lands
        # on <a>; then <c>'s tail "S" also lands on <a> (now the previous
        # sibling), so <a>.tail becomes "QRS" with no duplication.
        root = etree.Element("root")
        root.text = "P"
        a = etree.SubElement(root, "a")
        a.tail = "Q"
        b = etree.SubElement(root, "b")
        b.set("__groups_key__", self.restricted_key)
        b.tail = "R"
        c = etree.SubElement(root, "c")
        c.set("__groups_key__", self.restricted_key)
        c.tail = "S"
        d = etree.SubElement(root, "d")
        d.tail = "T"

        self._postprocess_as_restricted(root)

        self.assertEqual([child.tag for child in root], ["a", "d"])
        self.assertEqual(root.find("a").tail, "QRS")
        self.assertEqual(root.find("d").tail, "T")
        self.assertEqual("".join(root.itertext()), "PQRST")

    @mute_logger("odoo.addons.base.models.ir_ui_view")
    def test_get_view_group_removal_preserves_structure(self):
        """End-to-end get_view drops guarded siblings without orphaning text."""
        # Mirror test_attrs_groups_behavior: build a real form view with a
        # group-restricted field/div and request it as a user lacking the
        # group, exercising _postprocess_access_rights through get_view.
        view = self.View.create(
            {
                "name": "tailtext_form",
                "model": "res.partner",
                "arch": """
                    <form>
                        <field name="name"/>
                        <field name="function" groups="base.group_system"/>
                        <div id="visible"/>
                        <div id="guarded" groups="base.group_system"/>
                        <field name="email"/>
                    </form>
                """,
            }
        )

        arch = (
            self.env["res.partner"]
            .with_user(self.restricted_user)
            .get_view(view_id=view.id)["arch"]
        )
        tree = etree.fromstring(arch)

        # Unguarded nodes survive; guarded ones are removed.
        self.assertTrue(tree.xpath('//field[@name="name"]'))
        self.assertTrue(tree.xpath('//field[@name="email"]'))
        self.assertTrue(tree.xpath('//div[@id="visible"]'))
        self.assertFalse(tree.xpath('//field[@name="function"]'))
        self.assertFalse(tree.xpath('//div[@id="guarded"]'))
        # Surviving siblings appear exactly once each: tails were re-attached,
        # never duplicated into extra/orphaned nodes.
        self.assertEqual(len(tree.xpath('//field[@name="name"]')), 1)
        self.assertEqual(len(tree.xpath('//field[@name="email"]')), 1)
        self.assertEqual(len(tree.xpath('//div[@id="visible"]')), 1)
