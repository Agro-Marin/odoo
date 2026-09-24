from odoo.tests import TransactionCase, tagged

MODEL = "res.partner.industry"


@tagged("post_install", "-at_install")
class TestStoredAccessDomainsResolve(TransactionCase):
    # the shape production's noupdate base.user_device_logs had once
    # res.device.log lost user_id: a row saved when its domain was valid, kept
    # as it was while the model changed under it

    def _row(self, domain):
        row = self.env["ir.access"].create(
            {
                "name": "stale",
                "model_id": self.env["ir.model"]._get_id(MODEL),
                "group_id": self.env.ref("base.group_user").id,
                "kind": "permission",
                "operation": "r",
                "domain": "[('name', '!=', False)]",
            }
        )
        self.env.cr.execute(
            "UPDATE ir_access SET domain = %s WHERE id = %s", [domain, row.id]
        )
        row.invalidate_recordset(["domain"])
        return row

    def _unresolved(self, row):
        return [
            missing
            for access, missing in self.env["ir.access"]._unresolved_domains()
            if access == row
        ]

    def test_every_stored_domain_of_this_database_resolves(self):
        # run against a production restore after -u base, this is its gate
        unresolved = [
            f"{access.id} {access.model_id.model}: {missing}"
            for access, missing in self.env["ir.access"]._unresolved_domains()
        ]
        self.assertEqual(unresolved, [])

    def test_a_field_the_model_no_longer_has_is_named(self):
        row = self._row("[('user_id', '=', user.id)]")
        self.assertEqual(self._unresolved(row), [f"{MODEL}.user_id"])

    def test_a_path_is_followed_to_the_model_that_lacks_the_field(self):
        row = self._row("[('create_uid.partner_id.gone', '=', 1)]")
        self.assertEqual(self._unresolved(row), ["res.partner.gone"])

    def test_an_any_condition_is_read_on_its_comodel(self):
        row = self._row(
            "[('create_uid', 'any', [('login', '!=', False), ('gone', '=', user.id)])]"
        )
        self.assertEqual(self._unresolved(row), ["res.users.gone"])

    def test_a_valid_domain_names_nothing(self):
        row = self._row(
            "['|', ('create_uid', '=', user.id), "
            "('create_uid.company_ids', 'in', company_ids), "
            "('write_date.year_number', '=', 2026)] "
            "if user else []"
        )
        self.assertEqual(self._unresolved(row), [])

    def test_an_inactive_row_is_left_alone(self):
        row = self._row("[('user_id', '=', user.id)]")
        row.active = False
        self.assertEqual(self._unresolved(row), [])

    def test_the_load_logs_one_error_per_unresolved_row(self):
        row = self._row("[('user_id', '=', user.id)]")
        with self.assertLogs("odoo.addons.base.models.ir_access", "ERROR") as logs:
            self.env["ir.access"]._log_unresolved_domains()
        mine = [line for line in logs.output if f"Access {row.id} " in line]
        self.assertEqual(len(mine), 1)
        self.assertIn(f"{MODEL}.user_id", mine[0])
