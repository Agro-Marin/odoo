from . import models


def _check_existing_work_entries(env):
    env["hr.work.entry"].search([])._check_if_error()
