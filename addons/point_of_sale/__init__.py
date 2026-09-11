from . import models
from . import controllers
from . import reports
from . import wizards


def uninstall_hook(env):
    env["ir.sequence"].search([("prefix", "=like", "%/POS/")]).unlink()
