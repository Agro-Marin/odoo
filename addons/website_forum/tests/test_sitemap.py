from datetime import datetime
from unittest.mock import patch

from freezegun import freeze_time

from odoo.tests import tagged

from odoo.addons.website_forum.tests.common import TestForumCommon


@tagged("post_install", "-at_install")
class TestWebsiteControllers(TestForumCommon):
    def test_01_forum_sitemap(self):
        website = self.env["website"].browse(1)

        # Simulate post from 2023-05-31. `cr.now()` is annotated to return a
        # datetime and callers rely on it -- `mail_thread._is_notification_scheduled`
        # reads `.tzinfo` off it -- so the mock returns one, as every other
        # `patch.object(self.env.cr, "now", ...)` in the tree does.
        posted_on = datetime(2023, 5, 31)
        with (
            freeze_time(posted_on),
            patch.object(self.env.cr, "now", lambda: posted_on),
        ):
            self.post.name = "RenameIt"  # update write_date
            self.post._update_last_activity()  # update last_activity_date

        locs = website._enumerate_pages(
            query_string="/forum/%s" % self.env["ir.http"]._slug(self.forum)
        )
        self.assertEqual(next(iter(locs))["lastmod"].strftime("%Y-%m-%d"), "2023-05-31")

        # Edit post content the 2024-01-01
        edited_on = datetime(2024, 1, 1)
        with (
            freeze_time(edited_on),
            patch.object(self.env.cr, "now", lambda: edited_on),
        ):
            self.post.content = "I am a bird"  # update write_date

        locs = website._enumerate_pages(
            query_string="/forum/%s" % self.env["ir.http"]._slug(self.forum)
        )
        self.assertEqual(next(iter(locs))["lastmod"].strftime("%Y-%m-%d"), "2024-01-01")
