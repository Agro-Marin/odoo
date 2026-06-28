"""Relational field types, split by kind for readability.

The public surface (``Many2one``, ``One2many``, ``Many2many`` and the shared
bases) is unchanged: import from ``odoo.orm.fields.relational`` as before.
"""

from ._base import PrefetchX2many, _Relational, _RelationalMulti
from .many2many import Many2many
from .many2one import Many2one, PrefetchMany2one
from .one2many import One2many

__all__ = [
    "Many2many",
    "Many2one",
    "One2many",
    "PrefetchMany2one",
    "PrefetchX2many",
    "_Relational",
    "_RelationalMulti",
]
