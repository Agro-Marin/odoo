from typing import TYPE_CHECKING, Literal

from babel import lists

from odoo.libs.locale import py_to_js_locale
from odoo.tools.locale_utils import babel_locale_parse, get_lang

if TYPE_CHECKING:
    from collections.abc import Iterable

    import odoo.api


def format_list(
    env: odoo.api.Environment,
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
    locale = babel_locale_parse(lang_code or get_lang(env).code)
    if style not in locale.list_patterns:
        style = "standard"
    try:
        return lists.format_list([str(el) for el in lst], style, locale)
    except KeyError:
        return lists.format_list([str(el) for el in lst], "standard", locale)
