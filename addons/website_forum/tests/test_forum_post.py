from odoo import fields

from odoo.addons.website_forum.tests.common import TestForumCommon


class TestForumPost(TestForumCommon):
    def test_get_related_posts(self):
        forum_tags = self.env["forum.tag"].create(
            [
                {
                    "name": f"tag_{i}",
                    "forum_id": self.forum.id,
                }
                for i in range(10)
            ]
        )
        forum_posts = self.env["forum.post"].create(
            [
                {
                    "content": "A post ...",
                    "forum_id": self.forum.id,
                    "name": "Post...",
                    "tag_ids": forum_tags[:i],
                    "last_activity_date": fields.Datetime.subtract(
                        fields.Datetime.now(), days=i
                    ),
                }
                for i in range(len(forum_tags) + 1)
            ]
        )
        self.assertFalse(forum_posts[0].tag_ids)
        self.assertEqual(forum_posts[0]._get_related_posts(), self.env["forum.post"])
        self.assertEqual(forum_posts[1]._get_related_posts(), forum_posts[2:7])
        self.assertEqual(
            forum_posts[-1]._get_related_posts(),
            forum_posts[len(forum_posts) - 6 : -1][::-1],
        )
        self.assertEqual(self.post.tag_ids.post_ids, self.post)
        self.assertEqual(forum_posts[0]._get_related_posts(), self.env["forum.post"])
        forum_posts.write({"tag_ids": forum_tags.ids})
        self.assertEqual(forum_posts[0]._get_related_posts(), forum_posts[1:6])
        self.assertEqual(forum_posts[-1]._get_related_posts(), forum_posts[:5])
