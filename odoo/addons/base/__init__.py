from . import models
from . import reports
from . import wizards


def post_init(env):
    env["ir.config_parameter"].init(force=True)
