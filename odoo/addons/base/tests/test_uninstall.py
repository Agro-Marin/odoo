import unittest
from contextlib import contextmanager

from odoo import api
from odoo.modules.registry import Registry
from odoo.tests import common
from odoo.tests.common import BaseCase


@contextmanager
def environment():
    reg = Registry(common.get_db_name())
    with reg.cursor() as cr:
        yield api.Environment(cr, api.SUPERUSER_ID, {})


MODULE = "test_uninstall"
MODEL = "test_uninstall.model"


class TestUninstall(BaseCase):
    def test_01_install(self):
        with environment() as env:
            module = env["ir.module.module"].search([("name", "=", MODULE)])
            assert len(module) == 1
            module.button_install()
        Registry.new(common.get_db_name(), update_module=True)

        with environment() as env:
            self.assertIn("test_uninstall.model", env.registry)
            self.assertTrue(env["ir.model.data"].search([("module", "=", MODULE)]))
            self.assertTrue(env["ir.model.fields"].search([("model", "=", MODEL)]))

            env.cr.execute(r"""
                SELECT conname
                  FROM pg_constraint
                 WHERE conrelid = 'res_users'::regclass
                   AND conname LIKE 'res\_users\_test\_uninstall\_res\_user\_%'
                """)
            existing_constraints = [r[0] for r in env.cr.fetchall()]
            self.assertTrue(len(existing_constraints) == 4, existing_constraints)

    def test_02_uninstall(self):
        with environment() as env:
            module = env["ir.module.module"].search([("name", "=", MODULE)])
            assert len(module) == 1
            module.button_uninstall()
        Registry.new(common.get_db_name(), update_module=True)

        with environment() as env:
            self.assertNotIn("test_uninstall.model", env.registry)
            self.assertFalse(env["ir.model.data"].search([("module", "=", MODULE)]))
            self.assertFalse(env["ir.model.fields"].search([("model", "=", MODEL)]))

            env.cr.execute(r"""
                SELECT conname
                  FROM pg_constraint
                 WHERE conrelid = 'res_users'::regclass
                   AND conname LIKE 'res\_users\_test\_uninstall\_res\_user\_%'
                """)
            remaining_constraints = [r[0] for r in env.cr.fetchall()]
            self.assertFalse(remaining_constraints)


if __name__ == "__main__":
    unittest.main()
