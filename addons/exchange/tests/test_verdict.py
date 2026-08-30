from odoo.tests.common import BaseCase

from odoo.addons.exchange.tools import ACCEPTED, REJECTED, SENT, Verdict


class TestVerdict(BaseCase):
    def test_an_unknown_state_is_refused(self):
        with self.assertRaises(ValueError):
            Verdict(state="done")

    def test_a_rejection_carries_the_counterpartys_words(self):
        with self.assertRaises(ValueError):
            Verdict(state=REJECTED)
        self.assertEqual(Verdict(state=REJECTED, message="Bad NIF").message, "Bad NIF")

    def test_a_settled_verdict_cannot_ask_to_be_retried(self):
        with self.assertRaises(ValueError):
            Verdict(state=ACCEPTED, retry_after=60)
        self.assertEqual(Verdict(state=SENT, retry_after=60).retry_after, 60)

    def test_settlement_is_a_property_of_the_state(self):
        self.assertTrue(Verdict(state=ACCEPTED).is_settled)
        self.assertTrue(Verdict(state=REJECTED, message="no").is_settled)
        self.assertFalse(Verdict(state=SENT).is_settled)
