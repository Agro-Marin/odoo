import gc
import sys
import warnings
from pathlib import Path

from .libs.native import assert_fresh, assert_optimised, native_required
from .release import MIN_PY_VERSION

if sys.version_info[:2] < MIN_PY_VERSION:
    raise RuntimeError(
        f"Outdated python version detected, Odoo requires Python >= "
        f"{'.'.join(map(str, MIN_PY_VERSION))} to run."
    )

try:
    import odoo_rust
except ImportError as exc:
    if native_required():
        raise ImportError(
            "The 'odoo_rust' native extension is not importable and "
            "ODOO_REQUIRE_NATIVE (or CI) is set, so the pure-Python fallbacks are "
            "not acceptable here. Build and install it with maturin (e.g. "
            "`maturin develop --release` in crates/odoo_rust) into the active "
            "virtualenv. The lint scanner is a SEPARATE extension, odoo_lint, "
            "needed only to run the test_lint gates."
        ) from exc
    warnings.warn(
        "The 'odoo_rust' native extension is not importable; running on the "
        "pure-Python fallbacks, which are slower, not wrong. Build it with "
        "`maturin develop --release` in crates/odoo_rust, or set "
        "ODOO_REQUIRE_NATIVE=1 to make its absence fatal, as CI does.",
        RuntimeWarning,
        stacklevel=1,
    )
    odoo_rust = None


_CRATES = Path(__file__).resolve().parents[1] / "crates"

if odoo_rust is not None:
    assert_fresh(odoo_rust, _CRATES / "odoo_rust")
    assert_optimised(odoo_rust)


if gc.get_threshold()[0] in (700, 2000):
    gc.set_threshold(12_000, 20, 25)

from . import _monkeypatches

_monkeypatches.patch_init()

from .libs.gc import gc_set_timing

gc_set_timing(enable=True)
