from odoo.modules.module import get_module_path, load_script
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAccountConfigMigrationTaxSettings(TransactionCase):
    # account 1.26 runs on a database whose company still holds the accounting
    # columns; three of them moved on to tax.config (3d4c31c07d91), so the
    # script finds them on res_company and not on account_config

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = load_script(
            f"{get_module_path('account')}/migrations/1.26/"
            "post-migrate_account_config_rows.py",
            "account_1_26_post_migrate_account_config_rows",
        )
        cls.italy = cls.env.ref("base.it")
        cls.custom = cls.env["res.company"].create({"name": "Per line, tax included"})
        cls.plain = cls.env["res.company"].create({"name": "Defaults"})
        cr = cls.env.cr
        cls.env.flush_all()
        # the company as it stood before account 1.26
        cr.execute(
            """
            ALTER TABLE res_company
                ADD COLUMN chart_template VARCHAR,
                ADD COLUMN account_fiscal_country_id INTEGER,
                ADD COLUMN account_price_include VARCHAR,
                ADD COLUMN tax_calculation_rounding_method VARCHAR
            """
        )
        cr.execute(
            """
            UPDATE res_company c
               SET chart_template = ac.chart_template
              FROM account_config ac
             WHERE ac.company_id = c.id
            """
        )
        cr.execute(
            """
            UPDATE res_company
               SET account_fiscal_country_id = %s,
                   account_price_include = 'tax_included',
                   tax_calculation_rounding_method = 'round_per_line'
             WHERE id = %s
            """,
            [cls.italy.id, cls.custom.id],
        )
        cr.execute(
            """
            UPDATE res_company
               SET account_price_include = NULL,
                   tax_calculation_rounding_method = NULL
             WHERE id = %s
            """,
            [cls.plain.id],
        )

    def _settings(self, company):
        self.env.cr.execute(
            """
            SELECT account_fiscal_country_id, account_price_include,
                   tax_calculation_rounding_method
              FROM tax_config
             WHERE company_id = %s
            """,
            [company.id],
        )
        return self.env.cr.fetchone()

    def test_the_company_s_tax_settings_land_on_its_tax_configuration(self):
        self.script.migrate(self.env.cr, "1.25")
        self.assertEqual(
            self._settings(self.custom),
            (self.italy.id, "tax_included", "round_per_line"),
        )

    def test_a_company_without_a_tax_configuration_gets_one(self):
        self.env.cr.execute(
            "DELETE FROM tax_config WHERE company_id = %s", [self.custom.id]
        )
        self.script.migrate(self.env.cr, "1.25")
        self.assertEqual(
            self._settings(self.custom),
            (self.italy.id, "tax_included", "round_per_line"),
        )

    def test_an_unset_setting_takes_the_tax_configuration_s_default(self):
        self.script.migrate(self.env.cr, "1.25")
        _country, price_include, rounding = self._settings(self.plain)
        self.assertEqual((price_include, rounding), ("tax_excluded", "round_globally"))

    def test_tax_1_4_0_then_has_nothing_to_move(self):
        # tax loads before account: on this path account_config never held
        # the three, so tax's own move must leave what 1.26 wrote alone
        self.script.migrate(self.env.cr, "1.25")
        tax_script = load_script(
            f"{get_module_path('tax')}/migrations/1.4.0/post-migrate.py",
            "tax_1_4_0_post_migrate",
        )
        tax_script.migrate(self.env.cr, "19.0.1.3.0")
        self.assertEqual(
            self._settings(self.custom),
            (self.italy.id, "tax_included", "round_per_line"),
        )
