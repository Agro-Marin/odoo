from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env["res.company"].search(
        [("chart_template", "=", "cl")], order="parent_path"
    ):
        env["account.chart.template"].try_loading("cl", company, force_create=False)
