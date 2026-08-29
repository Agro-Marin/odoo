import warnings

import bs4

_OFXPARSE_MODULE_RE = r"ofxparse(\.|\Z)"


def patch_module() -> None:
    if hasattr(bs4, "XMLParsedAsHTMLWarning"):
        warnings.filterwarnings(
            "ignore",
            category=bs4.XMLParsedAsHTMLWarning,
            module=_OFXPARSE_MODULE_RE,
        )
