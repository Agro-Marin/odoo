import codecs
import re


def patch_module() -> None:
    """Resolve charset labels that reach us from mail and imports but not CPython.

    The ISO-8859-8 search function covers the visual and logical Hebrew
    variants: CPython resolves `iso_8859_8_i` on its own, but not the
    separator-less `iso88598i`, and a codec search function is the only
    extension point for a name no alias table entry can spell.

    The Thai codepage no longer needs help.  `874` and `windows_874` are
    aliases in CPython 3.14's own table, and `odoo/release.py` pins the
    interpreter to exactly 3.14, so the two assignments this patch used to make
    only ever rewrote those entries with the values they already held.  They
    were load-bearing up to 3.13, where the aliases are absent -- if the
    interpreter floor is ever lowered, they have to come back.
    """
    iso8859_8 = codecs.lookup("iso8859_8")
    iso8859_8ie_re = re.compile(r"iso[-_]?8859[-_]?8[-_]?[ei]\Z", re.IGNORECASE)
    codecs.register(
        lambda charset: iso8859_8 if iso8859_8ie_re.match(charset) else None
    )
