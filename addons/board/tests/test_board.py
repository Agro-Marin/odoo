# Part of Odoo. See LICENSE file for full copyright and licensing details.

from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBoardArchPreprocessing(TransactionCase):
    """Tests for ``board.board._arch_preprocessing`` dashboard arch cleanup."""

    def _process(self, arch):
        return self.env["board.board"]._arch_preprocessing(arch)

    def test_sets_board_js_class(self):
        """The root node of the processed arch gets ``js_class='board'``."""
        root = etree.fromstring(self._process("<form><board/></form>"))
        self.assertEqual(root.get("js_class"), "board")

    def test_removes_invisible_action(self):
        """An ``<action>`` flagged invisible is stripped; a visible one stays."""
        arch = "<form><action name='1' invisible='1'/><action name='2'/></form>"
        root = etree.fromstring(self._process(arch))
        self.assertEqual([a.get("name") for a in root.findall(".//action")], ["2"])

    def test_removes_nested_invisible_action(self):
        """Invisible actions nested under other nodes are stripped recursively."""
        arch = (
            "<form><board><column>"
            "<action name='keep'/><action name='drop' invisible='1'/>"
            "</column></board></form>"
        )
        root = etree.fromstring(self._process(arch))
        self.assertEqual([a.get("name") for a in root.findall(".//action")], ["keep"])

    def test_arch_without_actions_preserved(self):
        """Boundary: arch with no ``<action>`` keeps its structure, only js_class added."""
        root = etree.fromstring(self._process("<form><board><column/></board></form>"))
        self.assertEqual(root.get("js_class"), "board")
        self.assertEqual(len(root.findall(".//column")), 1)
        self.assertEqual(root.findall(".//action"), [])
