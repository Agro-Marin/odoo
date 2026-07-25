"""Locale format conversion utilities.

Pure Python locale helpers with no Odoo dependencies.
"""

import re

import babel

XPG_LOCALE_RE = re.compile(
    r"""^
    ([a-z]+)      # language
    (_[A-Z\d]+)?  # maybe _territory
    # no support for .codeset (we don't use that in Odoo)
    (@.+)?        # maybe @modifier
    $""",
    re.VERBOSE,
)


def py_to_js_locale(locale: str) -> str:
    """Convert a locale from Python (XPG) to JavaScript (BCP 47) format.

    Most of the time the conversion is simply to replace _ with -.
    Example: fr_BE -> fr-BE

    Exception: Serbian can be written in both Latin and Cyrillic scripts
    interchangeably, therefore its locale includes a special modifier
    to indicate which script to use.
    Example: sr@latin -> sr-Latn

    BCP 47 (JS):
        language[-extlang][-script][-region][-variant][-extension][-privateuse]
        https://www.ietf.org/rfc/rfc5646.txt
    XPG syntax (Python):
        language[_territory][.codeset][@modifier]
        https://www.gnu.org/software/libc/manual/html_node/Locale-Names.html

    :param locale: The locale formatted for use on the Python-side.
    :return: The locale formatted for use on the JavaScript-side.
    """
    match_ = XPG_LOCALE_RE.match(locale)
    if not match_:
        return locale
    language, territory, modifier = match_.groups()
    subtags = [language]
    if modifier == "@Cyrl":
        subtags.append("Cyrl")
    elif modifier == "@latin":
        subtags.append("Latn")
    if territory:
        subtags.append(territory.removeprefix("_"))
    return "-".join(subtags)


POSIX_TO_LDML = {
    "a": "E",
    "A": "EEEE",
    "b": "MMM",
    "B": "MMMM",
    "d": "dd",
    "-d": "d",
    "e": "d",
    "H": "HH",
    "I": "hh",
    "j": "DDD",
    "m": "MM",
    "-m": "M",
    "M": "mm",
    "p": "a",
    "S": "ss",
    "U": "w",
    "w": "e",
    "W": "w",
    "y": "yy",
    "Y": "yyyy",
}


def posix_to_ldml(fmt: str, locale: babel.Locale) -> str:
    """Convert a POSIX/strftime pattern into an LDML date format pattern.

    LDML is the Unicode locale-data standard used by Babel and ICU.

    :param fmt: non-extended C89/C90 strftime pattern
    :param locale: babel locale used for locale-specific conversions (e.g. %x and %X)
    :return: LDML date format pattern

    Example::

        >>> from babel import Locale
        >>> posix_to_ldml('%Y-%m-%d', Locale.parse('en_US'))
        'yyyy-MM-dd'
    """
    buf = []
    pc = False
    minus = False
    quoted = []

    for c in fmt:
        if not pc and c.isalpha():
            quoted.append(c if c != "'" else "''")
            continue
        if quoted:
            buf.extend(("'", "".join(quoted), "'"))
            quoted = []

        if pc:
            if c == "-":
                minus = True
                continue
            directive = f"-{c}" if minus else c
            minus = False
            pc = False
            if c == "%":
                buf.append("%")
            elif c == "x":
                buf.append(locale.date_formats["short"].pattern)
            elif c == "X":
                buf.append(locale.time_formats["medium"].pattern)
            elif (ldml := POSIX_TO_LDML.get(directive)) is not None:
                buf.append(ldml)
            else:
                raise ValueError(
                    f"Unsupported strftime directive '%{directive}' in {fmt!r}"
                )
        elif c == "%":
            pc = True
        else:
            buf.append(c)

    if quoted:
        buf.extend(("'", "".join(quoted), "'"))

    if pc:
        buf.append("%")

    return "".join(buf)
