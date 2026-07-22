"""Tests for the video URL parsing and embed-code helpers."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.html_editor.tools import get_video_embed_code, get_video_url_data

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
VIMEO_URL = "https://vimeo.com/76979871"


@tagged("post_install", "-at_install")
class TestVideoTools(TransactionCase):
    def test_youtube_url_parses_to_embed(self):
        """A watch URL maps to the youtube embed with rel disabled."""
        data = get_video_url_data(YOUTUBE_URL)
        self.assertEqual(data["platform"], "youtube")
        self.assertIn("/embed/dQw4w9WgXcQ", data["embed_url"])
        self.assertIn("rel=0", data["embed_url"])

    def test_youtube_autoplay_forces_mute_and_jsapi(self):
        """Autoplay implies mute and the js api (mobile contract)."""
        data = get_video_url_data(YOUTUBE_URL, autoplay=True)
        self.assertIn("autoplay=1", data["embed_url"])
        self.assertIn("mute=1", data["embed_url"])
        self.assertIn("enablejsapi=1", data["embed_url"])

    def test_youtube_loop_carries_playlist(self):
        """Looping a youtube video requires the playlist parameter."""
        data = get_video_url_data(YOUTUBE_URL, loop=True)
        self.assertIn("loop=1", data["embed_url"])
        self.assertIn("playlist=dQw4w9WgXcQ", data["embed_url"])

    def test_vimeo_url_parses_with_do_not_track(self):
        """Vimeo embeds always request do-not-track."""
        data = get_video_url_data(VIMEO_URL)
        self.assertEqual(data["platform"], "vimeo")
        self.assertIn("player.vimeo.com/video/76979871", data["embed_url"])
        self.assertIn("dnt=1", data["embed_url"])

    def test_invalid_url_reports_error(self):
        """A non-video URL yields the error payload (boundary)."""
        data = get_video_url_data("https://example.com/not-a-video")
        self.assertTrue(data.get("error"))

    def test_embed_code_wraps_iframe_or_none(self):
        """Valid URLs wrap into an iframe; invalid ones return None."""
        code = get_video_embed_code(YOUTUBE_URL)
        self.assertIn("<iframe", str(code))
        self.assertIn("/embed/dQw4w9WgXcQ", str(code))
        self.assertIsNone(get_video_embed_code("https://example.com/not-a-video"))
