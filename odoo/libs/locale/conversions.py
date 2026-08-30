import re

import babel

__all__ = [
    "POSIX_TO_LDML",
    "XPG_LOCALE_RE",
    "posix_to_ldml",
    "py_to_js_locale",
]


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


def _ldml_literal(text: str) -> str:
    """Encode a run of strftime literal text as an LDML literal.

    Apostrophes double, and the run is wrapped in quotes only when it carries
    something that would otherwise be read as pattern letters. A run that is
    *only* apostrophes must stay unwrapped: LDML reads a leading ``''`` as one
    escaped apostrophe rather than as an opening quote, so wrapping ``'`` gives
    ``''''``, which babel renders as two.
    """
    escaped = text.replace("'", "''")
    return escaped if text and not text.strip("'") else f"'{escaped}'"


def posix_to_ldml(fmt: str, locale: babel.Locale) -> str:
    buf: list[str] = []
    pc = False
    minus = False
    quoted: list[str] = []

    for c in fmt:
        # The apostrophe belongs *inside* the literal run, not between two runs.
        # It is not `isalpha()`, so it used to fall through to `buf.append(c)`
        # and land between a closing and an opening quote: "%d o'clock" became
        # "dd 'o'''clock'", which LDML reads as literal "o'" followed by `clock`
        # as pattern letters -- babel renders that "29 o'7lo715".
        if not pc and (c.isalpha() or c == "'"):
            quoted.append(c)
            continue
        if quoted:
            buf.append(_ldml_literal("".join(quoted)))
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
        buf.append(_ldml_literal("".join(quoted)))

    if pc:
        buf.append("%")

    return "".join(buf)
