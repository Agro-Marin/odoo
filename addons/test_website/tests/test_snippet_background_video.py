import odoo.tests


@odoo.tests.common.tagged("post_install", "-at_install")
class TestSnippetBackgroundVideo(odoo.tests.HttpCase):
    def test_snippet_background_video(self):
        self.start_tour("/", "snippet_background_video", login="admin")
