# ruff: noqa: E402
import gc
import sys

from .release import MIN_PY_VERSION

# raise (not assert): a hard runtime floor must hold under ``python -O``, which
# strips asserts and would let an unsupported interpreter proceed to obscure
# failures deep in a later import.
if sys.version_info[:2] < MIN_PY_VERSION:
    raise RuntimeError(
        f"Outdated python version detected, Odoo requires Python >= "
        f"{'.'.join(map(str, MIN_PY_VERSION))} to run."
    )

# ----------------------------------------------------------
# The ``odoo_rust`` native extension is a HARD requirement of this fork: the ORM
# cache/read paths, the db cursor row mapping, JSON fast-clone and the lint
# scanner all import it directly (there is no Python fallback). Enforce it here,
# early and with a clear message, rather than letting a missing build surface as
# an obscure ModuleNotFoundError deep inside a later import.
# ----------------------------------------------------------
try:
    import odoo_rust  # noqa: F401
except ImportError as exc:
    raise ImportError(
        "The required 'odoo_rust' native extension is not importable. This fork "
        "depends on it (ORM cache/read paths, db cursor, JSON fast-clone, lint "
        "scanner). Build and install it with maturin (e.g. `maturin develop` in "
        "the odoo_rust crate) into the active virtualenv."
    ) from exc

# ----------------------------------------------------------
# Set gc thresolds if they are default, see `odoo.libs.gc`.
# Defaults changed from (700, 10, 10) to (2000, 10, 10) in 3.13
# and the last generation was removed in 3.14.
# ----------------------------------------------------------
if gc.get_threshold()[0] in (700, 2000):
    # Handling requests can sometimes allocate over 5k new objects, let leave
    # some space before starting any collection.
    gc.set_threshold(12_000, 20, 25)

# ----------------------------------------------------------
# Import tools to patch code and libraries
# required to do as early as possible for evented and timezone
# ----------------------------------------------------------
from . import _monkeypatches

_monkeypatches.patch_init()

from .libs.gc import gc_set_timing

gc_set_timing(enable=True)

# ----------------------------------------------------------
# Shortcuts
# Expose them at the `odoo` namespace level
# ----------------------------------------------------------
import odoo

from .orm.primitives import SUPERUSER_ID, Command
from .tools.translate import _, _lt

odoo.SUPERUSER_ID = SUPERUSER_ID
odoo._ = _
odoo._lt = _lt
odoo.Command = Command
