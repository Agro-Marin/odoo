from . import models
from . import report
from . import wizard

from odoo import Command


def _enable_tracking_numbers(env):
    group_production_lot = env.ref("stock.group_production_lot")
    groups = env.ref("base.group_user") + env.ref("base.group_portal")
    groups.write({"implied_ids": [Command.link(group_production_lot.id)]})
