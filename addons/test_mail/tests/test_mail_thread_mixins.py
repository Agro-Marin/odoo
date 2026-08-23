# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import exceptions, tools
from odoo.fields import Domain
from odoo.tests.common import tagged, users
from odoo.tools import mute_logger

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.mail.tests.common_tracking import MailTrackingDurationMixinCase
from odoo.addons.test_mail.tests.common import TestRecipients


@tagged("mail_thread", "mail_track", "is_query_count")
class TestMailTrackingDurationMixin(MailTrackingDurationMixinCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass("mail.test.track.duration.mixin")

    def test_mail_tracking_duration(self):
        self._test_record_duration_tracking()

    def test_mail_tracking_duration_batch(self):
        self._test_record_duration_tracking_batch()

    def test_queries_batch_mail_tracking_duration(self):
        self._test_queries_batch_duration_tracking()


@tagged("mail_thread", "mail_track")
class TestMailThreadRottingMixin(MailTrackingDurationMixinCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass("mail.test.rotting.resource")

        [cls.stage_new, cls.stage_qualification, cls.stage_finished] = cls.env[
            "mail.test.rotting.stage"
        ].create(
            [
                {
                    "name": "stage_new",
                    "rotting_threshold_days": 3,
                },
                {
                    "name": "stage_qualification",
                    "rotting_threshold_days": 5,
                },
                {
                    "name": "stage_finished",
                    "rotting_threshold_days": 1,
                    "no_rot": True,
                },
            ]
        )

    def test_resource_rotting(self):
        # create dates for the test
        jan1 = datetime(2025, 1, 1)
        jan5 = datetime(2025, 1, 5)
        jan7 = datetime(2025, 1, 7)
        jan12 = datetime(2025, 1, 12)
        jan28 = datetime(2025, 1, 28)

        # create resources for the test, created on jan 1
        with self.mock_datetime_and_now(jan1):
            items = [item1, item2, item3, item_done, item_won] = self.env[
                "mail.test.rotting.resource"
            ].create(
                [
                    {
                        "name": "item1",
                        "stage_id": self.stage_new.id,
                    },
                    {
                        "name": "item2",
                        "stage_id": self.stage_qualification.id,
                    },
                    {
                        "name": "item3",
                        "stage_id": self.stage_new.id,
                    },
                    {
                        "name": "item_done",
                        "stage_id": self.stage_qualification.id,
                        "done": True,
                    },
                    {
                        "name": "item_wonStage",
                        "stage_id": self.stage_finished.id,
                    },
                ]
            )
            items.flush_recordset(
                ["date_last_stage_update"]
            )  # precalculate stage update()

        with self.mock_datetime_and_now(jan5):
            # need to invalidate on date change to ensure rotting computations
            items.invalidate_recordset(["is_rotting"])
            for item in [item1, item3]:
                self.assertTrue(
                    item.is_rotting,
                    "on jan 5: it's been four days, so only items in stage_new should be rotting",
                )
                self.assertEqual(item.rotting_days, 4)
            for item in [item2, item_done, item_won]:
                self.assertFalse(
                    item.is_rotting,
                    "on jan 5: it's been four days, so only items in stage_new should be rotting",
                )
                self.assertEqual(item.rotting_days, 0)

            item3.name = "item3 edited"
            self.assertTrue(
                item3.is_rotting,
                "writing to an item doesn't affect its rotting status",
            )

        with self.mock_datetime_and_now(jan7):
            items.invalidate_recordset(["is_rotting"])
            self.assertTrue(
                item2.is_rotting,
                "on jan 7: items belonging to stage_qualification should be rotting, except if their state forbids it",
            )
            self.assertEqual(item2.rotting_days, 6)
            self.assertFalse(
                item_done.is_rotting,
                "item_done is marked as done, it should not be able to rot",
            )

            self.assertTrue(item1.is_rotting)
            item1.message_post(body="Message received", message_type="email")
            self.assertTrue(
                item1.is_rotting,
                "Receiving an email should not remove rotting",
            )

            item1.message_post(body="Message sent", message_type="email_outgoing")
            self.assertTrue(
                item1.is_rotting,
                "Nor should sending an email",
            )

            self.assertFalse(
                item_won.is_rotting,
                "Items in stage_finished cannot rot",
            )
            self.stage_finished.no_rot = False
            self.assertTrue(
                item_won.is_rotting,
                "However if the stage no longer disallows rotting, then all items in the stage may once more rot",
            )

            self.stage_finished.no_rot = True
            self.assertFalse(
                item_won.is_rotting,
                "Disallowing rotting once again should disable rotting once more",
            )

        with self.mock_datetime_and_now(jan12):
            items.invalidate_recordset(["rotting_days", "is_rotting"])

            self.assertTrue(item3.is_rotting)
            self.stage_new.rotting_threshold_days = 40
            self.assertFalse(
                item3.is_rotting,
                "Changing the threshold should affect the status immediately)",
            )

            self.stage_new.rotting_threshold_days = 1

            item3.stage_id = self.stage_qualification
            self.assertFalse(
                item3.is_rotting,
                "Changing stages always removes rotting",
            )

            self.stage_qualification.rotting_threshold_days = 0
            self.assertFalse(
                item2.is_rotting,
                "Setting rotting_threshold_days at 0 on a stage immediately disables rotting for the stage",
            )

        with self.mock_datetime_and_now(jan28):
            items.invalidate_recordset(["rotting_days", "is_rotting"])
            # After a significant amount of time has passed:
            self.assertTrue(
                item1.is_rotting,
                "Items that are not done or won are rotting",
            )
            for item in [item2, item3, item_done, item_won]:
                self.assertFalse(
                    item.is_rotting,
                    "Items that are not done, won, or in a disabled rotting stage are not rotting",
                )

    def test_resource_rotting_negative_threshold_never_rots(self):
        """A negative ``rotting_threshold_days`` disables rotting, like 0 does.

        Regression: the domain excluded ``!= 0`` only, so a negative threshold
        put ``last_update + threshold`` in the past and every record in the
        stage read as rotting from the instant it was created -- including
        unsaved ones, where ``rotting_days`` then divided a ``False`` date.
        """
        stage = self.env["mail.test.rotting.stage"].create(
            {"name": "negative", "rotting_threshold_days": -1}
        )
        record = self.env["mail.test.rotting.resource"].create(
            {"name": "fresh", "stage_id": stage.id}
        )
        record.flush_recordset(["date_last_stage_update"])
        record.invalidate_recordset(["is_rotting", "rotting_days"])
        self.assertFalse(record.is_rotting)
        self.assertEqual(record.rotting_days, 0)
        self.assertNotIn(
            record,
            self.env["mail.test.rotting.resource"].search([("is_rotting", "=", True)]),
        )

        unsaved = self.env["mail.test.rotting.resource"].new(
            {"name": "unsaved", "stage_id": stage.id}
        )
        self.assertFalse(unsaved.is_rotting, "an unsaved record cannot be rotting")

    def test_resource_rotting_search_matches_compute_without_last_update(self):
        """Search and compute must agree when the last-update date is unset.

        Regression: ``_compute_rotting`` falls back to ``create_date`` when the
        tracked last-update field is NULL, but the search compared the bare
        column, so such records showed the rotting badge and were missing from
        every "Rotting" filter.
        """
        record = self.env["mail.test.rotting.resource"].create(
            {"name": "no last update", "stage_id": self.stage_new.id}
        )
        record.flush_recordset(["date_last_stage_update"])
        self.env.cr.execute(
            "UPDATE mail_test_rotting_resource "
            "SET date_last_stage_update = NULL, create_date = %s WHERE id = %s",
            (datetime(2025, 1, 1), record.id),
        )
        record.invalidate_recordset()

        with self.mock_datetime_and_now(datetime(2025, 2, 1)):
            self.assertFalse(record.date_last_stage_update)
            self.assertTrue(record.is_rotting)
            self.assertIn(
                record,
                self.env["mail.test.rotting.resource"].search(
                    [("is_rotting", "=", True)]
                ),
            )
            self.assertNotIn(
                record,
                self.env["mail.test.rotting.resource"].search(
                    [("is_rotting", "=", False)]
                ),
            )

    def test_resource_rotting_search_unsupported_model_names_the_cause(self):
        """A model without the feature must say so, not blame the operator.

        Regression: the operator guard ran first and raised ``ValueError``,
        which the domain optimiser does not catch. It retried the condition as
        ``('is_rotting', '=', True)``, hit that same guard, and surfaced 'use
        "=" operators' to a caller who had written exactly that -- the
        configuration ``UserError`` was unreachable.
        """
        model = self.env["mail.test.track.duration.mixin"]
        self.assertFalse(model._is_rotting_feature_enabled())
        with self.assertRaisesRegex(
            exceptions.UserError, "does not support the rotting feature"
        ):
            model.search([("is_rotting", "=", True)])

    def test_resource_rotting_search_survives_an_unconditional_domain(self):
        """``_get_rotting_domain`` may be widened to match everything.

        Regression: the search interpolated ``Query.where_clause`` into a
        hand-written statement, so a domain that produced no WHERE terms left a
        dangling ``AND`` and PostgreSQL rejected the whole query.
        """
        model = self.env["mail.test.rotting.resource"]
        with patch.object(
            type(model), "_get_rotting_domain", lambda records: Domain.TRUE
        ):
            model.search([("is_rotting", "=", True)])

    def test_resource_rotting_search_agrees_with_compute(self):
        """Inside the window, the search must return exactly what rots.

        The two implementations are independent -- one in Python over the
        recordset, one in SQL -- and every rotting defect found so far was a
        disagreement between them rather than an error in either alone. This
        sweeps a grid of ages against every stage and pins them together.
        """
        model = self.env["mail.test.rotting.resource"]
        stages = self.stage_new + self.stage_qualification + self.stage_finished
        base = datetime(2025, 6, 1)
        records = model.create(
            [
                {"name": f"{stage.name}-{age}", "stage_id": stage.id, "done": done}
                for stage in stages
                for age in (0, 1, 2, 3, 4, 5, 6, 30)
                for done in (False, True)
            ]
        )
        records.flush_recordset(["date_last_stage_update"])
        for index, record in enumerate(records):
            self.env.cr.execute(
                "UPDATE mail_test_rotting_resource "
                "SET date_last_stage_update = %s WHERE id = %s",
                (base - relativedelta(days=(0, 1, 2, 3, 4, 5, 6, 30)[index // 2 % 8]), record.id),
            )
        records.invalidate_recordset()

        with self.mock_datetime_and_now(base):
            computed = records.filtered("is_rotting")
            searched = model.search([("id", "in", records.ids), ("is_rotting", "=", True)])
            self.assertEqual(
                computed, searched, "is_rotting and its search must select the same set"
            )
            not_searched = model.search(
                [("id", "in", records.ids), ("is_rotting", "=", False)]
            )
            self.assertEqual(
                records - computed,
                not_searched,
                "searching is_rotting = False must return the complement",
            )

    def test_resource_rotting_search_max_months_window(self):
        """``_search_is_rotting`` must honor the configured max-months window.

        Regression: the ``INTERVAL '%(max_rotting_months)s months'`` placeholder
        sat inside a SQL string literal, so under psycopg3's server-side binding
        the bound value was ignored and the window silently collapsed to the
        placeholder's positional ordinal (~2 months) -- hiding the *most* rotten
        records (those last touched long ago) from every 'Rotting' filter while
        the kanban badge still showed them rotting.
        """
        base = datetime(2025, 1, 1)
        with self.mock_datetime_and_now(base):
            rec = self.env["mail.test.rotting.resource"].create(
                {
                    "name": "old_rotting",
                    "stage_id": self.stage_new.id,  # rotting_threshold_days = 3
                }
            )
            rec.flush_recordset(["date_last_stage_update"])

        # Configure an explicit, non-default window so the test proves the *value*
        # is bound (the old bug ignored it entirely, whatever it was set to).
        self.env["ir.config_parameter"].sudo().set_param("crm.lead.rot.max.months", 6)

        # 4 months later: last stage move was 4 months ago (>> 3d threshold) so the
        # record is rotting, and 4 < 6 => it must be returned by the search.
        with self.mock_datetime_and_now(base + relativedelta(months=4)):
            rec.invalidate_recordset(["is_rotting"])
            self.assertTrue(rec.is_rotting)
            found = self.env["mail.test.rotting.resource"].search(
                [("is_rotting", "=", True)]
            )
            self.assertIn(
                rec,
                found,
                "a 4-month-old rotting record is inside the 6-month window and must be found",
            )

        # 8 months later: still rotting by compute, but 8 > 6 => excluded by the
        # window (confirms the cutoff is a real, honored bound, not a no-op).
        with self.mock_datetime_and_now(base + relativedelta(months=8)):
            rec.invalidate_recordset(["is_rotting"])
            self.assertTrue(rec.is_rotting)
            found = self.env["mail.test.rotting.resource"].search(
                [("is_rotting", "=", True)]
            )
            self.assertNotIn(
                rec,
                found,
                "an 8-month-old record is outside the 6-month window",
            )

    def test_resource_rotting_search_window_param_is_mail_owned(self):
        """The window is configured under a mail key, with the crm one honored.

        ``mixin.mail.tracking.duration`` is generic -- project, helpdesk,
        hr_recruitment and crm all inherit it -- so its window must not be
        spelled ``crm.lead.rot.max.months``. The legacy key keeps working so
        databases that already tuned it are not silently reset to the default.
        """
        icp = self.env["ir.config_parameter"].sudo()
        base = datetime(2025, 1, 1)
        with self.mock_datetime_and_now(base):
            rec = self.env["mail.test.rotting.resource"].create(
                {
                    "name": "window_param",
                    "stage_id": self.stage_new.id,  # rotting_threshold_days = 3
                }
            )
            rec.flush_recordset(["date_last_stage_update"])

        def rotting_found():
            return rec in self.env["mail.test.rotting.resource"].search(
                [("is_rotting", "=", True)]
            )

        # 4 months on, the record is rotting by compute in every case below.
        with self.mock_datetime_and_now(base + relativedelta(months=4)):
            rec.invalidate_recordset(["is_rotting"])
            self.assertTrue(rec.is_rotting)

            # legacy key alone still drives the window (backward compatibility)
            icp.set_param("crm.lead.rot.max.months", 2)
            self.assertFalse(rotting_found(), "legacy crm key must still be honored")

            # the mail-owned key takes precedence over the legacy one
            icp.set_param("mail.rotting.max.months", 6)
            self.assertTrue(
                rotting_found(),
                "mail.rotting.max.months must win over crm.lead.rot.max.months",
            )

            # and it is a real bound in its own right, not just an override
            icp.set_param("mail.rotting.max.months", 2)
            self.assertFalse(rotting_found())


@tagged("mail_thread", "mail_blacklist")
class TestMailThread(MailCommon, TestRecipients):
    @mute_logger("odoo.models.unlink")
    def test_blacklist_mixin_email_normalized(self):
        """Test email_normalized and is_blacklisted fields behavior, notably
        when dealing with encapsulated email fields and multi-email input."""
        base_email = "test.email@test.example.com"

        # test data: source email, expected email normalized
        valid_pairs = [
            (base_email, base_email),
            (tools.formataddr(("Another Name", base_email)), base_email),
            (f"Name That Should Be Escaped <{base_email}>", base_email),
            ("test.😊@example.com", "test.😊@example.com"),
            ('"Name 😊" <test.😊@example.com>', "test.😊@example.com"),
        ]
        void_pairs = [(False, False), ("", False), (" ", False)]
        multi_pairs = [
            (
                f"{base_email}, other.email@test.example.com",
                base_email,
            ),  # multi supports first found
            (
                f"{tools.formataddr(('Another Name', base_email))}, other.email@test.example.com",
                base_email,
            ),  # multi supports first found
        ]
        for email_from, exp_email_normalized in valid_pairs + void_pairs + multi_pairs:
            with self.subTest(
                email_from=email_from, exp_email_normalized=exp_email_normalized
            ):
                new_record = self.env["mail.test.gateway"].create(
                    {
                        "email_from": email_from,
                        "name": "BL Test",
                    }
                )
                self.assertEqual(new_record.email_normalized, exp_email_normalized)
                self.assertFalse(new_record.is_blacklisted)

                # blacklist email should fail as void
                if email_from in [pair[0] for pair in void_pairs]:
                    with self.assertRaises(exceptions.UserError):
                        bl_record = self.env["mail.blacklist"]._add(email_from)
                # blacklist email currently fails but could not
                elif email_from in [pair[0] for pair in multi_pairs]:
                    with self.assertRaises(exceptions.UserError):
                        bl_record = self.env["mail.blacklist"]._add(email_from)
                # blacklist email ok
                else:
                    bl_record = self.env["mail.blacklist"]._add(email_from)
                    self.assertEqual(bl_record.email, exp_email_normalized)
                    new_record.invalidate_recordset(fnames=["is_blacklisted"])
                    self.assertTrue(new_record.is_blacklisted)

                bl_record.unlink()


@tagged("mail_thread", "mail_thread_cc", "mail_tools")
class TestMailThreadCC(MailCommon):
    @users("employee")
    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_suggested_recipients_mail_cc(self):
        """MailThreadCC mixin adds its own suggested recipients management
        coming from CC (carbon copy) management."""
        record = self.env["mail.test.cc"].create(
            {
                "email_cc": "cc1@example.com, cc2@example.com, cc3 <cc3@example.com>",
            }
        )
        suggestions = record._message_get_suggested_recipients(no_create=True)
        expected_list = [
            {
                "name": "",
                "email": "cc1@example.com",
                "partner_id": False,
                "create_values": {},
            },
            {
                "name": "",
                "email": "cc2@example.com",
                "partner_id": False,
                "create_values": {},
            },
            {
                "name": "cc3",
                "email": "cc3@example.com",
                "partner_id": False,
                "create_values": {},
            },
        ]
        self.assertEqual(len(suggestions), len(expected_list))
        for suggestion, expected in zip(suggestions, expected_list, strict=True):
            self.assertDictEqual(suggestion, expected)
