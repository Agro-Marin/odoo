import functools
import mimetypes
from typing import Any, Final

#: What the web must be served as, whatever the host says.
WEB_TYPES: Final[tuple[tuple[str, str], ...]] = (
    ("font/woff", ".woff"),
    ("application/vnd.ms-fontobject", ".eot"),
    ("font/ttf", ".ttf"),
    ("image/webp", ".webp"),
    ("image/svg+xml", ".svg"),
    ("text/javascript", ".js"),
)


def add_web_types() -> None:
    for mimetype, extension in WEB_TYPES:
        mimetypes.add_type(mimetype, extension)


def patch_module() -> None:
    """Pin six extensions against a host mapping that disagrees.

    CPython 3.14's own table already agrees on all six, so on a well-configured
    Linux box this changes nothing. It is not there for that box: `init()`
    reads `knownfiles` -- a distro `/etc/mime.types` -- and on Windows the
    registry, and whatever it finds *overrides* the defaults. Serving `.js` as
    `text/plain` is a broken web client.

    `init()` is also what makes a plain `add_type()` insufficient: it rebuilds
    the database from scratch and silently discards every earlier addition. So
    the re-application is wrapped around it rather than done once, which is
    what makes the pin a guarantee instead of a statement about import order.
    """
    add_web_types()

    if getattr(mimetypes.init, "_odoo_repins", False):
        return

    original_init = mimetypes.init

    @functools.wraps(original_init)
    def init(files: Any = None) -> None:
        original_init(files)
        add_web_types()

    init._odoo_repins = True
    mimetypes.init = init
