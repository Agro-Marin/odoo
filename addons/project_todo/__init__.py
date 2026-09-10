from . import models
from . import wizard


def _todo_post_init(env):
    env["res.users"].search([("share", "=", False)])._create_onboarding_todo()
