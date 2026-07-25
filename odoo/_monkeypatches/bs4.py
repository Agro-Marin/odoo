import warnings

import bs4


def patch_module() -> None:
    if hasattr(bs4, "XMLParsedAsHTMLWarning"):
        warnings.filterwarnings("ignore", category=bs4.XMLParsedAsHTMLWarning)
