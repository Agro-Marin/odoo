from . import models
from . import tools
from . import wizard
from . import controllers


def _mail_post_init(env):
    env["mail.alias.domain"]._migrate_icp_to_domain()
