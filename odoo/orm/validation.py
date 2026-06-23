"""Name and identifier validation for the ORM.

Validation for model names, PostgreSQL identifiers, and method names.
"""

import re

from odoo.exceptions import AccessError, ValidationError

# Validation patterns

regex_alphanumeric = re.compile(r"^[a-z0-9_]+$")
# First segment must start with a letter/underscore (it prefixes the generated
# SQL table name); later segments may start with a digit since they join via
# ``_`` (e.g. ``l10n_us.1099_box`` → table ``l10n_us_1099_box``). This rejects
# ``"1invalid"`` and empty segments (``"."``, ``"res..partner"``).
regex_object_name = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z0-9_]+)*$")
# Lowercase only — PostgreSQL folds unquoted identifiers to lowercase, so
# ``MyTable`` and ``mytable`` would silently collide.
regex_pg_name = re.compile(r"^[a-z_][a-z0-9_$]*$")

# Match private methods, to prevent their remote invocation
regex_private = re.compile(r"^(_.*|init)$")


# Validation functions


def check_object_name(name: str) -> bool:
    """Return whether *name* is a valid model name.

    Model names are lowercase alphanumeric with underscores and dots (e.g.
    ``res.partner``); uppercase is disallowed because PostgreSQL folds unquoted
    identifiers to lowercase and Odoo does not consistently quote them. Prefer
    :func:`raise_on_invalid_object_name` to validate with an exception.
    """
    return regex_object_name.match(name) is not None


def check_pg_name(name: str) -> None:
    """Check whether *name* is a valid PostgreSQL identifier.

    :raises ValidationError: invalid characters, or longer than 63 chars.
    """
    if not regex_pg_name.match(name):
        raise ValidationError(f"Invalid characters in table name {name!r}")
    if len(name) > 63:
        raise ValidationError(f"Table name {name!r} is too long")


def check_method_name(name: str) -> None:
    """Check whether *name* is safe for remote invocation.

    Private methods (prefixed with ``_``) and ``init`` cannot be called via RPC.

    :raises AccessError: if *name* matches the private-method pattern.
    """
    if regex_private.match(name):
        raise AccessError(
            f"Private methods (such as {name!r}) cannot be called remotely."
        )


def raise_on_invalid_object_name(name: str) -> None:
    """Raise :class:`ValueError` if *name* is not a valid model name."""
    if not check_object_name(name):
        msg = f"The _name attribute {name!r} is not valid."
        raise ValueError(msg)
