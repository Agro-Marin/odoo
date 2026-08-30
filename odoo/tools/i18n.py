from typing import TYPE_CHECKING, Literal

from babel import lists

from odoo.libs.locale import py_to_js_locale
from odoo.tools.locale_utils import babel_locale_parse, get_lang

if TYPE_CHECKING:
    from collections.abc import Iterable

    import odoo.api

# Every name this module re-exports or defines, per the rule
# tests/framework/test_public_surfaces.py::TestToolsSubmoduleSurfaces pins:
# a tools shim publishes what it defines plus what it takes from another
# odoo module.  Third-party imports are incidental and stay out.
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
    # Materialise once.  `lst` is annotated Iterable, and the fallback below
    # formats it a second time -- a generator or a map object would reach that
    # retry exhausted and babel would render the empty list as "".  54 of the 93
    # languages odoo ships have at least one style whose CLDR patterns are
    # incomplete, so the retry is reached often enough to matter.
    items = [str(el) for el in lst]
    if style not in locale.list_patterns:
        style = "standard"
    try:
        return lists.format_list(items, style, locale)
    except KeyError, ValueError:
        # KeyError: the resolved pattern lacks 'start'/'middle'/'end'.
        # ValueError: babel found no replacement style for this locale at all.
        return lists.format_list(items, "standard", locale)
