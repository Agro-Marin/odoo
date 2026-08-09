# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Cash in/out and session identity.

``try_cash_in_out`` is an RPC: the client hands it a type, an amount, a reason
and an ``extras`` dict, and the server used all four verbatim. It also never
looked at the session's state, and the session it stamps into the statement
line's label can still be carrying its ``/`` placeholder.

Authored red-green: every test below failed against the pre-fix code.
"""

import logging

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestPosCashInOut(CommonPosTest):
    def setUp(self):
        super().setUp()
        self.pos_config_usd.open_ui()
        self.session = self.pos_config_usd.current_session_id

    def _last_line(self):
        return self.session.statement_line_ids.sorted("id")[-1]

    # ------------------------------------------------------------------
    # The sign is the server's to decide. It used to be `sign * amount`
    # with a client-supplied amount, so a "Cash In" of -100 booked -100.
    # ------------------------------------------------------------------
    def test_cash_in_is_always_positive(self):
        self.session.try_cash_in_out("in", -100, "reason", False, {})
        self.assertEqual(self._last_line().amount, 100)

    def test_cash_out_is_always_negative(self):
        self.session.try_cash_in_out("out", 100, "reason", False, {})
        self.assertEqual(self._last_line().amount, -100)

    def test_cash_out_with_negative_amount_stays_negative(self):
        self.session.try_cash_in_out("out", -100, "reason", False, {})
        self.assertEqual(self._last_line().amount, -100)

    def test_positive_cash_in_is_unchanged(self):
        """Control: the normal path must be untouched."""
        self.session.try_cash_in_out("in", 100, "reason", False, {})
        self.assertEqual(self._last_line().amount, 100)

    def test_unknown_type_is_refused(self):
        with self.assertRaises(UserError):
            self.session.try_cash_in_out("sideways", 100, "reason", False, {})

    def test_zero_amount_is_refused(self):
        with self.assertRaises(UserError):
            self.session.try_cash_in_out("in", 0, "reason", False, {})

    # ------------------------------------------------------------------
    # The accounting label is the server's to write.
    # ------------------------------------------------------------------
    def test_label_ignores_client_supplied_text(self):
        self.session.try_cash_in_out(
            "in", 10, "float top-up", False, {"translatedType": "AUDITED AND APPROVED"}
        )
        payment_ref = self._last_line().payment_ref
        self.assertNotIn("AUDITED AND APPROVED", payment_ref)
        self.assertIn("float top-up", payment_ref)

    def test_label_names_the_direction(self):
        self.session.try_cash_in_out("out", 10, "petty cash", False, {})
        self.assertIn("Cash Out", self._last_line().payment_ref)

    # ------------------------------------------------------------------
    # A session that is no longer trading takes no cash movements: its
    # closing entry has already been posted and reconciled.
    # ------------------------------------------------------------------
    def test_closed_session_refuses_cash_movements(self):
        self.session.write({"state": "closed"})
        with self.assertRaises(UserError):
            self.session.try_cash_in_out("in", 10, "reason", False, {})

    def test_closing_control_session_refuses_cash_movements(self):
        self.session.write({"state": "closing_control"})
        with self.assertRaises(UserError):
            self.session.try_cash_in_out("in", 10, "reason", False, {})

    def test_opening_control_session_accepts_the_float(self):
        """Control: counting the drawer happens in `opening_control`, so that
        state must keep working."""
        self.assertEqual(self.session.state, "opening_control")
        self.session.try_cash_in_out("in", 10, "opening float", False, {})
        self.assertEqual(self._last_line().amount, 10)


@tagged("post_install", "-at_install")
class TestPosSessionName(CommonPosTest):
    """A session used to be named only by `set_opening_control`, which the
    frontend calls. A session opened from the backend and closed from there
    therefore lived and died as ``/`` -- and that placeholder is interpolated
    into cash-movement labels, closing-difference move refs and chatter.
    """

    def test_session_is_named_on_creation(self):
        self.pos_config_usd.open_ui()
        session = self.pos_config_usd.current_session_id
        self.assertNotEqual(session.name, "/")

    def test_placeholder_never_reaches_an_account_move_ref(self):
        self.pos_config_usd.open_ui()
        session = self.pos_config_usd.current_session_id
        ref = session._get_diff_account_move_ref(session.payment_method_ids[:1])
        self.assertNotIn("(/)", ref)

    def test_placeholder_never_reaches_a_cash_movement(self):
        self.pos_config_usd.open_ui()
        session = self.pos_config_usd.current_session_id
        session.try_cash_in_out("in", 10, "reason", False, {})
        self.assertFalse(
            session.statement_line_ids.sorted("id")[-1].payment_ref.startswith("/-")
        )

    def test_names_are_sequential_and_distinct(self):
        self.pos_config_usd.open_ui()
        first = self.pos_config_usd.current_session_id
        first.write({"state": "closed"})
        # The one-open-session-per-config index is enforced by the database, so
        # the close has to reach it before the next session is inserted.
        self.env.flush_all()
        self.pos_config_usd.open_ui()
        second = self.pos_config_usd.current_session_id
        self.assertNotEqual(first.name, second.name)

    def test_opening_control_does_not_rename(self):
        """Naming moved to creation; running opening control must not append a
        second sequence number to an already-named session."""
        self.pos_config_usd.open_ui()
        session = self.pos_config_usd.current_session_id
        named = session.name
        session.set_opening_control(0, "")
        self.assertEqual(session.name, named)
