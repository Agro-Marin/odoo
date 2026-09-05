import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Employee = env["hr.employee"]
    result = Employee.converge_party_rows()
    _logger.info(
        "party convergence: %s employees merged onto their user's partner, "
        "%s left for a human",
        len(result["merged"]),
        len(result["left_for_a_human"]),
    )
    if result["left_for_a_human"]:
        _logger.warning(
            "employees whose work contact and user partner disagree, not merged: %s\n%s",
            result["left_for_a_human"],
            Employee.print_party_convergence(),
        )
