from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.product.tests.common import ProductCommon


@tagged("post_install", "-at_install")
class TestProductFavorite(ProductCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal = [Command.link(cls.env.ref("base.group_user").id)]
        cls.alice, cls.bob = cls.env["res.users"].create(
            [
                {"name": "Alice", "login": "product_fav_alice", "group_ids": internal},
                {"name": "Bob", "login": "product_fav_bob", "group_ids": internal},
            ]
        )
        cls.template = cls.env["product.template"].create({"name": "Starrable"})

    def test_is_favorite_is_the_same_for_everyone(self):
        self.template.is_favorite = True

        self.assertTrue(self.template.with_user(self.alice).is_favorite)
        self.assertTrue(self.template.with_user(self.bob).is_favorite)

    def test_is_user_favorite_is_per_user_and_leaves_the_global_flag_alone(self):
        self.template.is_favorite = True

        self.template.with_user(self.alice).is_user_favorite = True

        self.assertTrue(self.template.with_user(self.alice).is_user_favorite)
        self.assertFalse(self.template.with_user(self.bob).is_user_favorite)
        self.assertTrue(self.template.is_favorite)

    def test_a_variant_stars_its_template_without_write_access(self):
        variant = self.template.product_variant_ids[:1]
        as_alice = variant.with_user(self.alice)
        with self.assertRaises(AccessError):
            as_alice.write({"default_code": "nope"})

        as_alice.write({"is_user_favorite": True})

        self.assertTrue(self.template.with_user(self.alice).is_user_favorite)
        self.assertTrue(as_alice.is_user_favorite)
        self.assertFalse(variant.with_user(self.bob).is_user_favorite)
