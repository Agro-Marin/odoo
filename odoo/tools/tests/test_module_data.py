import unittest

from odoo.tools.module_data import (
    READONLY_MERGED_MODULE,
    absorb_readonly_forerunners,
    adopt_xmlids,
)

BaseCase = unittest.TestCase


class _Cursor:
    def __init__(self, xmlids, installed=()):
        self.xmlids = dict(xmlids)
        self.modules = dict.fromkeys(installed, "installed")
        self.statements = []
        self._result = []
        self.rowcount = 0

    def execute(self, query, params=None):
        code = " ".join(str(query.code).split())
        params = list(query.params) if params is None else list(params)
        self.statements.append((code, params))
        self._result = []
        self.rowcount = 0
        if code.startswith("SELECT id, name FROM ir_model_data WHERE module = %s"):
            self._result = [
                (rid, name)
                for rid, (mod, name) in self.xmlids.items()
                if mod == params[0]
            ]
        elif code.startswith(
            "UPDATE ir_model_data SET module = %s, name = %s WHERE id = %s"
        ):
            to_module, new_name, rid = params
            if rid in self.xmlids:
                self.xmlids[rid] = (to_module, new_name)
                self.rowcount = 1
        elif code.startswith(
            "UPDATE ir_model_data SET module = %s, name = %s WHERE module = %s AND name = %s"
        ):
            to_module, new_name, from_module, old_name = params
            for rid, (mod, name) in self.xmlids.items():
                if (mod, name) == (from_module, old_name):
                    self.xmlids[rid] = (to_module, new_name)
                    self.rowcount += 1
        elif code.startswith("SELECT 1 FROM ir_model_data WHERE module = %s"):
            self._result = (
                [(1,)] if any(m == params[0] for m, _ in self.xmlids.values()) else []
            )
        elif code.startswith("UPDATE ir_module_module SET state = 'uninstalled'"):
            if self.modules.get(params[0], "uninstalled") != "uninstalled":
                self.modules[params[0]] = "uninstalled"
                self.rowcount = 1
        elif code.startswith("DELETE FROM ir_module_module_dependency"):
            pass
        else:
            raise AssertionError(f"unexpected statement: {code}")

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


FORERUNNER_ROWS = {
    1: ("sale_group_readonly", "group_sale_readonly"),
    2: ("sale_group_readonly", "access_crm_tag_readonly"),
    3: ("sale_group_readonly", "access_account_move_readonly"),
    4: ("stock_group_readonly", "group_stock_readonly"),
    5: ("stock_group_readonly", "access_stock_picking_readonly"),
    6: ("purchase_group_readonly", "access_stock_picking_readonly"),
    7: ("mail", "group_mail_something"),
}


class TestAbsorbReadonlyForerunners(BaseCase):
    def test_rows_move_under_the_merged_module_with_domain_suffixed_acl_names(self):
        cr = _Cursor(
            FORERUNNER_ROWS, installed=("sale_group_readonly", "stock_group_readonly")
        )
        moved = absorb_readonly_forerunners(cr)
        self.assertEqual(moved, 6)
        merged = {
            name for mod, name in cr.xmlids.values() if mod == READONLY_MERGED_MODULE
        }
        self.assertEqual(
            merged,
            {
                "group_sale_readonly",
                "access_crm_tag_sale_readonly",
                "access_account_move_sale_readonly",
                "group_stock_readonly",
                "access_stock_picking_stock_readonly",
                "access_stock_picking_purchase_readonly",
            },
        )
        self.assertEqual(cr.xmlids[1], (READONLY_MERGED_MODULE, "group_sale_readonly"))
        self.assertEqual(cr.xmlids[7], ("mail", "group_mail_something"))

    def test_the_forerunner_modules_are_retired_once_emptied(self):
        cr = _Cursor(
            FORERUNNER_ROWS, installed=("sale_group_readonly", "stock_group_readonly")
        )
        absorb_readonly_forerunners(cr)
        self.assertEqual(cr.modules["sale_group_readonly"], "uninstalled")
        self.assertEqual(cr.modules["stock_group_readonly"], "uninstalled")

    def test_a_database_that_took_the_intermediate_step_is_a_no_op(self):
        already = {
            1: (READONLY_MERGED_MODULE, "group_sale_readonly"),
            2: ("sales_team", "group_sale_readonly"),
        }
        cr = _Cursor(already)
        self.assertEqual(absorb_readonly_forerunners(cr), 0)
        self.assertEqual(cr.xmlids, already)
        self.assertEqual(cr.modules, {})

    def test_the_split_adoption_then_finds_the_absorbed_rows(self):
        cr = _Cursor(FORERUNNER_ROWS, installed=("sale_group_readonly",))
        self.assertEqual(
            adopt_xmlids(
                cr, READONLY_MERGED_MODULE, "sales_team", ("group_sale_readonly",)
            ),
            0,
        )
        absorb_readonly_forerunners(cr)
        self.assertEqual(
            adopt_xmlids(
                cr,
                READONLY_MERGED_MODULE,
                "sales_team",
                ("group_sale_readonly", "access_crm_tag_sale_readonly"),
            ),
            2,
        )
        self.assertEqual(cr.xmlids[1], ("sales_team", "group_sale_readonly"))
        self.assertEqual(cr.xmlids[2], ("sales_team", "access_crm_tag_sale_readonly"))
