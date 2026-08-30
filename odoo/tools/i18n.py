from typing import TYPE_CHECKING, Literal

from babel import lists

from odoo.libs.locale import py_to_js_locale
from odoo.tools.locale_utils import babel_locale_parse, get_lang

if TYPE_CHECKING:
    from collections.abc import Iterable

    import odoo.api

__all__ = [
    "babel_locale_parse",
    "format_list",
    "get_lang",
    "py_to_js_locale",
]


def format_list(
    env: odoo.api.Environment | None,
    lst: Iterable,
    style: Literal[
        "standard",
        "standard-short",
        "or",
        "or-short",
        "unit",
        "unit-short",
        "unit-narrow",
    ] = "standard",
    lang_code: str | None = None,
) -> str:
    locale = babel_locale_parse(
        lang_code or (get_lang(env).code if env is not None else "en_US")
    )
    items = [str(el) for el in lst]
    if style not in locale.list_patterns:
        style = "standard"
    try:
        return lists.format_list(items, style, locale)
    except KeyError, ValueError:
        return lists.format_list(items, "standard", locale)
