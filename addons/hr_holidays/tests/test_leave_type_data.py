from odoo.exceptions import ValidationError
from odoo.release import version_info
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("-at_install", "post_install", "post_install_l10n")
class TestLeaveTypeData(TransactionCase):
    def test_ensure_hr_leave_type_definition(self):
        if version_info[3] != "alpha":
            return
        leave_types_xmlids = self.env["hr.leave.type"].search([])._get_external_ids()
        invalid_xmlids = []
        for xmlids in leave_types_xmlids.values():
            for xmlid in xmlids:
                module = xmlid.split(".")[0]
                if module not in [
                    "hr_holidays",
                    "__export__",
                    "__custom__",
                ] and not module.startswith("test_"):
                    invalid_xmlids.append(xmlid)
        if invalid_xmlids:
            raise ValidationError(
                "Some time off types are defined outside of module hr_holidays.\n%s"
                % "\n".join(invalid_xmlids)
            )
