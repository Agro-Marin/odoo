import odoo.tests
from odoo.tools import mute_logger

from odoo.addons.base.tests.common import HttpCaseWithUserDemo


@odoo.tests.common.tagged("post_install", "-at_install")
class TestUi(HttpCaseWithUserDemo):
    def test_01_admin_widget_x2many(self):

        self.start_tour(
            "/odoo/action-test_orm.action_discussions",
            "widget_x2many",
            login="admin",
            timeout=120,
        )


@odoo.tests.tagged("-at_install", "post_install")
class TestUiTranslation(odoo.tests.HttpCase):
    @mute_logger("odoo.db", "odoo.http")
    def test_01_sql_constraints(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env.ref("base.module_test_orm")._update_translations(["fr_FR"])
        constraint = self.env.ref(
            "test_orm.constraint_test_orm_category_positive_color"
        )
        message = constraint.with_context(lang="fr_FR").message
        self.assertEqual(message, "La couleur doit être une valeur positive !")

        self.start_tour(
            "/odoo/action-test_orm.action_categories",
            "sql_constaint",
            login="admin",
        )
