from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.html_editor.tools import handle_history_divergence


def _html(*step_ids):
    return f'<p data-last-history-steps="{",".join(step_ids)}">body</p>'


@tagged("post_install", "-at_install")
class TestHistoryDivergence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["html_editor.converter.test"].create(
            {
                "html": _html("1", "2"),
            }
        )

    def test_untouched_field_is_left_alone(self):
        vals = {"char": "unrelated"}
        handle_history_divergence(self.record, "html", vals)
        self.assertEqual(vals, {"char": "unrelated"})

    def test_module_install_context_skips_handling(self):
        vals = {"html": _html("9", "10")}
        handle_history_divergence(
            self.record.with_context(install_module=True),
            "html",
            vals,
        )
        self.assertEqual(vals["html"], _html("9", "10"))

    def test_value_without_history_is_left_verbatim(self):
        vals = {"html": "<p>from an external pad</p>"}
        handle_history_divergence(self.record, "html", vals)
        self.assertEqual(vals["html"], "<p>from an external pad</p>")

    def test_known_history_is_collapsed_to_the_latest_step(self):
        vals = {"html": _html("1", "2", "3")}
        handle_history_divergence(self.record, "html", vals)
        self.assertEqual(vals["html"], _html("3"))

    def test_diverged_history_is_refused(self):
        vals = {"html": _html("7", "8")}
        with self.assertRaises(ValidationError):
            handle_history_divergence(self.record, "html", vals)

    def test_empty_server_value_accepts_any_history(self):
        blank = self.env["html_editor.converter.test"].create({})
        vals = {"html": _html("42")}
        handle_history_divergence(blank, "html", vals)
        self.assertEqual(vals["html"], _html("42"))

    def test_legacy_server_value_without_history_is_accepted(self):
        legacy = self.env["html_editor.converter.test"].create(
            {
                "html": "<p>saved before collaboration</p>",
            }
        )
        vals = {"html": _html("5", "6")}
        handle_history_divergence(legacy, "html", vals)
        self.assertEqual(vals["html"], _html("6"))
