# Exports features of the ORM to developers.
# This is a `__init__.py` file to avoid merge conflicts on `odoo/api.py`.
from odoo.orm._typing import DomainType
from odoo.orm.primitives import (
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

# The curated public surface. Addon and application code imports the API from
# here (and from odoo.fields / odoo.models), never from odoo.orm.* directly, so
# the ORM's internal layout can evolve freely. Enforced by the `facade-boundary`
# contract in tooling/architecture/layer_check.py (ADR-0008).
__all__ = [
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
