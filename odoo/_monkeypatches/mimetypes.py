import functools
import mimetypes
from typing import Any, Final, Protocol


class _RepinningInit(Protocol):
    # mimetypes.init resets the type map, dropping the types added above; the
    # wrapper re-adds them and carries this marker so a second patch_module()
    # does not wrap the wrapper. The Protocol is what makes the marker a
    # declared contract rather than an attribute stamped onto a function.
    _odoo_repins: bool

    def __call__(self, files: Any = None) -> None: ...


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
    add_web_types()

    if getattr(mimetypes.init, "_odoo_repins", False):
        return

    original_init = mimetypes.init

    @functools.wraps(original_init)
    def init(files: Any = None) -> None:
        original_init(files)
        add_web_types()

    repinning: _RepinningInit = init  # type: ignore[assignment]
    repinning._odoo_repins = True
    mimetypes.init = repinning
