# Exports features of the ORM to developers.
# This is a `__init__.py` file to avoid merge conflicts on `odoo/models.py`.

# Constants
from odoo.orm.constants import (
    READ_GROUP_AGGREGATE,
    READ_GROUP_DISPLAY_FORMAT,
    READ_GROUP_NUMBER_GRANULARITY,
    READ_GROUP_TIME_GRANULARITY,
)
from odoo.orm.primitives import LOG_ACCESS_COLUMNS, MAGIC_COLUMNS, ValuesType
from odoo.orm.parsing import regex_order

# Model classes
from odoo.orm.models import (
    AbstractModel,
    BaseModel,
    MetaModel,
    Model,
    TransientModel,
)

# Table objects
from odoo.orm.models.table_objects import Constraint, Index, UniqueIndex

# Registration utilities
from odoo.orm.registration import (
    add_field,
    add_to_registry,
    is_model_definition,
    pop_field,
)

# Utilities
from odoo.orm.helpers import (
    check_companies_domain_parent_of,
    check_company_domain_parent_of,
    to_record_ids,
)
from odoo.orm.parsing import fix_import_export_id_paths, parse_read_group_spec
from odoo.orm.validation import check_object_name, check_pg_name, is_manual_name

# The curated public surface. Addon and application code imports model features
# from here (and from odoo.api / odoo.fields), never from odoo.orm.* directly,
# so the ORM's internal layout can evolve freely. Enforced by the
# `facade-boundary` contract in tooling/architecture/layer_check.py (ADR-0008).
__all__ = [
    "LOG_ACCESS_COLUMNS",
    "MAGIC_COLUMNS",
    "READ_GROUP_AGGREGATE",
    "READ_GROUP_DISPLAY_FORMAT",
    "READ_GROUP_NUMBER_GRANULARITY",
    "READ_GROUP_TIME_GRANULARITY",
    "AbstractModel",
    "BaseModel",
    "Constraint",
    "Index",
    "MetaModel",
    "Model",
    "TransientModel",
    "UniqueIndex",
    "ValuesType",
    "add_field",
    "add_to_registry",
    "check_companies_domain_parent_of",
    "check_company_domain_parent_of",
    "check_object_name",
    "check_pg_name",
    "fix_import_export_id_paths",
    "is_manual_name",
    "is_model_definition",
    "parse_read_group_spec",
    "pop_field",
    "regex_order",
    "to_record_ids",
]
