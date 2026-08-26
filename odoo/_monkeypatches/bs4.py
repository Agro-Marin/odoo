import warnings

import bs4

_OFXPARSE_MODULE_RE = r"ofxparse(\.|\Z)"


def patch_module() -> None:
    """Silence bs4's XML-parsed-as-HTML warning for ofxparse, and only there.

    ofxparse reads OFX -- an XML dialect -- with `BeautifulSoup(fh,
    'html.parser')` at `ofxparse/ofxparse.py:30`, which is exactly what
    `XMLParsedAsHTMLWarning` complains about. The upstream issue (#170) is
    still open, so the warning is noise we cannot fix at the source, and it
    reaches us through `account_bank_statement_import_ofx`.

    The filter is scoped with `module=`, which matches the *calling* module
    rather than bs4: bs4 raises these with a `stacklevel` chosen to point at
    the caller. Without the scope this is a process-global suppression, and
    Odoo code that feeds XML to an HTML parser -- a real mistake worth
    hearing about -- would be silenced along with ofxparse.
    """
    if hasattr(bs4, "XMLParsedAsHTMLWarning"):
        warnings.filterwarnings(
            "ignore",
            category=bs4.XMLParsedAsHTMLWarning,
            module=_OFXPARSE_MODULE_RE,
        )
