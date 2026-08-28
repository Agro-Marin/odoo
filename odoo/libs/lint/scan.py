"""Parallel source scanning for the ``test_lint`` gates.

The scanner lives in its own native extension, ``odoo_lint``, not in
``odoo_rust``. ``odoo_rust`` is a hard runtime dependency that every deployment
and every worker carries; this is used by four lint suites and never by a
running server, and it brought twenty crates and 890 KB of wheel with it. It is
imported here, lazily, by the only module that needs it.
"""

from pathlib import Path

from odoo.libs.native import assert_fresh

__all__ = ["scan_byte_patterns", "scan_regex_patterns"]

try:
    import odoo_lint
except ImportError as exc:  # pragma: no cover - exercised by not installing it
    raise ImportError(
        "The 'odoo_lint' native extension is not importable. It carries the "
        "parallel source scanner behind the test_lint gates and is a separate "
        "wheel from odoo_rust, so a checkout that can run the server can still "
        "be missing it. Build it with `maturin develop` in crates/odoo_lint, or "
        "`maturin build --release --manifest-path crates/odoo_lint/Cargo.toml`."
    ) from exc

# A stale scanner does not fail, it counts differently — and every gate it feeds
# is an exact-mode ratchet that fails in BOTH directions, so the symptom is a
# ratchet failure that sends you hunting through the tree for a change nobody
# made. Check before the first scan rather than after the first confusing gate.
assert_fresh(
    odoo_lint,
    Path(__file__).resolve().parents[3] / "crates" / "odoo_lint",
    rebuild_hint=(
        " Until it is rebuilt the test_lint ratchets are measuring the previous"
        " version of the scanner."
    ),
)

scan_byte_patterns = odoo_lint.scan_byte_patterns
scan_regex_patterns = odoo_lint.scan_regex_patterns
