# Part of Odoo. See LICENSE file for full copyright and licensing details.
# `_check_pos_config` only sees rows its own transaction can see, so two cashiers
# opening the same point of sale concurrently both pass it and both commit. These
# tests pin the partial unique index that arbitrates that race, and the states it
# must deliberately leave alone.
#
# Rows are inserted with raw SQL rather than through the ORM: the point is what the
# database accepts from a competing transaction, and going through `create()` would
# only re-test the Python constraint (and entangle the assertions with flush order).
import psycopg

import odoo
from odoo.tools.sql import index_exists

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestPosSessionConcurrency(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config

    def _insert_session(self, config, state, rescue=False):
        """Insert a session row the way a competing transaction would.

        `company_id` and `currency_id` are related non-stored fields on this model,
        so the table only requires config, user and state.
        """
        self.env.cr.execute(
            """
            INSERT INTO pos_session (config_id, user_id, state, rescue,
                                     create_uid, write_uid, create_date, write_date)
                 VALUES (%s, %s, %s, %s, %s, %s, now(), now())
              RETURNING id
            """,
            (
                config.id,
                self.env.user.id,
                state,
                rescue,
                self.env.user.id,
                self.env.user.id,
            ),
        )
        return self.env.cr.fetchone()[0]

    def _assert_rejected(self, config, state, rescue=False):
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.env.cr.savepoint(flush=False):
                self._insert_session(config, state, rescue=rescue)

    def _assert_accepted(self, config, state, rescue=False):
        with self.env.cr.savepoint(flush=False):
            self.assertTrue(self._insert_session(config, state, rescue=rescue))

    def test_open_session_index_exists(self):
        self.assertTrue(
            index_exists(self.env.cr, "pos_session_open_per_config_uniq"),
            "the partial unique index guarding concurrent session opening is missing",
        )

    def test_second_open_session_is_rejected_by_the_database(self):
        self._insert_session(self.config, "opened")
        self._assert_rejected(self.config, "opened")

    def test_closing_control_still_holds_the_slot(self):
        """`closing_control` is not `closed`: a session being closed has not
        released the point of sale yet, matching `_check_pos_config`."""
        self._insert_session(self.config, "closing_control")
        self._assert_rejected(self.config, "opened")

    def test_rescue_sessions_are_exempt(self):
        """Rescue sessions are created alongside a stuck one on purpose."""
        self._insert_session(self.config, "opened")
        self._assert_accepted(self.config, "opened", rescue=True)

    def test_closed_sessions_do_not_hold_the_slot(self):
        """The whole point of the partial index: history must not block reopening."""
        self._insert_session(self.config, "closed")
        self._assert_accepted(self.config, "opened")

    def test_other_configs_are_unaffected(self):
        self._insert_session(self.config, "opened")
        self._assert_accepted(self.other_currency_config, "opened")
