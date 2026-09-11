from . import models
from . import reports
from . import wizards


def _create_buy_rules(env):
    warehouse_ids = env["stock.warehouse"].search([("buy_pull_id", "=", False)])
    warehouse_ids.write({"buy_to_resupply": True})
