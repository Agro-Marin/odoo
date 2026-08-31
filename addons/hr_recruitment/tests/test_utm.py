from odoo.exceptions import UserError
from odoo.tests.common import tagged, users

from odoo.addons.utm.tests.common import TestUTMCommon


@tagged("post_install", "-at_install", "utm_consistency")
class TestUTMConsistencyHrRecruitment(TestUTMCommon):
    @users("__system__")
    def test_utm_consistency(self):
        hr_recruitment_source = self.env["hr.recruitment.source"].create(
            {"name": "Recruitment Source"}
        )
        utm_source = hr_recruitment_source.source_id

        with self.assertRaises(UserError):
            utm_source.unlink()

        with self.assertRaises(UserError):
            self.env.ref("hr_recruitment.utm_campaign_job").unlink()
