"""Fill the newly stored analytics snapshot.

``health_score``, ``health_status`` and the five flow metrics became stored in
1.14 so they can be filtered, grouped and sorted — unstored, every one of them
raised ``Cannot convert ... to SQL because it is not stored`` on any search or
group-by, which is most of what a health indicator is for.

They are stored computes with **no** ``@api.depends`` (aggregating them
reactively would re-run a project-wide aggregation on every task edit), and the
ORM only schedules a compute for fields that declare dependencies. So the new
columns arrive NULL and nothing would fill them until ``_cron_refresh_metrics``
first fires — a whole day of projects reporting a health score of 0. Date them
once, here.
"""

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
