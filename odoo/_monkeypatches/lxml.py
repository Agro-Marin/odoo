from lxml.html import defs

XLINK_HREF = "xlink:href"


def patch_module() -> None:
    defs.link_attrs |= {XLINK_HREF}
