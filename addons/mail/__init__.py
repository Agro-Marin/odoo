import encodings
import typing

from . import models
from . import tools
from . import wizard
from . import controllers

encodings.aliases.aliases["cp_850"] = "cp850"

if typing.TYPE_CHECKING:
    from odoo.api import Environment


def _mail_post_init(env: Environment) -> None:
    env["mail.alias.domain"]._migrate_icp_to_domain()
