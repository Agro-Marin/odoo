from odoo.tests.common import TransactionCase


class TestEnv(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        user = cls.env["res.users"].create(
            {
                "name": "superuser",
                "login": "superuser",
                "password": "superuser",
                "group_ids": [(6, 0, cls.env.user.group_ids.ids)],
            }
        )
        cls.env = cls.env(user=user)

        cls.sudo_env = cls.env(su=True)

    def test_env_company_part_01(self):
        company = self.env["res.company"].create(
            {
                "name": "Test Company",
            }
        )
        self.env.user.write(
            {
                "company_id": company.id,
                "company_ids": [(4, company.id), (4, self.env.company.id)],
            }
        )
        self.assertEqual(self.env.company, self.env.user.company_id)
        self.assertTrue(self.env.company.exists())
        self.assertEqual(self.sudo_env.company, self.env.user.company_id)
        self.assertTrue(self.sudo_env.company.exists())

    def test_env_company_part_02(self):
        self.assertEqual(self.env.company, self.env.user.company_id)
        self.assertTrue(self.env.company.exists())
        self.assertEqual(self.sudo_env.company, self.env.user.company_id)
        self.assertTrue(self.sudo_env.company.exists())
