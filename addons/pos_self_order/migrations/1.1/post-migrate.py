import logging
import typing

from odoo import api

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)


def migrate(cr: "Cursor", version: str | None) -> None:
    if not version:
        return
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    _unbind_qr_codes_report(env)


def _unbind_qr_codes_report(env: api.Environment) -> None:
    """Take the QR-codes sheet out of every register's Print menu.

    Dropping the two fields from the data file is not enough: loading a
    record only writes the fields it declares, so a database installed
    before this keeps the binding it was given.
    """
    report = env.ref(
        "pos_self_order.report_self_order_qr_codes_page", raise_if_not_found=False
    )
    if not report or not report.binding_model_id:
        return
    _logger.info(
        "pos_self_order 1.1: unbinding %s from the %s print menu -- the sheet is "
        "built from the self-ordering settings payload and renders empty from "
        "anywhere else",
        report.name,
        report.binding_model_id.model,
    )
    report.binding_model_id = False
