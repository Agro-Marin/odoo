"""One of the three public façades: ``odoo.api``, ``odoo.fields``, ``odoo.models``.

Nothing is implemented here. Every name is re-exported from ``odoo/orm/``: the
field types from ``orm.fields``, the domain machinery from ``orm.domain``,
``Command``/``NO_ACCESS``/``COLLECTION_TYPES`` from ``orm.primitives`` and
``parse_field_expr`` from ``orm.parsing``. The indirection is the point -- it
leaves the ORM free to move behind a surface addon code can rely on.

Addon code imports model features from this module and never from ``odoo.orm.*``.
That is the ``facade-boundary`` contract in
``tooling/architecture/layer_check.py`` (ADR-0008);
``doc/architecture/module.md`` is the prose companion.

Adding a field type to ``odoo/orm/fields`` does not make it public. It becomes
public once it is imported here *and* named in ``__all__`` -- both, because a
caller reads the first and static tooling reads the second.
"""

from odoo.orm.primitives import COLLECTION_TYPES, NO_ACCESS, Command
from odoo.orm.domain import (
    ACCEPTED_CONDITION_OPERATORS,
    CONDITION_OPERATORS,
    register_condition_operators,
    NEGATIVE_CONDITION_OPERATORS,
    Domain,
    DomainCondition,
    OptimizationLevel,
    operator_optimization,
)
from odoo.orm.fields import (
    Field,
    Id,
    Boolean,
    Json,
    Integer,
    Count,
    Float,
    Monetary,
    Char,
    Text,
    Html,
    Selection,
    Date,
    Datetime,
    Binary,
    Image,
    Many2one,
    One2many,
    Many2many,
    Reference,
    Many2oneReference,
    Properties,
    PropertiesDefinition,
)
from odoo.orm.parsing import parse_field_expr

__all__ = [
    "ACCEPTED_CONDITION_OPERATORS",
    "COLLECTION_TYPES",
    "CONDITION_OPERATORS",
    "NEGATIVE_CONDITION_OPERATORS",
    "NO_ACCESS",
    "Binary",
    "Boolean",
    "Char",
    "Command",
    "Count",
    "Date",
    "Datetime",
    "Domain",
    "DomainCondition",
    "Field",
    "Float",
    "Html",
    "Id",
    "Image",
    "Integer",
    "Json",
    "Many2many",
    "Many2one",
    "Many2oneReference",
    "Monetary",
    "One2many",
    "OptimizationLevel",
    "Properties",
    "PropertiesDefinition",
    "Reference",
    "Selection",
    "Text",
    "operator_optimization",
    "parse_field_expr",
    "register_condition_operators",
]
