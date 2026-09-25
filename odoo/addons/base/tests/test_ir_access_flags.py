from odoo.tests import TransactionCase, tagged

MODEL = "res.partner.industry"


@tagged("post_install", "-at_install")
class TestAccessFlagsFollowTheOperation(TransactionCase):
    # the shape base 1.106 left on the device rows: `operation` rewritten by
    # SQL, and the Read / Update / Create / Delete flags stored beside it
    # still saying what it was

    def _row(self, operation):
        return self.env["ir.access"].create(
            {
                "name": "flags",
                "model_id": self.env["ir.model"]._get_id(MODEL),
                "group_id": self.env.ref("base.group_system").id,
                "kind": "permission",
                "operation": operation,
            }
        )

    def _rewrite(self, row, operation):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ir_access SET operation = %s WHERE id = %s", [operation, row.id]
        )
        row.invalidate_recordset()

    def _flags(self, row):
        return (row.for_read, row.for_write, row.for_create, row.for_unlink)

    def test_the_flags_are_those_of_the_operation_whoever_wrote_it(self):
        row = self._row("r")
        self._rewrite(row, "ru")
        self.assertEqual(self._flags(row), (True, True, False, False))

    def test_ticking_a_flag_after_a_rewrite_keeps_the_rewritten_letters(self):
        row = self._row("r")
        self._rewrite(row, "ru")
        row.for_unlink = True
        self.assertEqual(row.operation, "rud")

    def test_the_filters_read_the_operation(self):
        row = self._row("r")
        self._rewrite(row, "cu")
        Access = self.env["ir.access"].with_context(active_test=False)
        self.assertIn(row, Access.search([("for_write", "=", True)]))
        self.assertIn(row, Access.search([("for_create", "=", True)]))
        self.assertNotIn(row, Access.search([("for_read", "=", True)]))
        self.assertIn(row, Access.search([("for_read", "=", False)]))
        self.assertIn(row, Access.search([("for_read", "!=", True)]))

    def test_a_row_for_verbs_only_holds_no_crud_flag(self):
        row = self._row("r")
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ir_access SET operation = NULL, verbs = 'post' WHERE id = %s",
            [row.id],
        )
        row.invalidate_recordset()
        self.assertEqual(self._flags(row), (False, False, False, False))
        Access = self.env["ir.access"].with_context(active_test=False)
        self.assertIn(row, Access.search([("for_read", "=", False)]))

    def test_the_flags_are_not_columns(self):
        self.assertFalse(
            any(
                self.env["ir.access"]._fields[f"for_{operation}"].store
                for operation in ("read", "write", "create", "unlink")
            )
        )
