import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env["project.project"].with_context(active_test=False).search([])
    if not projects:
        return
    for index in range(0, len(projects), BATCH_SIZE):
        batch = projects[index : index + BATCH_SIZE]
        batch._refresh_metrics()
        cr.commit()
    _logger.info(
        "project: dated the analytics snapshot of %s project(s)", len(projects)
    )
