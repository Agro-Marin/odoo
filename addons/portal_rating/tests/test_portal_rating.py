# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestPortalRating(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Message = cls.env["mail.message"]
        cls.Rating = cls.env["rating.rating"]

    def test_format_properties_exclude_rating_by_default(self):
        """Rating fields are not requested unless the caller opts in."""
        names = self.Message._portal_get_default_format_properties_names()
        self.assertNotIn("rating", names)

    def test_format_properties_include_rating_on_option(self):
        """The rating_include option adds the rating fields to the request."""
        names = self.Message._portal_get_default_format_properties_names(
            options={"rating_include": True}
        )
        self.assertIn("rating", names)
        self.assertIn("rating_value", names)

    def test_format_rating_with_publisher(self):
        """A rating with a publisher exposes the avatar, name, and comment."""
        formatted = self.Message._portal_message_format_rating(
            {
                "publisher_id": [7, "Bob"],
                "publisher_comment": "Thanks!",
                "publisher_datetime": fields.Datetime.now(),
            }
        )
        self.assertEqual(formatted["publisher_id"], 7)
        self.assertEqual(formatted["publisher_name"], "Bob")
        self.assertEqual(formatted["publisher_comment"], "Thanks!")
        self.assertEqual(
            formatted["publisher_avatar"],
            "/web/image/res.partner/7/avatar_128/50x50",
        )

    def test_format_rating_without_publisher(self):
        """A rating with no publisher blanks the avatar, name, and comment."""
        formatted = self.Message._portal_message_format_rating(
            {
                "publisher_id": False,
                "publisher_comment": False,
                "publisher_datetime": False,
            }
        )
        self.assertEqual(formatted["publisher_id"], False)
        self.assertEqual(formatted["publisher_name"], "")
        self.assertEqual(formatted["publisher_comment"], "")
        self.assertEqual(formatted["publisher_avatar"], "")
        self.assertEqual(formatted["publisher_datetime"], "")

    def test_synchronize_publisher_values_fills_metadata(self):
        """A publisher comment auto-stamps the publisher partner and datetime."""
        values = self.Rating._synchronize_publisher_values(
            {"publisher_comment": "Nice"}
        )
        self.assertEqual(values["publisher_id"], self.env.user.partner_id.id)
        self.assertTrue(values["publisher_datetime"])

    def test_publisher_comment_requires_write_access(self):
        """Commenting a rating needs write access on the related record."""
        company = self.env.ref("base.main_company")
        rating = self.Rating.create(
            {
                "res_model_id": self.env["ir.model"]._get("res.company").id,
                "res_id": company.id,
            }
        )
        restricted = new_test_user(
            self.env, login="rating_restricted", groups="base.group_user"
        )
        with self.assertRaises(AccessError):
            rating.with_user(restricted)._check_synchronize_publisher_values()
