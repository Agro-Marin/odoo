from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref(
        "automation.ir_cron_data_automation_resume", raise_if_not_found=False
    )
    if not cron:
        return
    cron.write({"active": True, "repeat_interval": 1, "repeat_unit": "hour"})
    cron._trigger()
