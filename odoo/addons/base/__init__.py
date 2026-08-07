from . import models
from . import report
from . import wizard


def post_init(env):
    env["ir.config_parameter"].init(force=True)
