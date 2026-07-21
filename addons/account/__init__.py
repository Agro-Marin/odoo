def _set_fiscal_country(env):
    """Set the fiscal country on existing companies when installing the module."""
    # The field is an editable computed field: the ORM does not compute it on
    # preexisting records at install time, so trigger the compute by hand.
    env["res.company"].search([])._compute_account_fiscal_country_id()


def _account_post_init(env):
    _set_fiscal_country(env)


# imported here to avoid dependency cycle issues
# pylint: disable=wrong-import-position
from . import controllers
from . import models
from . import demo
from . import wizard
from . import report
from . import tools
