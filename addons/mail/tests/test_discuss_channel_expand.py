from markupsafe import Markup

from odoo.tests.common import HttpCase, tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("-at_install", "post_install")
class TestDiscussChannelExpand(HttpCase, MailCommon):
    def test_channel_expand_tour(self):
        testuser = self.env["res.users"].create(
            {
                "email": "testuser@testuser.com",
                "group_ids": [(6, 0, [self.ref("base.group_user")])],
                "name": "Test User",
                "login": "testuser",
                "password": "testuser",
            }
        )
        DiscussChannelAsUser = self.env["discuss.channel"].with_user(testuser)
        channel = DiscussChannelAsUser._create_channel(
            name="test-mail-channel-expand-tour", group_id=self.ref("base.group_user")
        )
        channel.message_post(
            body=Markup("<p>test-message-mail-channel-expand-tour</p>"),
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        self._reset_bus()
        self.start_tour(
            "/odoo",
            "mail/static/tests/tours/discuss_channel_expand_test_tour.js",
            login="testuser",
        )
