from . import controllers
from . import models
from . import report
from . import wizard


# TODO: Apply proper fix & remove in master
def pre_init_hook(env):
    env["ir.model.data"].search(
        [("model", "like", "stock"), ("module", "=", "stock")]
    ).unlink()


def uninstall_hook(env):
    picking_type_ids = (
        env["stock.picking.type"].with_context({"active_test": False}).search([])
    )
    picking_type_ids.sequence_id.unlink()
