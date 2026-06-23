"""Read group operations sub-package.

Modules: ``sql`` (SELECT/GROUP BY/HAVING/ORDER BY generation), ``format``
(post-processing), ``fill`` (empty-group and temporal-gap filling), ``mixin``
(``ReadGroupMixin`` entry points). ``READ_GROUP_*`` constants live in
``odoo.orm.constants``.
"""

from .mixin import ReadGroupMixin

__all__ = ["ReadGroupMixin"]
