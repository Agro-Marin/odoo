import logging

from . import models
from . import wizard
from . import report
from . import controller

_logger = logging.getLogger(__name__)


def _pre_init_mrp(env):
    env.cr.execute(
        """ALTER TABLE "stock_move" ADD COLUMN "unit_factor" double precision NOT NULL DEFAULT 1;"""
    )
    env.cr.execute(
        """ALTER TABLE "stock_move" ADD COLUMN "manual_consumption" boolean NOT NULL DEFAULT FALSE;"""
    )


def _create_warehouse_data(env):
    warehouse_ids = env["stock.warehouse"].search([("manufacture_pull_id", "=", False)])
    warehouse_ids.write({"manufacture_to_resupply": True})


def uninstall_hook(env):
    warehouses = env["stock.warehouse"].search([])
    pbm_routes = warehouses.mapped("pbm_route_id")
    warehouses.write({"pbm_route_id": False})
    try:
        with env.cr.savepoint():
            pbm_routes.unlink()
    except Exception:
        _logger.debug(
            "Could not delete PBM routes during MRP uninstall; they are still in use.",
            exc_info=True,
        )
