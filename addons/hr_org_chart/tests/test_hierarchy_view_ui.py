from odoo.tests import HttpCase, tagged

from odoo.addons.hr.tests.common import TestHrCommon


@tagged("-at_install", "post_install")
class TestHierarchyViewUi(TestHrCommon, HttpCase):
    """Drive the hierarchy view against a real server.

    Its HOOT suite answers every read from a mock, so a mock that drifts from
    `hierarchy_read` is invisible there. This is the only test in the tree that
    makes the view talk to the ORM.
    """

    def test_hierarchy_view_unfolds_and_folds(self):
        Employee = self.env["hr.employee"].with_user(self.res_users_hr_officer)
        root = Employee.create({"name": "Hierarchy Root"})
        report_a, _report_b = Employee.create(
            [
                {"name": "Hierarchy Report A", "parent_id": root.id},
                {"name": "Hierarchy Report B", "parent_id": root.id},
            ]
        )
        Employee.create({"name": "Hierarchy Grandchild", "parent_id": report_a.id})

        self.start_tour("/odoo/employees", "hierarchy_view_tour", login="admin")
