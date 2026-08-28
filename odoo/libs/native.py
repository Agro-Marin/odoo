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

The algorithm has to match ``odoo_build::stamp_build_identity`` byte for byte:
the workspace ``Cargo.lock`` (labelled ``../Cargo.lock``), the crate's
``Cargo.toml`` and every ``.rs`` under ``src/``, each entry length-delimited by
its crate-relative POSIX path and a NUL, sorted by that path, CRC-32/ISO-HDLC.
``zlib.crc32`` is that CRC, and being C makes the check immeasurable at startup.

The **profile** is the axis the CRC cannot see, and it needs its own assertion:
a debug and a release build of identical sources fingerprint identically.
``maturin develop`` defaults to ``dev``, and a debug ``odoo_rust`` is not merely
slower -- four of its exports are slower than the pure Python they exist to
delete (``origin_ids`` 4.08x, ``sort_ids_by_values`` 3.84x, ``to_prefetch_ids``
2.53x, ``sort_ids_by_cache`` 2.41x). :func:`assert_optimised` names the cause,
which ``test_native_acceleration_pays`` -- the gate that does catch it -- cannot,
because from where it stands the symptom is an algorithm that stopped paying.
"""

import os
import zlib
from pathlib import Path

__all__ = ["assert_fresh", "assert_optimised", "source_crc"]

#: Set to bypass every freshness check — for bisects and for running against a
#: deliberately older wheel. Named once here rather than spelled at each site.
SKIP_ENV = "ODOO_SKIP_RUST_FRESHNESS_CHECK"

#: Set to run on a debug build anyway — for attaching a debugger to the crate.
#: Separate from :data:`SKIP_ENV` because the two answer different questions:
#: one is "this build is old", the other "this build is slow".
ALLOW_DEBUG_ENV = "ODOO_ALLOW_DEBUG_RUST"


def source_crc(crate: Path) -> str:
    """Fingerprint the workspace ``Cargo.lock``, ``crate``'s ``Cargo.toml`` and
    its ``src/**/*.rs``.

    The lock is an input because a manifest names a *range*: these crates ask
    for ``pyo3 = "0.29.2"``, which any 0.29.x satisfies, so a ``cargo update``
    changes the built artifact while every hashed file stays byte-identical. It
    is skipped when absent, which is how a crate copied somewhere for a test
    hashes at all.
    """
    lock = crate.parent / "Cargo.lock"
    inputs = sorted(
        [
            (path.relative_to(crate).as_posix(), path)
            for path in (crate / "Cargo.toml", *(crate / "src").rglob("*.rs"))
        ]
        # Labelled the way the Rust side labels it: it is the one input that
        # does not live under the crate, so it has no crate-relative path.
        + ([("../Cargo.lock", lock)] if lock.is_file() else []),
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
        f"(or `maturin develop --release` in {crate}.)"
        f"{rebuild_hint}"
        f" Set {SKIP_ENV}=1 to bypass this check."
    )


def assert_optimised(module: object) -> None:
    """Raise unless ``module`` was built with optimisations on.

    A no-op for a wheel built before this stamp existed: it carries no
    ``__profile__``, and refusing to start on an extension that predates the
    check would make upgrading harder than the thing being checked for.
    """
    if os.environ.get(ALLOW_DEBUG_ENV):
        return
    profile = getattr(module, "__profile__", None)
    if profile is None or profile == "release":
        return

    name = getattr(module, "__name__", str(module))
    raise RuntimeError(
        f"The installed {name!r} extension was built with the {profile!r} "
        f"profile. It has no pure-Python fallback and exists only to be faster; "
        f"unoptimised, four of its exports are slower than the code they "
        f"replace. `maturin develop` defaults to this profile — pass --release:"
        f"\n    maturin develop --release\n"
        f"Set {ALLOW_DEBUG_ENV}=1 to run on it anyway (attaching a debugger)."
    )
