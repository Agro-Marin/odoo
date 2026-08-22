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
        self.session.try_cash_in_out("in", 100, "reason", False, {})
        self.assertEqual(self._last_line().amount, 100)

    def test_unknown_type_is_refused(self):
        with self.assertRaises(UserError):
            self.session.try_cash_in_out("sideways", 100, "reason", False, {})

    def test_zero_amount_is_refused(self):
        with self.assertRaises(UserError):
            self.session.try_cash_in_out("in", 0, "reason", False, {})

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

    def test_closed_session_refuses_cash_movements(self):
        self.session.write({"state": "closed"})
        with self.assertRaises(UserError):
            self.session.try_cash_in_out("in", 10, "reason", False, {})

    def test_closing_control_session_refuses_cash_movements(self):
        self.session.write({"state": "closing_control"})
        with self.assertRaises(UserError):
            self.session.try_cash_in_out("in", 10, "reason", False, {})

    def test_opening_control_session_accepts_the_float(self):
        self.assertEqual(self.session.state, "opening_control")
        self.session.try_cash_in_out("in", 10, "opening float", False, {})
        self.assertEqual(self._last_line().amount, 10)


@tagged("post_install", "-at_install")
class TestPosSessionName(CommonPosTest):

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
        self.env.flush_all()
        self.pos_config_usd.open_ui()
        second = self.pos_config_usd.current_session_id
        self.assertNotEqual(first.name, second.name)

    def test_opening_control_does_not_rename(self):
        self.pos_config_usd.open_ui()
        session = self.pos_config_usd.current_session_id
        named = session.name
        session.set_opening_control(0, "")
        self.assertEqual(session.name, named)
