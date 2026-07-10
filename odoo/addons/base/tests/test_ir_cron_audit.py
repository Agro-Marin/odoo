"""Regression coverage for ``ir.cron`` (base module audit Tranche 4).

Covers CRON-T01: ``ir.cron._trigger(coalesce=...)`` quantizes each requested
``call_at`` up to the next coalesce-minute boundary, collapsing several
sub-minute triggers into one wake-up.
"""

import math
import secrets
from datetime import datetime, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestCronTriggerCoalesce(TransactionCase):
    """Exercise ``ir.cron._trigger(coalesce=...)`` quantization (CRON-T01)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A non-admin owner is enough; the cron only writes triggers as sudo.
        cls.user = new_test_user(cls.env, login="cron_audit_user")
        cls.cron = cls.env["ir.cron"].create(cls._cron_vals(cls.env, cls.user))

    @classmethod
    def _cron_vals(cls, env, user):
        """Build minimal vals for an active ``ir.cron`` record."""
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
            # Keep nextcall in the future so only triggers schedule the job.
            "nextcall": fields.Datetime.now() + timedelta(hours=1),
        }

    @staticmethod
    def _expected_boundary(dt, coalesce):
        """Replicate the source arithmetic at ir_cron.py:913-920.

        Mirrors ``datetime.fromtimestamp(ceil(dt.timestamp() / factor) *
        factor)`` so the expectation tracks the process timezone semantics,
        matching the stored value.
        """
        factor = coalesce * 60
        return datetime.fromtimestamp(math.ceil(dt.timestamp() / factor) * factor)

    @mute_logger("odoo.addons.base.models.ir_cron")
    def test_coalesce_rounds_up_to_next_minute_boundary(self):
        """A sub-minute ``at`` is rounded UP to the next coalesce boundary."""
        # 12:03:17 with coalesce=5 must land on the next 5-minute mark.
        at = datetime(2026, 5, 28, 12, 3, 17)
        triggers = self.cron._trigger(at=at, coalesce=5)

        self.assertEqual(len(triggers), 1)
        expected = self._expected_boundary(at, 5)
        self.assertEqual(triggers.call_at, expected)
        # The stored boundary is strictly after the requested instant and
        # within the coalescing window.
        self.assertGreater(triggers.call_at, at)
        self.assertLessEqual(triggers.call_at - at, timedelta(minutes=5))

    @mute_logger("odoo.addons.base.models.ir_cron")
    def test_coalesce_groups_triggers_within_same_window(self):
        """Several sub-minute instants in one window share one boundary."""
        base = datetime(2026, 5, 28, 9, 0, 0)
        instants = [
            base + timedelta(seconds=1),
            base + timedelta(seconds=59),
            base + timedelta(minutes=2, seconds=30),
            base + timedelta(minutes=4, seconds=59),
        ]
        triggers = self.cron._trigger(at=instants, coalesce=5)

        self.assertEqual(len(triggers), len(instants))
        # All four fall in the [09:00, 09:05) window and coalesce to 09:05.
        expected = self._expected_boundary(base + timedelta(seconds=1), 5)
        self.assertEqual(set(triggers.mapped("call_at")), {expected})

    @mute_logger("odoo.addons.base.models.ir_cron")
    def test_coalesce_boundary_exact_value_kept(self):
        """An instant already on a boundary is not pushed to the next one."""
        # math.ceil leaves an exact multiple unchanged, so a value already on
        # a coalesce boundary stays put rather than jumping a full window.
        coalesce = 5
        factor = coalesce * 60
        on_boundary = datetime.fromtimestamp((1_700_000_000 // factor) * factor)
        triggers = self.cron._trigger(at=on_boundary, coalesce=coalesce)

        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers.call_at, on_boundary)

    @mute_logger("odoo.addons.base.models.ir_cron")
    def test_no_coalesce_keeps_exact_at(self):
        """``coalesce=0`` (default) leaves ``call_at`` untouched."""
        at = datetime(2026, 5, 28, 12, 3, 17)
        triggers = self.cron._trigger(at=at)

        self.assertEqual(len(triggers), 1)
        # No quantization: the sub-minute seconds are preserved verbatim.
        self.assertEqual(triggers.call_at, at)


@tagged("post_install", "-at_install")
class TestCronTriggerIndexes(TransactionCase):
    """Pin the ir_cron_trigger index layout: a composite (cron_id, call_at)
    serves both the ready-jobs EXISTS probe and plain cron_id lookups, so the
    old single-column cron_id index must be gone; call_at keeps its own index
    for the autovacuum GC scan."""

    def test_trigger_index_layout(self):
        self.env.cr.execute(
            "SELECT indexname, indexdef FROM pg_indexes"
            " WHERE tablename = 'ir_cron_trigger'"
        )
        indexes = dict(self.env.cr.fetchall())
        composite = indexes.get("ir_cron_trigger_cron_id_call_at_idx")
        self.assertTrue(composite, f"composite index missing, got: {sorted(indexes)}")
        self.assertIn("(cron_id, call_at)", composite)
        # call_at keeps a dedicated index (leading column call_at) for the GC.
        self.assertTrue(
            any("(call_at)" in d for d in indexes.values()),
            f"call_at index missing, got: {indexes}",
        )
        # The composite's prefix covers cron_id, so the field must no longer
        # declare its own index. (Checked on the declaration, not pg_indexes:
        # on a legacy database the ORM keeps the now-"unexpected" old index.)
        self.assertFalse(self.env["ir.cron.trigger"]._fields["cron_id"].index)
