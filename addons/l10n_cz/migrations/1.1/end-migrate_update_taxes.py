from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env["res.company"].search(
        [("chart_template", "=", "cz")], order="parent_path"
    ):
        env["account.chart.template"].try_loading("cz", company, force_create=False)
