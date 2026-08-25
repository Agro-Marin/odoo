"""One of the three public façades: ``odoo.api``, ``odoo.fields``, ``odoo.models``.

Nothing is implemented here. Every name is re-exported from ``odoo/orm/``: the
model/field decorators (``@api.depends``, ``@api.constrains``, ``@api.model``,
...) from ``orm.decorators``, ``Environment`` from ``orm.runtime``,
``SUPERUSER_ID``/``MODULE_UNINSTALL_FLAG`` and the recordset type aliases
(``ContextType``, ``IdType``, ``NewId``, ``Self``, ``ValuesType``) from
``orm.primitives``, and ``DomainType`` from ``orm._typing``. The indirection is
the point -- it leaves the ORM free to move behind a surface addon code can
rely on.

Addon code imports environment and decorator features from this module and
never from ``odoo.orm.*``. That is the ``facade-boundary`` contract in
``tooling/architecture/layer_check.py`` (ADR-0008);
``doc/architecture/module.md`` is the prose companion.

Adding a decorator or type to ``odoo/orm`` does not make it public. It becomes
public once it is imported here *and* named in ``__all__`` -- both, because a
caller reads the first and static tooling reads the second.
"""

from odoo.orm._typing import DomainType
from odoo.orm.primitives import (
    MODULE_UNINSTALL_FLAG,
    SUPERUSER_ID,
    ContextType,
    IdType,
    NewId,
    Self,
    ValuesType,
)
from odoo.orm.decorators import (
    autovacuum,
    constrains,
    depends,
    depends_context,
    deprecated,
    job,
    model,
    model_create_multi,
    onchange,
    ondelete,
    private,
    readonly,
)
from odoo.orm.runtime import Environment

__all__ = [
    "MODULE_UNINSTALL_FLAG",
    "SUPERUSER_ID",
    "ContextType",
    "DomainType",
    "Environment",
    "IdType",
    "NewId",
    "Self",
    "ValuesType",
    "autovacuum",
    "constrains",
    "depends",
    "depends_context",
    "deprecated",
    "job",
    "model",
    "model_create_multi",
    "onchange",
    "ondelete",
    "private",
    "readonly",
]
