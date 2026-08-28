"""Freshness checking for the workspace's native extensions.

A compiled extension that has fallen behind its sources does not degrade, it
misbehaves, and the failure never names its cause: a stale ``odoo_rust`` once
segfaulted the DB-free suite on a cyclic structure and silently mis-ordered a
timezone-aware column, because the installed wheel predated the recursion guard
and the aware-datetime bail-out. CI never sees it — every lane builds fresh —
so only long-lived development virtualenvs are exposed, which is exactly where
it is hardest to attribute.

Each crate's build script stamps ``__source_crc__`` onto the module it builds
(``crates/odoo_build``). This recomputes the same value from the crate on disk,
so importing an extension whose sources have moved on raises a sentence instead
of misbehaving.

The algorithm has to match ``odoo_build::stamp_source_crc`` byte for byte:
``Cargo.toml`` plus every ``.rs`` under ``src/``, each entry length-delimited by
its crate-relative POSIX path and a NUL, sorted by that path, CRC-32/ISO-HDLC.
``zlib.crc32`` is that CRC, and being C makes the check immeasurable at startup.
"""

import os
import zlib
from pathlib import Path

__all__ = ["assert_fresh", "source_crc"]

#: Set to bypass every freshness check — for bisects and for running against a
#: deliberately older wheel. Named once here rather than spelled at each site.
SKIP_ENV = "ODOO_SKIP_RUST_FRESHNESS_CHECK"


def source_crc(crate: Path) -> str:
    """Fingerprint ``crate``'s ``Cargo.toml`` and ``src/**/*.rs``."""
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


def assert_fresh(module: object, crate: Path, *, rebuild_hint: str = "") -> None:
    """Raise unless ``module`` was built from the sources now in ``crate``.

    A no-op when the crate is absent, which is the normal shape of an installed
    deployment: there is nothing to compare against, and the wheel is whatever
    was released. The check only bites in a development checkout, where the
    sources and the build can disagree.
    """
    if not crate.is_dir() or os.environ.get(SKIP_ENV):
        return

    built = getattr(module, "__source_crc__", None)
    current = source_crc(crate)
    if built == current:
        return

    name = getattr(module, "__name__", str(module))
    was = "predates the build script" if built is None else f"built from {built}"
    raise RuntimeError(
        f"The installed {name!r} extension is stale: it was {was}, but the "
        f"crate in this checkout is {current}. It is a hard dependency with no "
        f"fallback, so running on it gives wrong results rather than slow "
        f"ones. Rebuild it:\n"
        f"    maturin build --release --manifest-path "
        f"{crate.name and f'crates/{crate.name}/Cargo.toml'} --out dist\n"
        f"    pip install --force-reinstall --no-deps dist/{name}-*.whl\n"
        f"(or `maturin develop` in {crate}.)"
        f"{rebuild_hint}"
        f" Set {SKIP_ENV}=1 to bypass this check."
    )
