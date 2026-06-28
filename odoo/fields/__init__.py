# Exports features of the ORM to developers.
# This is a `__init__.py` file to avoid merge conflicts on `odoo/fields.py`.

from odoo.orm.primitives import COLLECTION_TYPES, NO_ACCESS, Command
from odoo.orm.domain import (
    CONDITION_OPERATORS,
    Domain,
    DomainCondition,
    OptimizationLevel,
    operator_optimization,
)
from odoo.orm.fields import (
    # Base
    Field,
    # Scalar types
    Id,
    Boolean,
    Json,
    Integer,
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
    # Relational types
    Many2one,
    One2many,
    Many2many,
    Reference,
    Many2oneReference,
    # Special types
    Properties,
    PropertiesDefinition,
)
from odoo.orm.parsing import parse_field_expr

# The curated public surface. Addon and application code imports field types and
# domains from here (and from odoo.api / odoo.models), never from odoo.orm.*
# directly, so the ORM's internal layout can evolve freely. Enforced by the
# `facade-boundary` contract in tooling/architecture/layer_check.py (ADR-0008).
__all__ = [
    "COLLECTION_TYPES",
    "CONDITION_OPERATORS",
    "NO_ACCESS",
    "Binary",
    "Boolean",
    "Char",
    "Command",
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
]
