import re


def patch_module() -> None:
    """Default is 512, a little too small for odoo"""
    re._MAXCACHE = 4096  # type: ignore[attr-defined]
