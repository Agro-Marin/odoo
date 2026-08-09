"""Name-checking helpers.

Two protocols, told apart by their prefix rather than by memory:

``is_*``     answers a question and returns ``bool``. Never raises.
``check_*``  asserts a requirement, returns ``None``, and raises
             :class:`~odoo.exceptions.ValidationError` when it does not hold.

Until 2026-08-09 this module used ``check_`` for both, so ``check_object_name``
returned a bool while ``check_pg_name`` raised, and ``if check_pg_name(x):``
read as a validation and was in fact always false -- silently accepting every
invalid name. It also raised three different exception types for one kind of
failure (``ValidationError``, ``AccessError``, ``ValueError``); they are one
now.

Normalising the names is also what made the redundancy visible:
``raise_on_invalid_object_name`` was ``check_object_name`` plus a raise, which
is exactly what ``check_object_name`` means under the rule above, so the two
collapsed into one pair.
"""

import re

from odoo.exceptions import ValidationError

regex_alphanumeric = re.compile(r"^[a-z0-9_]+\Z")
regex_object_name = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z0-9_]+)*\Z")
regex_pg_name = re.compile(r"^[a-z_][a-z0-9_$]*\Z")

MANUAL_NAME_PREFIX = "x_"

#: PostgreSQL's identifier limit (``NAMEDATALEN - 1``).
MAX_PG_NAME_LENGTH = 63


def is_manual_name(name: str) -> bool:
    """Whether *name* belongs to a field or model created from the UI."""
    return name.startswith(MANUAL_NAME_PREFIX)


def is_valid_object_name(name: str) -> bool:
    """Whether *name* is a well-formed model name (``res.partner``)."""
    return regex_object_name.match(name) is not None


def check_object_name(name: str) -> None:
    """Raise unless *name* is a well-formed model name."""
    if not is_valid_object_name(name):
        raise ValidationError(f"The _name attribute {name!r} is not valid.")


def check_pg_name(name: str) -> None:
    """Raise unless *name* is usable as a PostgreSQL identifier."""
    if not regex_pg_name.match(name):
        raise ValidationError(f"Invalid characters in table name {name!r}")
    if len(name) > MAX_PG_NAME_LENGTH:
        raise ValidationError(f"Table name {name!r} is too long")
