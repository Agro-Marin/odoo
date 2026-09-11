from . import models
from . import wizards


def uninstall_hook(env):
    teams = env["crm.team"].search([("use_opportunities", "=", False)])
    teams.write({"use_opportunities": True})
