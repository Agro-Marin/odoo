import json

from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestOrgChartController(HttpCase):
    """JSON endpoints feeding the org chart widget."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Employee = cls.env['hr.employee']
        cls.grand_parent = Employee.create({'name': 'Org GP'})
        cls.manager = Employee.create({
            'name': 'Org Manager', 'parent_id': cls.grand_parent.id,
        })
        cls.employee = Employee.create({
            'name': 'Org Employee', 'parent_id': cls.manager.id,
        })
        cls.child = Employee.create({
            'name': 'Org Child', 'parent_id': cls.employee.id,
        })
        cls.hr_user = new_test_user(
            cls.env, login='orgchart_hr',
            groups='base.group_user,hr.group_hr_user',
        )
        cls.plain_user = new_test_user(
            cls.env, login='orgchart_plain', groups='base.group_user',
        )

    def _rpc(self, route, params):
        payload = {'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}
        res = self.url_open(
            route,
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(res.status_code, 200)
        return res.json().get('result')

    def test_redirect_model_for_hr_user(self):
        """HR officers are redirected to the full employee model."""
        self.authenticate('orgchart_hr', 'orgchart_hr')
        self.assertEqual(
            self._rpc('/hr/get_redirect_model', {}), 'hr.employee',
        )

    def test_redirect_model_for_plain_user(self):
        """Users without HR access only get the public employee model."""
        self.authenticate('orgchart_plain', 'orgchart_plain')
        self.assertEqual(
            self._rpc('/hr/get_redirect_model', {}), 'hr.employee.public',
        )

    def test_org_chart_builds_ancestors_and_children(self):
        """The chart lists managers top-down and the direct children."""
        self.authenticate('orgchart_hr', 'orgchart_hr')
        values = self._rpc('/hr/get_org_chart', {
            'employee_id': self.employee.id,
            'context': {'max_level': 5},
        })
        self.assertEqual(values['self']['id'], self.employee.id)
        self.assertEqual(
            [m['id'] for m in values['managers']],
            [self.grand_parent.id, self.manager.id],
        )
        self.assertEqual(
            [c['id'] for c in values['children']], [self.child.id],
        )
        self.assertFalse(values['managers_more'])
        self.assertEqual(values['self']['direct_sub_count'], 1)

    def test_org_chart_without_employee_is_empty(self):
        """No employee id yields an empty chart (boundary/negative)."""
        self.authenticate('orgchart_hr', 'orgchart_hr')
        values = self._rpc('/hr/get_org_chart', {
            'employee_id': False,
            'context': {'max_level': 5},
        })
        self.assertEqual(values, {'managers': [], 'children': []})

    def test_subordinates_direct(self):
        """Direct subordinates are the employee's own children."""
        self.authenticate('orgchart_hr', 'orgchart_hr')
        res = self._rpc('/hr/get_subordinates', {
            'employee_id': self.manager.id,
            'subordinates_type': 'direct',
        })
        self.assertEqual(res, [self.employee.id])

    def test_subordinates_indirect(self):
        """Indirect subordinates exclude the direct children."""
        self.authenticate('orgchart_hr', 'orgchart_hr')
        res = self._rpc('/hr/get_subordinates', {
            'employee_id': self.manager.id,
            'subordinates_type': 'indirect',
        })
        self.assertEqual(sorted(res), sorted([self.child.id]))

    def test_subordinates_default_returns_all(self):
        """Without a type the whole subtree is returned."""
        self.authenticate('orgchart_hr', 'orgchart_hr')
        res = self._rpc('/hr/get_subordinates', {
            'employee_id': self.manager.id,
        })
        self.assertEqual(
            sorted(res), sorted([self.employee.id, self.child.id]),
        )

    def test_subordinates_without_employee_is_empty(self):
        """No employee id yields an empty payload (boundary)."""
        self.authenticate('orgchart_hr', 'orgchart_hr')
        res = self._rpc('/hr/get_subordinates', {'employee_id': False})
        self.assertEqual(res, {})
