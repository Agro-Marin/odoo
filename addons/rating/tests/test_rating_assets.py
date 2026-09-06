"""Pins that the rating JS models reach every bundle that builds a chatter."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRatingAssets(TransactionCase):
    JS_PARAMS = {"css": False, "js": True}
    COMMON = "/rating/static/src/core/common/"

    def _rating_files(self, bundle):
        paths = self.env["ir.asset"]._get_asset_paths(bundle, self.JS_PARAMS)
        return sorted(str(path) for path, *_ in paths if self.COMMON in str(path))

    def test_the_chatter_helpers_carry_the_rating_models(self):
        """`portal.assets_chatter_helpers` is the bundle a chatter is built from.

        Declaring the models one level up, on `portal.assets_chatter`, leaves
        them out of every bundle that assembles its own chatter from the
        helpers instead of including the whole frontend one -- Project
        Sharing's `project.webclient` being ours
        (`addons/project/__manifest__.py:201-204`). Such a client is handed a
        `rating_id` on every message (`models/mail_message.py:44`) for a field
        its `Message` model never declares.
        """
        self.assertTrue(
            self._rating_files("portal.assets_chatter_helpers"),
            "no rating model reaches portal.assets_chatter_helpers, so a "
            "chatter built from the helpers has none",
        )

    def test_the_frontend_chatter_still_carries_them(self):
        """The outer bundle keeps them, since it includes the helpers."""
        self.assertTrue(self._rating_files("portal.assets_chatter"))
