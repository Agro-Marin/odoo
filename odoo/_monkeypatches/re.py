import re


def patch_module() -> None:
    # _MAXCACHE is a CPython implementation global that typeshed does not
    # declare, which is the whole reason this patch has to reach for it.
    re._MAXCACHE = 4096  # type: ignore[attr-defined]
