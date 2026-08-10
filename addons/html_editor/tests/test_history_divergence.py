from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.html_editor.tools import handle_history_divergence


def _html(*step_ids):
    """Build a body carrying a collaboration history like the editor does."""
    return f'<p data-last-history-steps="{",".join(step_ids)}">body</p>'


@tagged('post_install', '-at_install')
class TestHistoryDivergence(TransactionCase):
    """Collaborative-editing conflict detection on html field writes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env['html_editor.converter.test'].create({
            'html': _html('1', '2'),
        })

    def test_untouched_field_is_left_alone(self):
        """A write that does not carry the html field is a no-op."""
        vals = {'char': 'unrelated'}
        handle_history_divergence(self.record, 'html', vals)
        self.assertEqual(vals, {'char': 'unrelated'})

    def test_module_install_context_skips_handling(self):
        """During module installation the incoming value is left verbatim."""
        vals = {'html': _html('9', '10')}
        handle_history_divergence(
            self.record.with_context(install_module=True), 'html', vals,
        )
        self.assertEqual(vals['html'], _html('9', '10'))

    def test_value_without_history_is_left_verbatim(self):
        """A value from outside the editor carries no history and is kept."""
        vals = {'html': '<p>from an external pad</p>'}
        handle_history_divergence(self.record, 'html', vals)
        self.assertEqual(vals['html'], '<p>from an external pad</p>')

    def test_known_history_is_collapsed_to_the_latest_step(self):
        """A continuing history is accepted and trimmed to its last id."""
        vals = {'html': _html('1', '2', '3')}
        handle_history_divergence(self.record, 'html', vals)
        self.assertEqual(vals['html'], _html('3'))

    def test_diverged_history_is_refused(self):
        """A history that never saw the server's last step is a conflict."""
        vals = {'html': _html('7', '8')}
        with self.assertRaises(ValidationError):
            handle_history_divergence(self.record, 'html', vals)

    def test_empty_server_value_accepts_any_history(self):
        """With nothing stored yet there is no history to diverge from."""
        blank = self.env['html_editor.converter.test'].create({})
        vals = {'html': _html('42')}
        handle_history_divergence(blank, 'html', vals)
        self.assertEqual(vals['html'], _html('42'))

    def test_legacy_server_value_without_history_is_accepted(self):
        """Old documents with no recorded history never raise (boundary)."""
        legacy = self.env['html_editor.converter.test'].create({
            'html': '<p>saved before collaboration</p>',
        })
        vals = {'html': _html('5', '6')}
        handle_history_divergence(legacy, 'html', vals)
        self.assertEqual(vals['html'], _html('6'))
