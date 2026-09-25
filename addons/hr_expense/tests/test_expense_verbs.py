from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

# row, persona, whose expense, verb: a cell the row alone grants, so switching
# the row off takes exactly that move away
ROW_CELLS = [
    line.split()
    for line in """
    access_hr_expense_decide_administrator admin admin approve
    access_hr_expense_decide_approver approver employee approve
    access_hr_expense_decide_team_approver department_head employee refuse
    access_hr_expense_decide_expense_manager expense_manager employee approve
    access_hr_expense_decide_team_below team_leader report refuse
    access_hr_expense_submit_reset employee employee submit
""".strip().splitlines()
]


@tagged("post_install", "-at_install")
class TestExpenseVerbs(TransactionCase):
    """Approving and refusing an expense are verbs of hr.expense, granted by
    security/ir_access.xml exactly as _get_cannot_approve_reason grants them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        team = "base.group_user,hr_expense.group_hr_expense_team_approver"
        groups = {
            "employee": "base.group_user",
            "report": "base.group_user",
            "expense_manager": "base.group_user",
            "department_head": team,
            "team_leader": team,
            "approver": "base.group_user,hr_expense.group_hr_expense_user",
            "admin": "base.group_user,hr_expense.group_hr_expense_manager",
        }
        cls.users = {
            key: new_test_user(cls.env, login=f"xverb_{key}", groups=spec)
            for key, spec in groups.items()
        }
        cls.employees = {
            key: cls.env["hr.employee"].create(
                {"name": f"Expense verb {key}", "user_id": user.id}
            )
            for key, user in cls.users.items()
        }
        department = cls.env["hr.department"].create(
            {"name": "Expense verbs", "manager_id": cls.employees["department_head"].id}
        )
        cls.employees["employee"].write(
            {
                "department_id": department.id,
                "expense_manager_id": cls.users["expense_manager"].id,
            }
        )
        cls.employees["report"].write(
            {
                "parent_id": cls.employees["team_leader"].id,
                "department_id": department.id,
            }
        )
        cls.employees["report"].expense_manager_id = False
        cls.product = cls.env["product.product"].create(
            {"name": "Expense verbs", "can_be_expensed": True, "standard_price": 0}
        )

    def _expense(self, whose, company=None):
        expense = self.env["hr.expense"].create(
            {
                "name": f"Expense of {whose}",
                "employee_id": self.employees[whose].id,
                "product_id": self.product.id,
                "total_amount_currency": 10,
                "company_id": (company or self.env.company).id,
            }
        )
        expense.sudo().review_state = "submitted"
        return expense

    def test_each_row_grants_its_move_and_only_it(self):
        for xmlid, persona, whose, verb in ROW_CELLS:
            with self.subTest(row=xmlid):
                mine = self._expense(whose).with_user(self.users[persona])
                self.assertTrue(mine.has_access(verb))
                row = self.env.ref(f"hr_expense.{xmlid}")
                row.active = False
                self.assertFalse(mine.has_access(verb), "no other row grants this move")
                row.active = True

    def test_an_expense_is_decided_in_the_companies_in_use(self):
        other = self.env["res.company"].create({"name": "Expense verbs elsewhere"})
        admin = self.users["admin"]
        admin.company_ids |= other
        elsewhere = self.env["hr.employee"].create(
            {"name": "Admin elsewhere", "user_id": admin.id, "company_id": other.id}
        )
        expense = self.env["hr.expense"].create(
            {
                "name": "Expense elsewhere",
                "employee_id": elsewhere.id,
                "product_id": self.product.id,
                "total_amount_currency": 10,
                "company_id": other.id,
            }
        )
        mine = expense.with_user(admin).with_context(
            allowed_company_ids=admin.company_id.ids
        )
        with (
            mute_logger("odoo.addons.base.models.ir_access"),
            self.assertRaises(AccessError),
        ):
            mine._check_approval_decider_holds("approve")
        guard = self.env.ref("hr_expense.access_hr_expense_decide_company")
        guard.active = False
        mine._check_approval_decider_holds("approve")
        guard.active = True

    def test_the_move_is_the_verb_whoever_writes_it(self):
        own = self.env["hr.expense"].create(
            {
                "name": "Own draft",
                "employee_id": self.employees["employee"].id,
                "product_id": self.product.id,
                "total_amount_currency": 11,
            }
        )
        with (
            mute_logger("odoo.addons.base.models.ir_access"),
            self.assertRaises(AccessError),
        ):
            # an employee may write their draft, not approve it by writing its
            # review state
            own.with_user(self.users["employee"]).write({"review_state": "approved"})
        expense = self._expense("employee")
        self.assertIsNone(
            expense.with_user(self.users["department_head"]).action_approve()
        )
        self.assertEqual(expense.review_state, "approved")

    def test_an_expense_nobody_approves_is_approved_by_its_submission(self):
        lone_user = new_test_user(
            self.env, login="xverb_lone", groups="base.group_user"
        )
        lone = self.env["hr.employee"].create(
            {"name": "Nobody's report", "user_id": lone_user.id}
        )
        expense = self.env["hr.expense"].create(
            {
                "name": "Approved on submission",
                "employee_id": lone.id,
                "product_id": self.product.id,
                "total_amount_currency": 10,
            }
        )
        self.assertTrue(expense._can_be_autovalidated())
        self.assertFalse(expense.with_user(lone_user).has_access("approve"))
        expense.with_user(lone_user).action_submit()
        self.assertEqual(expense.review_state, "approved")
