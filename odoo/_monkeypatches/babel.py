import babel.core


def patch_module() -> None:
    """Give bare `nb` a territory so Accept-Language detection resolves it.

    `http/request_class.py::Request.best_lang` maps a territory-less language
    tag through `LOCALE_ALIASES`, and Babel ships aliases for the other bare
    tags it expects to see but not for Norwegian Bokmal.  A browser sending
    `Accept-Language: nb` therefore raised `KeyError`, which `best_lang` turns
    into "no preference at all" -- silent, and indistinguishable from a client
    that sent no header.
    """
    babel.core.LOCALE_ALIASES["nb"] = "nb_NO"
