import logging
import os

from ...primitives import LOG_ACCESS_COLUMNS, SUPERUSER_ID

COPY_THRESHOLD = int(os.environ.get("ODOO_COPY_THRESHOLD", "10"))
COPY_DISABLED = os.environ.get("ODOO_DISABLE_COPY", "").lower() in (
    "1",
    "true",
    "yes",
)

_BAD_NAMES = frozenset({"id", "parent_path"})
_BAD_NAMES_LOG = _BAD_NAMES | frozenset(LOG_ACCESS_COLUMNS)


def bad_field_names(model) -> frozenset:
    if model._log_access and not (
        model.env.uid == SUPERUSER_ID and not model.pool.ready
    ):
        return _BAD_NAMES_LOG
    return _BAD_NAMES


_unlink = logging.getLogger("odoo.models.unlink")
_orm_crud = logging.getLogger("odoo.orm.crud")
