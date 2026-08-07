import gc
import sys

from .release import MIN_PY_VERSION

if sys.version_info[:2] < MIN_PY_VERSION:
    raise RuntimeError(
        f"Outdated python version detected, Odoo requires Python >= "
        f"{'.'.join(map(str, MIN_PY_VERSION))} to run."
    )

try:
    import odoo_rust  # noqa: F401  hard dependency probe; the ImportError below is the message
except ImportError as exc:
    raise ImportError(
        "The required 'odoo_rust' native extension is not importable. This fork "
        "depends on it (ORM cache/read paths, db cursor, JSON fast-clone, lint "
        "scanner). Build and install it with maturin (e.g. `maturin develop` in "
        "the odoo_rust crate) into the active virtualenv."
    ) from exc

if gc.get_threshold()[0] in (700, 2000):
    gc.set_threshold(12_000, 20, 25)

from . import _monkeypatches

_monkeypatches.patch_init()

from .libs.gc import gc_set_timing

gc_set_timing(enable=True)
