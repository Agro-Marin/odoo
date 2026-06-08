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

    def test_control_char_obfuscated_scheme_blanked(self):
        # Browsers strip C0 control chars (TAB/LF/CR/NUL) from a URL before
        # resolving its scheme, so these collapse to ``javascript:`` and execute.
        # The guard must catch them even though the literal substring differs.
        for payload in (
            "java\tscript:alert(1)",
            "java\nscript:alert(1)",
            "java\rscript:alert(1)",
            "java\x00script:alert(1)",
            "jav\tascript:alert(1)",
        ):
            atts = self.qweb._post_processing_att("a", {"href": payload})
            self.assertEqual(
                atts["href"],
                "",
                f"control-char obfuscated scheme not blanked: {payload!r}",
            )

    def test_control_char_in_benign_url_preserved(self):
        # Stripping is for detection only: a non-javascript URL that merely
        # contains a stray control character must not be blanked.
        atts = self.qweb._post_processing_att(
            "a", {"href": "https://example.com/a\tb"}
        )
        self.assertEqual(atts["href"], "https://example.com/a\tb")

    def test_compile_expr_cache_is_bounded_lru(self):
        # QWEB-P1: the compile-expr cache is a bounded LRU (not a plain dict
        # cleared wholesale at the cap, which caused recompile stampedes), and it
        # still returns a consistent result across calls.
        self.assertIsInstance(type(self.qweb)._compile_expr_cache, LRU)
        self.assertEqual(
            self.qweb._compile_expr("a + b"), self.qweb._compile_expr("a + b")
        )
