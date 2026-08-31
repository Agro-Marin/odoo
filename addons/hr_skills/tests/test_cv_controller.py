from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.hr_skills.controllers.main import EMPLOYEE_IDS_RE


@tagged("post_install", "-at_install")
class TestEmployeeIdsPattern(TransactionCase):
    def test_a_plain_id_list_is_accepted(self):
        for accepted in ("1", "1,2", "10,20,30"):
            self.assertTrue(EMPLOYEE_IDS_RE.match(accepted), accepted)

    def test_anything_int_would_choke_on_is_rejected(self):
        for rejected in ("1|2", "1,,2", "", ",", "1,", "1 2", "-1", "1;2", "a"):
            self.assertFalse(EMPLOYEE_IDS_RE.match(rejected), repr(rejected))

    def test_a_repeated_query_parameter_is_not_a_string(self):
        with self.assertRaises(TypeError):
            EMPLOYEE_IDS_RE.match(["1", "2"])

    def test_the_rejected_shapes_are_the_ones_that_used_to_reach_int(self):
        for crashing in ("1|2", "1,,2", "", ",", "1,", "1 2", "1;2", "a"):
            with self.assertRaises(ValueError, msg=crashing):
                [int(part) for part in crashing.split(",")]
