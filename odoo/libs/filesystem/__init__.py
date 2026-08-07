"""Odoo-agnostic filesystem utilities.

Pure Python filesystem helpers with no Odoo dependencies.

The public boundary of this area is the package, not its modules. Every name
``mimetypes`` declares in its own ``__all__`` is re-exported here;
``_odoo_guess_mimetype`` deliberately is not — it is the pure-Python fallback
used only to test the python-magic path against, and it stays module-private.
"""

from . import appdirs
from . import osutil
from . import mimetypes
from .mimetypes import (
    MIMETYPE_HEAD_SIZE,
    UNKNOWN_MIMETYPE,
    _olecf_mimetypes,
    fix_filename_extension,
    get_extension,
    guess_mimetype,
    neuter_mimetype,
    SystemUser,
)
from .which import which

__all__ = [
    "MIMETYPE_HEAD_SIZE",
    "UNKNOWN_MIMETYPE",
    "SystemUser",
    "_olecf_mimetypes",
    "appdirs",
    "fix_filename_extension",
    "get_extension",
    "guess_mimetype",
    "mimetypes",
    "neuter_mimetype",
    "osutil",
    "which",
]
