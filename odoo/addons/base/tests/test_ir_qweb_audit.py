from odoo.libs.lru import LRU
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestQwebPostProcessingAtt(TransactionCase):
    """QWEB-T2: _post_processing_att is the XSS guard that blanks malicious URL
    schemes on dynamic nodes. Cover the blanking, the javascript:history.back()
    exception, normal URLs, and the static-node bypass. (The previous coverage
    lived in a dead pytest module importing a non-existent odoo.libs.ir_qweb.)
    """

    def setUp(self):
        super().setUp()
        self.qweb = self.env["ir.qweb"]

    def test_javascript_scheme_blanked(self):
        for attr in ("href", "src", "action", "formaction"):
            atts = self.qweb._post_processing_att("a", {attr: "javascript:alert(1)"})
            self.assertEqual(
                atts[attr], "", f"{attr} javascript: scheme must be blanked"
            )

    def test_history_back_exception_preserved(self):
        for value in ("javascript:history.back()", "javascript:window.history.back()"):
            atts = self.qweb._post_processing_att("a", {"href": value})
            self.assertEqual(atts["href"], value)

    def test_normal_url_preserved(self):
        atts = self.qweb._post_processing_att("a", {"href": "https://example.com/x"})
        self.assertEqual(atts["href"], "https://example.com/x")

    def test_static_node_bypasses_scheme_stripping(self):
        # Static nodes carry __is_static_node and are NOT stripped (the flag is
        # popped off the returned dict).
        atts = self.qweb._post_processing_att(
            "a", {"href": "javascript:alert(1)", "__is_static_node": True}
        )
        self.assertEqual(atts, {"href": "javascript:alert(1)"})

    def test_compile_expr_cache_is_bounded_lru(self):
        # QWEB-P1: the compile-expr cache is a bounded LRU (not a plain dict
        # cleared wholesale at the cap, which caused recompile stampedes), and it
        # still returns a consistent result across calls.
        self.assertIsInstance(type(self.qweb)._compile_expr_cache, LRU)
        self.assertEqual(
            self.qweb._compile_expr("a + b"), self.qweb._compile_expr("a + b")
        )
