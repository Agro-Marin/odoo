import psycopg

from odoo.tests.common import users
from odoo.tools import mute_logger

from odoo.addons.website_slides.tests import common as slides_common


class TestSlideInternals(slides_common.SlidesCase):
    def test_compute_category_completion_time(self):
        self.category2 = (
            self.env["slide.slide"]
            .with_user(self.user_officer)
            .create(
                {
                    "name": "Cooking Tips For Dieting",
                    "channel_id": self.channel.id,
                    "is_category": True,
                    "is_published": True,
                    "sequence": 5,
                }
            )
        )
        self.slide_4 = (
            self.env["slide.slide"]
            .with_user(self.user_officer)
            .create(
                {
                    "name": "Vegan Diet",
                    "channel_id": self.channel.id,
                    "slide_category": "document",
                    "is_published": True,
                    "completion_time": 5.0,
                    "sequence": 6,
                }
            )
        )
        self.slide_5 = (
            self.env["slide.slide"]
            .with_user(self.user_officer)
            .create(
                {
                    "name": "Normal Diet",
                    "channel_id": self.channel.id,
                    "slide_category": "document",
                    "is_published": True,
                    "completion_time": 1.5,
                    "sequence": 7,
                }
            )
        )

        before_unlink = self.category2.completion_time
        self.assertEqual(
            before_unlink, self.slide_4.completion_time + self.slide_5.completion_time
        )

        self.channel.slide_ids[6].sudo().unlink()
        self.category2._compute_category_completion_time()

        after_unlink = self.category2.completion_time
        self.assertEqual(after_unlink, self.slide_4.completion_time)

    @mute_logger("odoo.db")
    @users("user_manager")
    def test_slide_create_vote_constraint(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.env["slide.slide.partner"].create(
                {
                    "slide_id": self.slide.id,
                    "channel_id": self.channel.id,
                    "partner_id": self.user_manager.partner_id.id,
                    "vote": 2,
                }
            )

    @users("user_manager")
    def test_slide_user_has_completed_category(self):
        uncategorized_slide = self.channel.slide_ids.filtered(
            lambda s: not s.is_category and not s.category_id
        )
        self.assertEqual(len(uncategorized_slide), 1)
        self.assertFalse(uncategorized_slide.user_has_completed)
        self.assertFalse(uncategorized_slide.user_has_completed_category)
        uncategorized_slide.user_has_completed = True
        self.assertFalse(uncategorized_slide.user_has_completed_category)

        category_slides = self.category.slide_ids
        self.assertEqual(len(category_slides), 2)
        self.assertFalse(any(category_slides.mapped("user_has_completed")))
        self.assertFalse(category_slides[0].user_has_completed_category)
        category_slides[0].user_has_completed = True
        self.assertFalse(category_slides[0].user_has_completed_category)
        for slide in category_slides:
            slide.user_has_completed = True
        self.assertTrue(category_slides[0].user_has_completed_category)

    def test_comments_count_matches_visible_chatter(self):
        slide = self.slide
        slide.message_post(
            body="Visible comment",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        slide.message_post(
            body="Internal note",
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )
        self.env["mail.message"].create(
            {
                "model": "slide.slide",
                "res_id": slide.id,
                "message_type": "comment",
                "subtype_id": self.env.ref("mail.mt_comment").id,
                "body": "",
            }
        )
        slide.invalidate_recordset(["comments_count"])
        self.assertEqual(slide.comments_count, 1)

    def test_change_content_type(self):
        slide = (
            self.env["slide.slide"]
            .with_context(website_slides_skip_fetch_metadata=True)
            .create(
                {
                    "name": "dummy",
                    "channel_id": self.channel.id,
                    "slide_category": "video",
                    "is_published": True,
                    "url": "https://youtu.be/W0JQcpGLSFw",
                }
            )
        )

        slide.write({"slide_category": "article", "html_content": "<p>Hello</p>"})
        self.assertTrue(slide.html_content)
        self.assertFalse(slide.url)

        slide.slide_category = "document"
        self.assertFalse(slide.html_content)


class TestVideoFromURL(slides_common.SlidesCase):
    def test_video_youtube(self):
        youtube_urls = {
            "W0JQcpGLSFw": [
                "https://youtu.be/W0JQcpGLSFw",
                "https://www.youtube.com/watch?v=W0JQcpGLSFw",
                "https://www.youtube.com/watch?v=W0JQcpGLSFw&list=PL1-aSABtP6ACZuppkBqXFgzpNb2nVctZx",
                "https://www.youtube.com/live/W0JQcpGLSFw?feature=shared",
                "https://youtube.com/shorts/W0JQcpGLSFw?si=N9xYS2w3f1BWuhU9",
            ],
            "vmhB-pt7EfA": [
                "https://youtu.be/vmhB-pt7EfA",
                "https://www.youtube.com/watch?feature=youtu.be&v=vmhB-pt7EfA",
                "https://www.youtube.com/watch?v=vmhB-pt7EfA&list=PL1-aSABtP6ACZuppkBqXFgzpNb2nVctZx&index=7",
            ],
            "hlhLv0GN1hA": [
                "https://www.youtube.com/v/hlhLv0GN1hA",
                "https://www.youtube.com/embed/hlhLv0GN1hA",
                "https://www.youtube-nocookie.com/embed/hlhLv0GN1hA",
                "https://m.youtube.com/watch?v=hlhLv0GN1hA",
            ],
        }

        Slide = self.env["slide.slide"].with_context(
            website_slides_skip_fetch_metadata=True
        )

        for youtube_id, urls in youtube_urls.items():
            for url in urls:
                with self.subTest(url=url, id=youtube_id):
                    slide = Slide.create(
                        {
                            "name": "dummy",
                            "channel_id": self.channel.id,
                            "url": url,
                            "slide_category": "video",
                        }
                    )
                    self.assertEqual("youtube", slide.video_source_type)
                    self.assertEqual(youtube_id, slide.youtube_id)

    def test_video_google_drive(self):
        google_drive_urls = {
            "1qU5nHVNbz_r84P_IS5kDzoCuC1h5ZAZR": [
                "https://drive.google.com/file/d/1qU5nHVNbz_r84P_IS5kDzoCuC1h5ZAZR/view?usp=sharing",
                "https://drive.google.com/file/d/1qU5nHVNbz_r84P_IS5kDzoCuC1h5ZAZR",
            ],
        }

        Slide = self.env["slide.slide"].with_context(
            website_slides_skip_fetch_metadata=True
        )

        for google_drive_id, urls in google_drive_urls.items():
            for url in urls:
                with self.subTest(url=url, id=google_drive_id):
                    slide = Slide.create(
                        {
                            "name": "dummy",
                            "channel_id": self.channel.id,
                            "url": url,
                            "slide_category": "video",
                        }
                    )
                    self.assertEqual("google_drive", slide.video_source_type)
                    self.assertEqual(google_drive_id, slide.google_drive_id)

    def test_video_vimeo(self):
        vimeo_urls = {
            "545859999": [
                "https://vimeo.com/545859999",
                "https://vimeo.com/545859999?autoplay=1",
            ],
            "551979139": [
                "https://vimeo.com/channels/staffpicks/551979139",
                "https://vimeo.com/channels/staffpicks/551979139?autoplay=1",
            ],
            "545859999/94dd03ddb0": [
                "https://vimeo.com/545859999/94dd03ddb0",
                "https://vimeo.com/545859999/94dd03ddb0?autoplay=1",
            ],
        }

        Slide = self.env["slide.slide"].with_context(
            website_slides_skip_fetch_metadata=True
        )

        for vimeo_id, urls in vimeo_urls.items():
            for url in urls:
                with self.subTest(url=url, id=vimeo_id):
                    slide = Slide.create(
                        {
                            "name": "dummy",
                            "channel_id": self.channel.id,
                            "url": url,
                            "slide_category": "video",
                        }
                    )
                    self.assertEqual("vimeo", slide.video_source_type)
                    self.assertEqual(vimeo_id, slide.vimeo_id)
