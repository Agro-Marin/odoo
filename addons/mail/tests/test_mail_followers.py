from odoo.tests import tagged, users

from odoo.addons.mail.tests import common


@tagged("-at_install", "post_install", "mail_followers")
class TestMailFollowersAudit(common.MailCommon):
    """`mail.followers` keeps who subscribed whom and when.

    The interesting half is that `_create_followers` writes the rows with a raw
    bulk INSERT, so the ORM never gets to fill the log-access columns on its own.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["res.partner"].create({"name": "Followed Document"})
        cls.watcher = cls.env["res.partner"].create({"name": "Watcher"})

    def test_followers_model_logs_access(self):
        self.assertTrue(
            self.env["mail.followers"]._log_access,
            "mail.followers is audited, so the log-access columns exist",
        )

    @users("employee")
    def test_subscribing_records_who_and_when(self):
        record = self.record.with_user(self.env.user)
        record.message_subscribe(partner_ids=self.watcher.ids)

        follower = self.env["mail.followers"].search(
            [
                ("res_model", "=", record._name),
                ("res_id", "=", record.id),
                ("partner_id", "=", self.watcher.id),
            ]
        )
        self.assertEqual(len(follower), 1)
        self.assertEqual(
            follower.create_uid,
            self.env.user,
            "the raw INSERT in _create_followers still stamps the author",
        )
        self.assertTrue(follower.create_date, "and the moment it happened")

    @users("employee")
    def test_subscribing_many_at_once_stamps_every_row(self):
        record = self.record.with_user(self.env.user)
        others = self.env["res.partner"].create(
            [{"name": "Watcher %02d" % i} for i in range(3)]
        )

        record.message_subscribe(partner_ids=others.ids)

        followers = self.env["mail.followers"].search(
            [
                ("res_model", "=", record._name),
                ("res_id", "=", record.id),
                ("partner_id", "in", others.ids),
            ]
        )
        self.assertEqual(len(followers), 3, "one INSERT, three rows")
        self.assertEqual(followers.create_uid, self.env.user)
        self.assertFalse(
            [f for f in followers if not f.create_date],
            "the unnest() bulk insert leaves no row unstamped",
        )
