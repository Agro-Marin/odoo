from . import models
from . import controllers
from . import report
from . import wizard


def uninstall_hook(env):
    # Reference sequences are named by stock.picking.type._prepare_sequence_vals;
    # the prefix is what this module owns, so match on that alone. Matching the
    # name as well used to make the hook depend on which code path last touched
    # the sequence.
    env["ir.sequence"].search([("prefix", "=like", "%/POS/")]).unlink()
