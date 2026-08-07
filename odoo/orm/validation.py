import re

from odoo.exceptions import AccessError, ValidationError

regex_alphanumeric = re.compile(r"^[a-z0-9_]+\Z")
regex_object_name = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z0-9_]+)*\Z")
regex_pg_name = re.compile(r"^[a-z_][a-z0-9_$]*\Z")

MANUAL_NAME_PREFIX = "x_"


def is_manual_name(name: str) -> bool:
    return name.startswith(MANUAL_NAME_PREFIX)


def check_object_name(name: str) -> bool:
    return regex_object_name.match(name) is not None


def check_pg_name(name: str) -> None:
    if not regex_pg_name.match(name):
        raise ValidationError(f"Invalid characters in table name {name!r}")
    if len(name) > 63:
        raise ValidationError(f"Table name {name!r} is too long")


def check_method_name(name: str) -> None:
    if name == "init" or name.startswith("_"):
        raise AccessError(
            f"Private methods (such as {name!r}) cannot be called remotely."
        )


def raise_on_invalid_object_name(name: str) -> None:
    if not check_object_name(name):
        msg = f"The _name attribute {name!r} is not valid."
        raise ValueError(msg)
