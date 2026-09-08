from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLotViewGroups(TransactionCase):
    """`stock.lot.location_id` is a counterpart of the quants, so it only says
    something once there is more than one place for the lot to be in."""

    def _visible_lot_form_fields(self, user):
        """Names of the fields the lot form actually paints for `user`.

        `get_view` strips what the user's groups do not grant, but it also
        *injects* the fields other nodes name in a modifier, hard-invisible and
        tagged `data-used-by`. `location_id` is one of those -- `partner_ids`
        reads it in its own `invisible` -- so counting occurrences would answer
        the wrong question.
        """
        arch = (
            self.env["stock.lot"]
            .with_user(user)
            .get_view(self.env.ref("stock.view_stock_lot_form").id, "form")["arch"]
        )
        return [
            node.get("name")
            for node in etree.fromstring(arch).xpath("//field")
            if node.get("invisible") != "True"
        ]

    def test_location_is_hidden_without_multi_locations(self):
        manager = self.env["res.users"].create(
            {
                "name": "Single location manager",
                "login": "single_location_manager",
                "group_ids": [
                    (6, 0, [self.env.ref("stock.group_stock_manager").id]),
                ],
            }
        )
        self.assertFalse(
            manager.has_group("stock.group_stock_multi_locations"),
            "the fixture needs a manager without storage locations",
        )
        self.assertNotIn(
            "location_id",
            self._visible_lot_form_fields(manager),
            "a manager who has a single location has nothing to read there",
        )

    def test_location_is_shown_with_multi_locations(self):
        user = self.env["res.users"].create(
            {
                "name": "Multi location user",
                "login": "multi_location_user",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("stock.group_stock_user").id,
                            self.env.ref("stock.group_stock_multi_locations").id,
                        ],
                    ),
                ],
            }
        )
        self.assertIn("location_id", self._visible_lot_form_fields(user))
