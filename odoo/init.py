import gc
import os
import sys
import zlib
from pathlib import Path

from .release import MIN_PY_VERSION

if sys.version_info[:2] < MIN_PY_VERSION:
    raise RuntimeError(
        f"Outdated python version detected, Odoo requires Python >= "
        f"{'.'.join(map(str, MIN_PY_VERSION))} to run."
    )

try:
    # Hard dependency probe; the ImportError below is the message. The module
    # object is used again by the freshness check further down.
    import odoo_rust
except ImportError as exc:
    raise ImportError(
        "The required 'odoo_rust' native extension is not importable. This fork "
        "depends on it (ORM cache/read paths, db cursor, JSON fast-clone, lint "
        "scanner). Build and install it with maturin (e.g. `maturin develop` in "
        "the odoo_rust crate) into the active virtualenv."
    ) from exc


def _rust_source_crc(crate):
    """CRC32 of the crate's build inputs — mirrors `crates/odoo_rust/build.rs`.

    Both sides feed the same length-delimited blob, in relative-path order, to
    CRC-32/ISO-HDLC.  Keep the two in step: a change to what is hashed, or in
    what order, must land in both files or every checkout reports itself stale.
    """
    inputs = sorted(
        (
            (path.relative_to(crate).as_posix(), path)
            for path in (crate / "Cargo.toml", *(crate / "src").rglob("*.rs"))
        ),
        key=lambda pair: pair[0],
    )
    blob = b"".join(
        rel.encode() + b"\0" + path.read_bytes() + b"\0" for rel, path in inputs
    )
    return f"{zlib.crc32(blob):08x}"


# A development checkout carries the crate that built the extension, so it can
# prove the two agree.  An installed deployment has no crate to compare against
# and skips the check.  The extension is a hard dependency with no fallback, so
# a stale build does not degrade gracefully -- it segfaults on a cyclic clone
# and mis-orders timezone-aware columns, neither of which names its own cause.
_RUST_CRATE = Path(__file__).resolve().parents[1] / "crates" / "odoo_rust"

if _RUST_CRATE.is_dir() and not os.environ.get("ODOO_SKIP_RUST_FRESHNESS_CHECK"):
    _built = getattr(odoo_rust, "__source_crc__", None)
    _current = _rust_source_crc(_RUST_CRATE)
    if _built != _current:
        _was = "predates build.rs" if _built is None else f"built from {_built}"
        raise RuntimeError(
            f"The installed 'odoo_rust' extension is stale: it was {_was}, but "
            f"the crate in this checkout is {_current}. It is a hard dependency "
            f"with no fallback, so running on it gives wrong results rather "
            f"than slow ones. Rebuild it:\n"
            f"    maturin build --release --manifest-path crates/odoo_rust/Cargo.toml --out dist\n"
            f"    pip install --force-reinstall --no-deps dist/odoo_rust-*.whl\n"
            f"(or `maturin develop` in {_RUST_CRATE}). Set "
            f"ODOO_SKIP_RUST_FRESHNESS_CHECK=1 to bypass this check."
        )

if gc.get_threshold()[0] in (700, 2000):
    gc.set_threshold(12_000, 20, 25)

from . import _monkeypatches

_monkeypatches.patch_init()

from .libs.gc import gc_set_timing

gc_set_timing(enable=True)
