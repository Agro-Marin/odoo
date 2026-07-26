"""
Language and locale utilities for Odoo.
"""

import csv
import functools
import logging
import typing
from operator import itemgetter

import babel

from .files import file_open

if typing.TYPE_CHECKING:
    from odoo.api import Environment

    from odoo.addons.base.models.res_lang import LangData
else:
    Environment = typing.Any
    LangData = typing.Any

_logger = logging.getLogger(__name__)


def get_iso_codes(lang: str) -> str:
    if lang.find("_") != -1:
        lang_items = lang.split("_")
        if lang_items[0] == lang_items[1].lower():
            lang = lang_items[0]
    return lang


@functools.cache
def _scan_languages() -> tuple[tuple[str, str], ...]:
    """Parse ``base/data/res.lang.csv`` once per process.

    The file is shipped data resolved through the addons path, which is fixed
    after startup, so the result is a constant of the installation.  It is worth
    memoizing because ``scan_languages`` backs the ``list_lang`` RPC verb, which
    is reachable with no authentication and no master password.

    Deliberately lets a read failure PROPAGATE instead of returning the English
    fallback itself: ``functools.cache`` stores return values, not exceptions, so
    handling the error in here would pin a transient failure — a half-deployed
    addons directory, a momentary EIO — as this process's permanent answer.
    :func:`scan_languages` owns the fallback, and the next call retries the read.
    """
    with file_open("base/data/res.lang.csv") as csvfile:
        reader = csv.reader(csvfile, delimiter=",", quotechar='"')
        fields = next(reader)
        code_index = fields.index("code")
        name_index = fields.index("name")
        result = [(row[code_index], row[name_index]) for row in reader]

    return tuple(sorted(result or [("en_US", "English")], key=itemgetter(1)))


def scan_languages() -> list[tuple[str, str]]:
    """Return all languages supported by Odoo for translation.

    :returns: a list of (lang_code, lang_name) pairs

    A fresh list over the memoized :func:`_scan_languages` parse, so callers keep
    the mutable sequence the signature promises without sharing the cached value.
    """
    try:
        return list(_scan_languages())
    except Exception:
        _logger.error("Could not read res.lang.csv")
        return [("en_US", "English")]


def get_lang(env: Environment, lang_code: str | None = None) -> LangData:
    """Return the first installed lang, checking lang_code, then the context, then the company.

    Defaults to English, or the first installed lang, if none of those match.

    :param env: environment used to look up installed languages
    :param str lang_code: the locale (e.g. en_US)
    :return LangData: the first lang found that is installed on the system.
    """
    langs = [code for code, _ in env["res.lang"].get_installed()]
    lang = "en_US" if "en_US" in langs else langs[0]
    if lang_code and lang_code in langs:
        lang = lang_code
    elif (context_lang := env.context.get("lang")) in langs:
        lang = context_lang
    elif (
        company_lang := env.user.with_context(lang="en_US").company_id.partner_id.lang
    ) in langs:
        lang = company_lang
    return env["res.lang"]._get_data(code=lang)


@functools.cache
def babel_locale_parse(lang_code: str | None) -> babel.Locale:
    if lang_code:
        try:
            return babel.Locale.parse(lang_code)
        except Exception:
            pass
    try:
        return babel.Locale.default()
    except Exception:
        return babel.Locale.parse("en_US")
