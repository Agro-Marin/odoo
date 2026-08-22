from . import models
from . import controllers
from . import report
from . import wizard


def uninstall_hook(env):
    env["ir.sequence"].search(
        [("name", "ilike", "%Picking POS%"), ("prefix", "ilike", "%/POS/%")]
    ).unlink()
