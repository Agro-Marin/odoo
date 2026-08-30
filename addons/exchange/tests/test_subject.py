from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import ExchangeCase
from odoo.addons.exchange.tools import Verdict


@tagged("post_install", "-at_install")
class TestExchangeSubject(ExchangeCase):
    def test_a_record_with_no_transmission_has_sent_nothing(self):
        self.assertEqual(self.subject.exchange_state, "none")
        self.assertEqual(self.subject.count_transmission, 0)

    def test_a_queued_transmission_reads_as_in_flight(self):
        self._add_transmission()
        self.subject.invalidate_recordset()
        self.assertEqual(self.subject.exchange_state, "pending")

    def test_an_acceptance_rolls_up(self):
        transmission = self._add_transmission()
        self._send(transmission, self._accepted())
        self.subject.invalidate_recordset()
        self.assertEqual(self.subject.exchange_state, "accepted")
        self.assertEqual(self.subject.count_transmission, 1)

    def test_an_accepted_annulment_wins_over_the_issue_it_annuls(self):
        issue = self._add_transmission()
        self._send(issue, self._accepted("CFDI-1"))
        annul = self._add_transmission("annul")
        self._send(annul, self._accepted("CANCEL-1"))

        self.subject.invalidate_recordset()
        self.assertEqual(self.subject.exchange_state, "annulled")
        self.assertEqual(issue.state, "accepted", "the issue keeps its own verdict")

    def test_a_rejected_annulment_leaves_the_record_accepted(self):
        issue = self._add_transmission()
        self._send(issue, self._accepted("CFDI-2"))
        annul = self._add_transmission("annul")
        self._send(annul, Verdict(state="rejected", message="Too late"))

        self.subject.invalidate_recordset()
        self.assertEqual(self.subject.exchange_state, "accepted")

    def test_transmissions_of_one_record_do_not_leak_into_another(self):
        other = self.env["res.partner"].create({"name": "Unrelated"})
        self._add_transmission()
        self.subject.invalidate_recordset()
        other.invalidate_recordset()
        self.assertEqual(self.subject.count_transmission, 1)
        self.assertEqual(other.count_transmission, 0)
        self.assertEqual(other.exchange_state, "none")

    def test_a_record_with_no_channel_says_so(self):
        with self.assertRaises(UserError):
            self.subject._add_transmission("issue")
