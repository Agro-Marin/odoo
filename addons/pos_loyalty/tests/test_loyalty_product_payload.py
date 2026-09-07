import base64

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged("post_install", "-at_install")
class TestPosLoyaltyProductPayload(CommonPosTest):
    """A reward product reaches the terminal through an append after super(), so it
    has to come out of the loader shaped like every other row."""

    def setUp(self):
        super().setUp()
        self.config = self.pos_config_usd
        self.config.open_ui()
        self.env["loyalty.program"].search([]).write({"active": False})
        self.reward_product = self.env["product.product"].create(
            {
                "name": "Reward not otherwise loadable",
                "type": "consu",
                "list_price": 5.0,
                "available_in_pos": False,
                "taxes_id": False,
                "image_1920": self._an_image(),
            }
        )
        self.env["loyalty.program"].create(
            {
                "name": "Payload probe program",
                "program_type": "promotion",
                "trigger": "auto",
                "applies_on": "current",
                "reward_ids": [
                    Command.create(
                        {
                            "reward_type": "product",
                            "reward_product_id": self.reward_product.id,
                            "reward_product_qty": 1,
                            "required_points": 2,
                        }
                    )
                ],
            }
        )

    def _an_image(self):
        # a real 1x1 png, not a donor search: CommonPosTest builds its own products
        # and none carries an image, so a missing donor would make the assertion
        # below pass on any tree at all
        return base64.b64encode(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
                "DwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
            )
        )

    def _reward_row(self):
        data = {"pos.config": [{"_pos_special_products_ids": []}]}
        rows = self.env["product.template"]._load_pos_data_search_read(
            data, self.config
        )
        template_id = self.reward_product.product_tmpl_id.id
        matching = [row for row in rows if row["id"] == template_id]
        self.assertEqual(len(matching), 1, "the reward product must be loaded once")
        return matching[0]

    def test_a_reward_products_image_is_a_flag_not_its_bytes(self):
        self.assertIsInstance(
            self._reward_row()["image_128"],
            bool,
            "the terminal builds the /web/image url itself; the bytes are payload "
            "nobody reads",
        )

    def test_a_reward_product_carries_its_archived_combinations(self):
        self.assertIn("_archived_combinations", self._reward_row())
