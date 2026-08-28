import gc
import sys
from pathlib import Path

from .libs.native import assert_fresh
from .release import MIN_PY_VERSION

if sys.version_info[:2] < MIN_PY_VERSION:
    raise RuntimeError(
        f"Outdated python version detected, Odoo requires Python >= "
        f"{'.'.join(map(str, MIN_PY_VERSION))} to run."
    )

try:
    import odoo_rust
except ImportError as exc:
    raise ImportError(
        "The required 'odoo_rust' native extension is not importable. This fork "
        "depends on it (ORM cache/read/sort paths, db cursor, JSON fast-clone, "
        "CSV export). Build and install it with maturin (e.g. `maturin develop` "
        "in crates/odoo_rust) into the active virtualenv. The lint scanner is a "
        "SEPARATE extension, odoo_lint, needed only to run the test_lint gates."
    ) from exc


_CRATES = Path(__file__).resolve().parents[1] / "crates"

# Fails loudly rather than silently misbehaving when the wheel predates the
# crate. See odoo/libs/native.py for why this exists at all.
assert_fresh(odoo_rust, _CRATES / "odoo_rust")


if gc.get_threshold()[0] in (700, 2000):
    gc.set_threshold(12_000, 20, 25)

from . import _monkeypatches

_monkeypatches.patch_init()

from .libs.gc import gc_set_timing

gc_set_timing(enable=True)
