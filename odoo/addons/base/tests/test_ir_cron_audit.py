import math
import secrets
from datetime import datetime, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestCronTriggerCoalesce(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="cron_audit_user")
        cls.cron = cls.env["ir.cron"].create(cls._cron_vals(cls.env, cls.user))

    @classmethod
    def _cron_vals(cls, env, user):
        unique = secrets.token_urlsafe(8)
        return {
            "name": f"Audit coalesce cron {unique}",
            "state": "code",
            "code": "",
            "model_id": env.ref("base.model_res_partner").id,
            "user_id": user.id,
            "active": True,
            "interval_number": 1,
            "interval_type": "days",
            "nextcall": fields.Datetime.now() + timedelta(hours=1),
        }

    @staticmethod
    def _expected_boundary(dt, coalesce):
        factor = coalesce * 60
        return datetime.fromtimestamp(math.ceil(dt.timestamp() / factor) * factor)

    @mute_logger("odoo.addons.base.models.ir_cron")
    def test_coalesce_rounds_up_to_next_minute_boundary(self):
        at = datetime(2026, 5, 28, 12, 3, 17)
        triggers = self.cron._trigger(at=at, coalesce=5)

        self.assertEqual(len(triggers), 1)
        expected = self._expected_boundary(at, 5)
        self.assertEqual(triggers.call_at, expected)
        self.assertGreater(triggers.call_at, at)
        self.assertLessEqual(triggers.call_at - at, timedelta(minutes=5))

    @mute_logger("odoo.addons.base.models.ir_cron")
    def test_coalesce_groups_triggers_within_same_window(self):
        base = datetime(2026, 5, 28, 9, 0, 0)
        instants = [
            base + timedelta(seconds=1),
            base + timedelta(seconds=59),
            base + timedelta(minutes=2, seconds=30),
            base + timedelta(minutes=4, seconds=59),
        ]
        triggers = self.cron._trigger(at=instants, coalesce=5)

        self.assertEqual(len(triggers), len(instants))
        expected = self._expected_boundary(base + timedelta(seconds=1), 5)
        self.assertEqual(set(triggers.mapped("call_at")), {expected})

    @mute_logger("odoo.addons.base.models.ir_cron")
    def test_coalesce_boundary_exact_value_kept(self):
        coalesce = 5
        factor = coalesce * 60
        on_boundary = datetime.fromtimestamp((1_700_000_000 // factor) * factor)
        triggers = self.cron._trigger(at=on_boundary, coalesce=coalesce)

        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers.call_at, on_boundary)

    @mute_logger("odoo.addons.base.models.ir_cron")
    def test_no_coalesce_keeps_exact_at(self):
        at = datetime(2026, 5, 28, 12, 3, 17)
        triggers = self.cron._trigger(at=at)

        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers.call_at, at)


@tagged("post_install", "-at_install")
class TestCronTriggerIndexes(TransactionCase):
    def test_trigger_index_layout(self):
        self.env.cr.execute(
            "SELECT indexname, indexdef FROM pg_indexes"
            " WHERE tablename = 'ir_cron_trigger'"
        )
        indexes = dict(self.env.cr.fetchall())
        composite = indexes.get("ir_cron_trigger_cron_id_call_at_idx")
        self.assertTrue(composite, f"composite index missing, got: {sorted(indexes)}")
        self.assertIn("(cron_id, call_at)", composite)
        self.assertTrue(
            any("(call_at)" in d for d in indexes.values()),
            f"call_at index missing, got: {indexes}",
        )
        self.assertFalse(self.env["ir.cron.trigger"]._fields["cron_id"].index)
