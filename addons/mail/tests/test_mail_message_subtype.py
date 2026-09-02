from odoo.exceptions import UserError

from odoo.addons.mail.tests.common import MailCommon


class TestMailMessageSubtypeProtection(MailCommon):
    """The three master subtypes are wired into every chatter: 'comment' backs
    'Send a message', 'note' backs 'Log a note' and must stay internal, and
    'activities' is used when marking activities as done. Binding any of them to
    a single model, or deleting one, breaks messaging database-wide, and
    Settings admins can reach all three from Technical > Subtypes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.custom_subtype = cls.env["mail.message.subtype"].create(
            {"name": "Custom Subtype"}
        )

    def test_master_subtypes_reject_res_model(self):
        for xml_id in ("mail.mt_comment", "mail.mt_note", "mail.mt_activities"):
            with self.subTest(xml_id=xml_id):
                subtype = self.env.ref(xml_id)
                with self.assertRaises(UserError):
                    subtype.write({"res_model": "res.partner"})

    def test_master_subtypes_reject_unlink(self):
        for xml_id in ("mail.mt_comment", "mail.mt_note", "mail.mt_activities"):
            with self.subTest(xml_id=xml_id):
                with self.assertRaises(UserError):
                    self.env.ref(xml_id).unlink()

    def test_comment_and_note_reject_internal_flip(self):
        """'comment' must stay public and 'note' internal; 'activities' is only
        pinned on res_model, so flipping its internal flag stays allowed."""
        for xml_id in ("mail.mt_comment", "mail.mt_note"):
            with self.subTest(xml_id=xml_id):
                subtype = self.env.ref(xml_id)
                with self.assertRaises(UserError):
                    subtype.write({"internal": not subtype.internal})

        activities = self.env.ref("mail.mt_activities")
        activities.write({"internal": not activities.internal})

    def test_master_subtypes_still_editable_otherwise(self):
        """The guard pins two fields, it does not freeze the records: renaming
        or re-sequencing a master subtype must keep working, and so must a
        write that sets a protected field to the value it already has."""
        comment = self.env.ref("mail.mt_comment")
        comment.write({"name": "Discussions renamed", "sequence": 7})
        self.assertEqual(comment.name, "Discussions renamed")
        comment.write({"res_model": False, "internal": False})

    def test_custom_subtype_is_unaffected(self):
        self.custom_subtype.write({"res_model": "res.partner", "internal": True})
        self.assertEqual(self.custom_subtype.res_model, "res.partner")
        self.custom_subtype.unlink()
