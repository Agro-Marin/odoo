from odoo.tests import tagged

from odoo.addons.mail.tests.common_controllers import MailControllerBinaryCommon


@tagged("-at_install", "post_install", "mail_controller")
class TestDiscussBinaryController(MailControllerBinaryCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_channel = cls.env["discuss.channel"].create(
            {"name": "Private Channel", "channel_type": "group"}
        )
        cls.public_channel = cls.env["discuss.channel"]._create_channel(
            name="Public Channel", group_id=None
        )
        cls.users = (
            cls.user_public + cls.user_portal + cls.user_employee + cls.user_admin
        )

    def test_open_guest_avatar(self):
        """Test access to open the avatar of a guest.
        There is no common channel or any interaction from the guest."""
        self._execute_subtests(
            self.guest_2,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_01_guest_avatar_private_channel(self):
        """Avatar access: guest target in a group channel, joined alongside the
        other users, no message posted."""
        self.private_channel._add_members(
            users=self.users, guests=self.guest | self.guest_2
        )
        self._execute_subtests(
            self.guest_2,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_01_partner_avatar_private_channel(self):
        """Avatar access: partner target in a group channel, joined alongside the
        other users, no message posted."""
        self.private_channel._add_members(
            users=self.users | self.user_employee_nopartner, guests=self.guest
        )
        self._execute_subtests(
            self.user_employee_nopartner.partner_id,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_02_guest_avatar_private_channel(self):
        """Avatar access: guest target in a group channel, joined alongside the
        other users, and posted a message."""
        self.private_channel._add_members(
            users=self.users, guests=self.guest | self.guest_2
        )
        self._post_message(self.private_channel, self.guest_2)
        self._execute_subtests(
            self.guest_2,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_02_partner_avatar_private_channel(self):
        """Avatar access: partner target in a group channel, joined alongside the
        other users, and posted a message."""
        self.private_channel._add_members(
            users=self.users | self.user_employee_nopartner, guests=self.guest
        )
        self._post_message(self.private_channel, self.user_employee_nopartner)
        self._execute_subtests(
            self.user_employee_nopartner.partner_id,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_03_guest_avatar_private_channel(self):
        """Avatar access: guest target in a group channel, joined alongside the
        other users, posted nothing, then left."""
        self.private_channel._add_members(
            users=self.users, guests=self.guest | self.guest_2
        )
        self.env["discuss.channel.member"].search(
            [
                ("guest_id", "=", self.guest_2.id),
                ("channel_id", "=", self.private_channel.id),
            ]
        ).unlink()
        self._execute_subtests(
            self.guest_2,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_03_partner_avatar_private_channel(self):
        """Avatar access: partner target in a group channel, joined alongside the
        other users, posted nothing, then left."""
        self.private_channel._add_members(
            users=self.users | self.user_employee_nopartner, guests=self.guest
        )
        self.env["discuss.channel.member"].search(
            [
                ("partner_id", "=", self.user_employee_nopartner.partner_id.id),
                ("channel_id", "=", self.private_channel.id),
            ]
        ).unlink()
        self._execute_subtests(
            self.user_employee_nopartner.partner_id,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_04_guest_avatar_private_channel(self):
        """Avatar access: guest target in a group channel, joined alongside the
        other users, posted a message, then left."""
        self.private_channel._add_members(
            users=self.users, guests=self.guest | self.guest_2
        )
        self._post_message(self.private_channel, self.guest_2)
        self.env["discuss.channel.member"].search(
            [
                ("guest_id", "=", self.guest_2.id),
                ("channel_id", "=", self.private_channel.id),
            ]
        ).unlink()
        self._execute_subtests(
            self.guest_2,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_04_partner_avatar_private_channel(self):
        """Avatar access: partner target in a group channel, joined alongside the
        other users, posted a message, then left."""
        self.private_channel._add_members(
            users=self.users | self.user_employee_nopartner, guests=self.guest
        )
        self._post_message(self.private_channel, self.user_employee_nopartner)
        self.env["discuss.channel.member"].search(
            [
                ("partner_id", "=", self.user_employee_nopartner.partner_id.id),
                ("channel_id", "=", self.private_channel.id),
            ]
        ).unlink()
        self._execute_subtests(
            self.user_employee_nopartner.partner_id,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_05_guest_avatar_private_channel(self):
        """Avatar access: guest target in a group channel nobody joined, having
        only posted a message."""
        self.private_channel.with_user(self.user_public).with_context(
            guest=self.guest_2
        ).sudo().message_post(
            body="Test", subtype_xmlid="mail.mt_comment", message_type="comment"
        )
        self._execute_subtests(
            self.guest_2,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_05_partner_avatar_private_channel(self):
        """Avatar access: partner target in a group channel nobody joined, having
        only been named author of a message."""
        self.private_channel.message_post(
            body="Test",
            subtype_xmlid="mail.mt_comment",
            message_type="comment",
            author_id=self.user_employee_nopartner.partner_id.id,
        )
        self._execute_subtests(
            self.user_employee_nopartner.partner_id,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_01_guest_avatar_public_channel(self):
        """Avatar access: guest target in a public channel nobody joined, having
        only posted a message."""
        self.public_channel.with_user(self.user_public).with_context(
            guest=self.guest_2
        ).sudo().message_post(
            body="Test", subtype_xmlid="mail.mt_comment", message_type="comment"
        )
        self._execute_subtests(
            self.guest_2,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_01_partner_avatar_public_channel(self):
        """Avatar access: partner target in a public channel nobody joined, having
        only posted a message."""
        self._post_message(self.public_channel, self.user_employee_nopartner)
        self._execute_subtests(
            self.user_employee_nopartner.partner_id,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_02_guest_avatar_public_channel(self):
        """Avatar access: guest target who joined a public channel the others did
        not, posted nothing, then left."""
        target_member = self.public_channel._add_members(guests=self.guest_2)
        target_member.unlink()
        self._execute_subtests(
            self.guest_2,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_02_partner_avatar_public_channel(self):
        """Avatar access: partner target who joined a public channel the others did
        not, posted nothing, then left."""
        target_member = self.public_channel._add_members(
            users=self.user_employee_nopartner
        )
        target_member.unlink()
        self._execute_subtests(
            self.user_employee_nopartner.partner_id,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_03_guest_avatar_public_channel(self):
        """Avatar access: guest target who joined a public channel the others did
        not, posted a message, then left."""
        target_member = self.public_channel._add_members(guests=self.guest_2)
        self._post_message(self.public_channel, self.guest_2)
        target_member.unlink()
        self._execute_subtests(
            self.guest_2,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )

    def test_03_partner_avatar_public_channel(self):
        """Avatar access: partner target who joined a public channel the others did
        not, posted a message, then left."""
        target_member = self.public_channel._add_members(
            users=self.user_employee_nopartner
        )
        self._post_message(self.public_channel, self.user_employee_nopartner)
        target_member.unlink()
        self._execute_subtests(
            self.user_employee_nopartner.partner_id,
            (
                (self.user_public, False),
                (self.guest, False),
                (self.user_portal, False),
                (self.user_employee, True),
                (self.user_admin, True),
            ),
        )
