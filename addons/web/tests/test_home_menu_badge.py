from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("web_unit", "web_menu", "post_install", "-at_install")
class TestHomeMenuBadge(TransactionCase):
    def test_an_empty_registry_answers_nothing(self):
        self.assertEqual(
            self.env["home.menu.badge"]._get_badges(),
            self.env["home.menu.badge"]._get_badges(),
            "the base implementation is stable",
        )

    def test_zeroes_never_reach_a_tile(self):
        self.patch(
            type(self.env["home.menu.badge"]),
            "_get_badges",
            lambda self: {"a.b": 0, "c.d": 3, "e.f": -1},
        )
        self.assertEqual(self.env["home.menu.badge"].get_badges(), {"c.d": 3})

    def test_a_model_the_reader_cannot_open_costs_no_count(self):
        reader = new_test_user(self.env, "badge_reader", groups="base.group_user")
        badge = self.env["home.menu.badge"].with_user(reader)
        self.assertEqual(
            badge._count_for("x.y", "ir.config_parameter", []),
            {},
            "a model an internal user cannot read contributes nothing",
        )

    def test_a_model_that_is_not_installed_costs_no_count(self):
        self.assertEqual(
            self.env["home.menu.badge"]._count_for("x.y", "no.such.model", []),
            {},
        )
