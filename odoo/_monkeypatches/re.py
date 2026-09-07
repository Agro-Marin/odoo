import re


def patch_module() -> None:
    re._MAXCACHE = 4096  # type: ignore[attr-defined]
