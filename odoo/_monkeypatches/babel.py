import babel.core


def patch_module() -> None:
    babel.core.LOCALE_ALIASES["nb"] = "nb_NO"
