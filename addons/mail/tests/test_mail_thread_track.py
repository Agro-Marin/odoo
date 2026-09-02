from unittest.mock import patch

from odoo.tests import tagged, users

from odoo.addons.mail.tests.common import MailCommon


@tagged("mail_thread", "mail_track")
class TestMailThreadTrackAccess(MailCommon):
    """`_track_prepare` reads the initial values, so it must read them as sudo.

    `write()` prepares EVERY tracked field of the model, not only the ones
    being written, and reading a tracked x2many searches its comodel. A user
    allowed to write the record but not to read that comodel therefore gets an
    `AccessError` out of the tracking machinery, on a field they never touched.

    This fork has exactly that shape in `project_hr.project_task.employee_ids`,
    a tracked many2many to `hr.employee`, which `base.group_user` cannot read
    (`addons/hr/security/ir.model.access.csv` grants `hr.employee` to
    `hr.group_hr_user` and `base.group_system` only). `mail` cannot depend on
    `project_hr`, so the shape is reproduced here on `res.partner`, whose
    `bank_ids` is a one2many to a comodel we can close off.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tracked_partner = cls.env["res.partner"].create(
            {"name": "Tracked Partner", "function": "before"}
        )

    def _close_off_partner_bank(self):
        """Leave `res.partner.bank` unreadable for the writing user."""
        for xmlid in (
            "base.access_res_partner_bank_group_user",
            "base.access_res_partner_bank_group_partner_manager",
        ):
            self.env.ref(xmlid).sudo().perm_read = False
        self.env["res.partner.bank"].invalidate_model()
        self.env.registry.clear_cache()

    @users("employee")
    def test_track_prepare_reads_initial_values_whatever_the_writer_s_acls(self):
        partner = self.tracked_partner.with_env(self.env)
        self._close_off_partner_bank()
        self.assertFalse(
            self.env["res.partner.bank"].has_access("read"),
            "the writing user must not be able to read the tracked comodel",
        )

        bank_ids = self.env["res.partner"]._fields["bank_ids"]
        with patch.object(type(bank_ids), "tracking", 1, create=True):
            self.assertIn(
                "bank_ids",
                partner._track_get_fields(),
                "the comodel is closed off but the FIELD stays readable, so "
                "`fields_get` keeps it in the tracked set",
            )
            # writing an unrelated, untracked field is enough: write() prepares
            # every tracked field of the model
            partner.write({"function": "after"})
            self.flush_tracking()

        self.assertEqual(partner.function, "after")

    @users("employee")
    def test_track_finalize_still_credits_the_real_writer(self):
        """Sudoing the initial read must not reattribute the log to OdooBot."""
        partner = self.tracked_partner.with_env(self.env)
        partner.write({"name": "Renamed By Ernest"})
        self.flush_tracking()

        tracking = partner.message_ids.sudo().tracking_value_ids
        self.assertTrue(tracking, "renaming a partner is tracked")
        self.assertEqual(
            partner.message_ids[0].sudo().author_id,
            self.partner_employee,
            "the tracking message stays authored by the user who wrote",
        )
