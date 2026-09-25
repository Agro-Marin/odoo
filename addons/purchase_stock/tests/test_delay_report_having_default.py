from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDelayReportHavingDefault(TransactionCase):
    def test_read_group_takes_the_base_having_default(self):
        report = self.env["vendor.delay.report"]
        domain = [("partner_id", "=", self.env.company.partner_id.id)]
        self.assertEqual(
            report._read_group(domain, [], ["on_time_rate:sum"], having=None),
            report._read_group(domain, [], ["on_time_rate:sum"], having=[]),
        )
