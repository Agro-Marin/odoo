"""Name and identifier validation for the ORM.

Validation for model names, PostgreSQL identifiers, and method names.
"""

import re

from odoo.exceptions import AccessError, ValidationError

# Validation patterns

# All three anchor with \Z, not $: in Python, $ also matches before a single
# trailing newline, so "name\n" would validate — the same trap
# check_method_name below defends against explicitly.
regex_alphanumeric = re.compile(r"^[a-z0-9_]+\Z")
# First segment must start with a letter/underscore (it prefixes the generated
# SQL table name); later segments may start with a digit since they join via
# ``_`` (e.g. ``l10n_us.1099_box`` → table ``l10n_us_1099_box``). This rejects
# ``"1invalid"`` and empty segments (``"."``, ``"res..partner"``).
regex_object_name = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z0-9_]+)*\Z")
# Lowercase only — PostgreSQL folds unquoted identifiers to lowercase, so
# ``MyTable`` and ``mytable`` would silently collide.
regex_pg_name = re.compile(r"^[a-z_][a-z0-9_$]*\Z")

# Manual (custom / Studio) fields and models are created at runtime rather than
# declared in Python, and are conventionally prefixed with ``x_`` so the ORM can
# tell them apart from code-defined ones.
MANUAL_NAME_PREFIX = "x_"


# Validation functions


def is_manual_name(name: str) -> bool:
    """Return whether *name* denotes a manual (custom / Studio) field or model.

    Single source of truth for the ``x_`` convention, shared by model setup
    (``orm.registration``) and the ``ir.model`` / ``ir.model.fields`` API.
    """
    return name.startswith(MANUAL_NAME_PREFIX)


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
    # Use startswith/equality rather than a ``^(_.*|init)$`` regex: ``.`` does not
    # match a newline and ``$`` matches before a trailing one, so a regex would
    # let a name like ``"_secret\nx"`` slip through (defense in depth -- such a
    # name cannot resolve to a real method, but the check must reject it).
    if name == "init" or name.startswith("_"):
        raise AccessError(
            f"Private methods (such as {name!r}) cannot be called remotely."
        )


def raise_on_invalid_object_name(name: str) -> None:
    """Raise :class:`ValueError` if *name* is not a valid model name."""
    if not check_object_name(name):
        msg = f"The _name attribute {name!r} is not valid."
        raise ValueError(msg)
