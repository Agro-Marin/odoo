import re

from odoo.exceptions import ValidationError

regex_alphanumeric = re.compile(r"^[a-z0-9_]+\Z")
regex_object_name = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z0-9_]+)*\Z")
# Lowercase only, deliberately: PostgreSQL folds unquoted identifiers, so
# `MyTable` and `mytable` would silently collide. `re.IGNORECASE` was applied
# here until 0a5b1f96b81 and contradicted that policy; the survey that made
# dropping it safe covered model `_table` values across core, enterprise and
# agromarin and found no uppercase one. **That survey did not cover field
# names**, which reach this through `ir.model.fields._check_name`, and
# `web_studio`'s view-editor tests still create fields with mixed-case names.
regex_pg_name = re.compile(r"^[a-z_][a-z0-9_$]*\Z")

MANUAL_NAME_PREFIX = "x_"

MAX_PG_NAME_LENGTH = 63


def is_manual_name(name: str) -> bool:
    return name.startswith(MANUAL_NAME_PREFIX)


def is_valid_object_name(name: str) -> bool:
    return regex_object_name.match(name) is not None


def check_object_name(name: str) -> None:
    if not is_valid_object_name(name):
        raise ValidationError(  # noqa: E8505  diagnostic, no caller shows it
            f"The _name attribute {name!r} is not valid."
        )


def check_pg_name(name: str) -> None:
    if not regex_pg_name.match(name):
        raise ValidationError(  # noqa: E8505  ir.model.fields translates its own
            f"Invalid characters in table name {name!r}"
        )
    if len(name) > MAX_PG_NAME_LENGTH:
        raise ValidationError(  # noqa: E8505  ir.model.fields translates its own
            f"Table name {name!r} is too long"
        )
