import re

from odoo.exceptions import ValidationError

regex_alphanumeric = re.compile(r"^[a-z0-9_]+\Z")
regex_object_name = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z0-9_]+)*\Z")
regex_pg_name = re.compile(r"^[a-z_][a-z0-9_$]*\Z")

MANUAL_NAME_PREFIX = "x_"

#: PostgreSQL's identifier limit (``NAMEDATALEN - 1``).
MAX_PG_NAME_LENGTH = 63


def is_manual_name(name: str) -> bool:
    return name.startswith(MANUAL_NAME_PREFIX)


def is_valid_object_name(name: str) -> bool:
    return regex_object_name.match(name) is not None


def check_object_name(name: str) -> None:
    if not is_valid_object_name(name):
        raise ValidationError(f"The _name attribute {name!r} is not valid.")


def check_pg_name(name: str) -> None:
    if not regex_pg_name.match(name):
        raise ValidationError(f"Invalid characters in table name {name!r}")
    if len(name) > MAX_PG_NAME_LENGTH:
        raise ValidationError(f"Table name {name!r} is too long")
