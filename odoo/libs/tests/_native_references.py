from odoo.libs.accel import _FORMULA_PREFIXES as FORMULA_PREFIXES
from odoo.libs.accel import (
    csv_export_python as csv_export_ref,
)
from odoo.libs.accel import (
    fast_clone_python as clone_ref,
)
from odoo.libs.accel import (
    rows_to_dicts_python as rows_to_dicts_ref,
)

__all__ = [
    "FORMULA_PREFIXES",
    "NewId",
    "clone_ref",
    "csv_export_ref",
    "rows_to_dicts_ref",
]


class NewId:
    __slots__ = ("origin",)

    def __init__(self, origin):
        self.origin = origin

    def __bool__(self):
        return False
