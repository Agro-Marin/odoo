from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.event.models.event_mail import EventMail
from odoo.addons.event.tests.common import EventCase


@tagged("event_mail", "post_install", "-at_install")
class TestSchedulerBatching(EventCase):
    """Batch-scale scheduler behaviour.

    The rest of the mail suite runs a handful of registrations, below both the
    500-row generation chunk and the cron limit, so it cannot see either the
    duplicate-generation or the slot-drop defect. These assert the marginal
    behaviour instead of an absolute at N=1.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.now = fields.Datetime.now()
        cls.template = cls.env["mail.template"].create({
            "body_html": "<p>hello</p>",
            "model_id": cls.env["ir.model"]._get_id("event.registration"),
            "name": "Batching probe",
            "subject": "probe",
            "use_default_to": True,
        })

    def _count_sends(self):
        """Return {registration_id: number of times it was handed to _send_mail}."""
        sent = {}

        def _record(scheduler, registrations):
            for registration in registrations:
                sent[registration.id] = sent.get(registration.id, 0) + 1

        return sent, patch.object(EventMail, "_send_mail", _record)

    def test_attendee_scheduler_mails_each_attendee_once_past_the_chunk_size(self):
        """Above the 500-row generation chunk, every attendee is still mailed once."""
        event = self.env["event.event"].create({
            "date_begin": self.now + timedelta(days=10),
            "date_end": self.now + timedelta(days=11),
            "event_mail_ids": [Command.create({
                "interval_nbr": 0,
                "interval_type": "after_sub",
                "interval_unit": "now",
                "template_ref": f"mail.template,{self.template.id}",
            })],
            "name": "Above the chunk",
            "question_ids": [],
        })
        scheduler = event.event_mail_ids
        count = 600  # > the 500 rows _create_missing_mail_registrations chunks on
        self.env["event.registration"].with_context(install_mode=True).create([
            {"email": f"a{idx}@test.example.com", "event_id": event.id, "name": f"A{idx}"}
            for idx in range(count)
        ])
        self.env.flush_all()

        sent, mock_send = self._count_sends()
        with mock_send:
            for _ in range(6):
                scheduler.execute()
                self.env.flush_all()
                if not self.env["event.mail.registration"].search_count([
                    ("mail_sent", "=", False), ("scheduler_id", "=", scheduler.id),
                ]):
                    break

        self.assertEqual(
            self.env["event.mail.registration"].search_count([("scheduler_id", "=", scheduler.id)]),
            count,
            "one scheduled communication per attendee, not one per attendee per chunk",
        )
        self.assertEqual(sorted(set(sent.values())), [1], "each attendee mailed exactly once")
        self.assertEqual(len(sent), count)
        self.assertEqual(sum(sent.values()), count)

    def test_slot_scheduler_mails_every_attendee_across_cron_runs(self):
        """A slot larger than the cron limit still reaches all of its attendees.

        Checked against the single-slot-less event, which is the same scheduler
        code with mail_slot unset: the two must not diverge.
        """
        self.env["ir.config_parameter"].sudo().set_param("mail.batch_size", "2")
        self.env["ir.config_parameter"].sudo().set_param("mail.render.cron.limit", "2")
        begin = self.now - timedelta(days=3)
        results = {}
        for multi in (False, True):
            event = self.env["event.event"].create({
                "date_begin": begin,
                "date_end": self.now - timedelta(hours=1),
                "date_tz": "UTC",
                "event_mail_ids": [],
                "is_multi_slots": multi,
                "name": f"Slots={multi}",
                "question_ids": [],
            })
            slot = self.env["event.slot"].create({
                "date": (self.now - timedelta(days=2)).date(),
                "end_hour": 10.0,
                "event_id": event.id,
                "start_hour": 9.0,
            }) if multi else self.env["event.slot"]
            scheduler = self.env["event.mail"].create({
                "event_id": event.id,
                "interval_nbr": 1,
                "interval_type": "after_event",
                "interval_unit": "hours",
                "template_ref": f"mail.template,{self.template.id}",
            })
            registrations = self.env["event.registration"].with_context(install_mode=True).create([
                {
                    "email": f"s{idx}@test.example.com",
                    "event_id": event.id,
                    "event_slot_id": slot.id if multi else False,
                    "name": f"S{idx}",
                }
                for idx in range(6)  # 3x the cron limit
            ])
            self.env.flush_all()

            sent, mock_send = self._count_sends()
            with mock_send:
                for _ in range(8):
                    scheduler.execute()
                    self.env.flush_all()
            results[multi] = [sent.get(registration.id, 0) for registration in registrations]

        self.assertEqual(
            results[True], results[False],
            "the slot-based path must mail the same attendees as the event-based one",
        )
        self.assertEqual(sorted(set(results[True])), [1], "each slot attendee mailed exactly once")
