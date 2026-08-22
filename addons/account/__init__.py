def _set_fiscal_country(env):
    env["res.company"].search([])._compute_account_fiscal_country_id()


def _account_post_init(env):
    _set_fiscal_country(env)


from . import controllers
from . import models
from . import demo
from . import wizard
from . import report
from . import tools
