from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class HrDepartment(models.Model):
    _name = "hr.department"
    _description = "Department"
    _inherit = ["mixin.mail.thread", "mixin.mail.activity"]
    _order = "name"
    _rec_name = "complete_name"
    _parent_store = True

    name = fields.Char("Department Name", required=True, translate=True)
    complete_name = fields.Char(
        "Complete Name",
        compute="_compute_complete_name",
        recursive=True,
        store=True,
    )
    active = fields.Boolean("Active", default=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        compute="_compute_company_id",
        store=True,
        recursive=True,
        index=True,
        readonly=False,
        tracking=True,
        default=lambda self: self.env.company,
    )
    parent_id = fields.Many2one(
        "hr.department", string="Parent Department", index=True, check_company=True
    )
    child_ids = fields.One2many(
        "hr.department", "parent_id", string="Child Departments"
    )
    manager_id = fields.Many2one(
        "hr.employee",
        string="Manager",
        tracking=True,
        domain="['|', ('company_id', '=', False), ('company_id', 'in', allowed_company_ids)]",
    )
    member_ids = fields.One2many(
        "hr.employee", "department_id", string="Members", readonly=True
    )
    # Search-only: no ``compute``, so READING this field raises. It exists to
    # carry ``_search_has_read_access`` into an action domain (hr_department_views).
    has_read_access = fields.Boolean(
        search="_search_has_read_access", store=False, export_string_translation=False
    )
    total_employee = fields.Integer(
        compute="_compute_total_employee",
        string="Total Employee",
        export_string_translation=False,
    )
    jobs_ids = fields.One2many("hr.job", "department_id", string="Jobs")
    plan_ids = fields.One2many("mail.activity.plan", "department_id")
    plans_count = fields.Integer(compute="_compute_plans_count")
    note = fields.Text("Note")
    color = fields.Integer("Color Index")
    parent_path = fields.Char(index=True)
    master_department_id = fields.Many2one(
        "hr.department",
        "Master Department",
        compute="_compute_master_department_id",
        store=True,
    )

    @api.depends_context("hierarchical_naming")
    def _compute_display_name(self):
        if self.env.context.get("hierarchical_naming", True):
            return super()._compute_display_name()
        for record in self:
            record.display_name = record.name
        return None

    def _search_has_read_access(self, operator, value):
        if operator != "in":
            return NotImplemented
        if self.env["hr.employee"].has_access("read"):
            return [(1, "=", 1)]
        departments_ids = (
            self.env["hr.department"]
            .sudo()
            .search([("manager_id", "in", self.env.user.employee_ids.ids)])
            .ids
        )
        return [("id", "child_of", departments_ids)]

    @api.model
    def name_create(self, name):
        record = self.create({"name": name})
        return record.id, record.display_name

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for department in self:
            if department.parent_id:
                department.complete_name = "%s / %s" % (
                    department.parent_id.complete_name,
                    department.name,
                )
            else:
                department.complete_name = department.name

    @api.depends("parent_path")
    def _compute_master_department_id(self):
        for dept in self:
            dept.master_department_id = (
                int(dept.parent_path.split("/")[0]) if dept.parent_path else dept.id
            )

    @api.depends_context("allowed_company_ids")
    @api.depends("member_ids")
    def _compute_total_employee(self):
        emp_data = (
            self.env["hr.employee"]
            .sudo()
            ._read_group(
                [
                    ("department_id", "in", self.ids),
                    ("company_id", "in", self.env.companies.ids),
                ],
                ["department_id"],
                ["__count"],
            )
        )
        result = {department.id: count for department, count in emp_data}
        for department in self:
            department.total_employee = result.get(department.id, 0)

    @api.depends_context("allowed_company_ids")
    @api.depends("plan_ids")
    def _compute_plans_count(self):
        plans_data = self.env["mail.activity.plan"]._read_group(
            domain=[
                "|",
                ("department_id", "=", False),
                ("department_id", "in", self.ids),
                ("company_id", "in", self.env.companies.ids + [False]),
            ],
            groupby=["department_id"],
            aggregates=["__count"],
        )
        plans_count = {department.id: count for department, count in plans_data}
        for department in self:
            department.plans_count = plans_count.get(
                department.id, 0
            ) + plans_count.get(False, 0)

    @api.constrains("parent_id")
    def _check_parent_id(self):
        if self._has_cycle():
            raise ValidationError(
                self.env._("You cannot create recursive departments.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        return super(
            HrDepartment, self.with_context(mail_create_nosubscribe=True)
        ).create(vals_list)

    @api.depends("parent_id", "parent_id.company_id")
    def _compute_company_id(self):
        for dept in self:
            dept.company_id = dept.parent_id.company_id or dept.company_id

    def write(self, vals):
        """If updating manager of a department, we need to update all the employees
        of department hierarchy, and subscribe the new manager.
        """
        if "manager_id" in vals:
            manager_id = vals.get("manager_id")
            # set the employees's parent to the new manager
            self._update_employee_manager(manager_id)
        return super().write(vals)

    def _update_employee_manager(self, manager_id):
        department_employees = self.env["hr.employee"].search(
            [
                ("id", "!=", manager_id),
                ("department_id", "in", self.ids),
            ]
        )
        # One pass over the employees, looking each one's own department up --
        # instead of re-``filtered()``ing the whole set once per department.
        # Called BEFORE super().write, so ``manager_id`` here is still the OLD
        # manager: that is what identifies the employees who were reporting to it.
        manager_per_department = {
            department: department.manager_id for department in self
        }
        employees = department_employees.filtered(
            lambda employee: (
                employee.parent_id == manager_per_department.get(employee.department_id)
            )
        )
        employees.write({"parent_id": manager_id})

    def get_formview_action(self, access_uid=None):
        res = super().get_formview_action(access_uid=access_uid)
        if not self.env.user.has_group("hr.group_hr_user") and self.env.context.get(
            "open_employees_kanban", False
        ):
            res.update(
                {
                    "name": self.name,
                    "res_model": "hr.employee.public",
                    "view_mode": "kanban",
                    "views": [(False, "kanban"), (False, "form")],
                    "context": {"searchpanel_default_department_id": self.id},
                    "res_id": False,
                }
            )
        return res

    def action_plan_from_department(self):
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "hr.mail_activity_plan_action"
        )
        action["context"] = dict(
            self.env["ir.actions.actions"]._eval_action_context(action.get("context")),
            default_department_id=self.id,
        )
        domain = [
            "|",
            ("department_id", "=", False),
            ("department_id", "in", self.ids),
        ]
        if "domain" in action:
            # The stored domain is an EXPRESSION, not a literal: this one names
            # ``allowed_company_ids``, which is why ``ast.literal_eval`` raises on
            # it and why this used to substitute the name into the string before
            # literal-eval'ing the result -- a substitution that only ever works
            # for the one name the caller thought of.
            # ``_eval_action_domain`` is the twin of the ``_eval_action_context``
            # this method already uses.
            action["domain"] = Domain.AND(
                [
                    self.env["ir.actions.actions"]._eval_action_domain(
                        action["domain"],
                        allowed_company_ids=self.env.context.get(
                            "allowed_company_ids", []
                        ),
                    ),
                    domain,
                ]
            )
        else:
            action["domain"] = domain
        if self.plans_count == 0:
            action["views"] = [(False, "form")]
        return action

    def action_employee_from_department(self):
        if self.env["hr.employee"].has_access("read"):
            res_model = "hr.employee"
            search_view_id = self.env.ref("hr.view_employee_filter").id
        else:
            res_model = "hr.employee.public"
            search_view_id = self.env.ref("hr.hr_employee_public_view_search").id
        return {
            "name": self.env._("Employees"),
            "type": "ir.actions.act_window",
            "res_model": res_model,
            "view_mode": "list,kanban,form",
            "views": [(False, "list"), (False, "kanban"), (False, "form")],
            "search_view_id": [search_view_id, "search"],
            "context": {
                "searchpanel_default_department_id": self.id,
                "default_department_id": self.id,
                "search_default_group_department": 1,
                "search_default_department_id": self.id,
                "expand": 1,
            },
        }

    def get_children_department_ids(self):
        return self.env["hr.department"].search([("id", "child_of", self.ids)])

    def action_open_view_child_departments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "hr.department",
            "views": [[False, "kanban"], [False, "list"], [False, "form"]],
            "domain": [["id", "in", self.get_children_department_ids().ids]],
            "name": "Child departments",
        }

    def get_department_hierarchy(self):
        if not self:
            return {}
        self.ensure_one()

        return {
            "parent": {
                "id": self.parent_id.id,
                "name": self.parent_id.name,
                "employees": self.parent_id.total_employee,
            }
            if self.parent_id
            else False,
            "self": {
                "id": self.id,
                "name": self.name,
                "employees": self.total_employee,
            },
            "children": [
                {"id": child.id, "name": child.name, "employees": child.total_employee}
                for child in self.child_ids
            ],
        }
