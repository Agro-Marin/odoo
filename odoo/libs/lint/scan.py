from pathlib import Path

from odoo.libs.native import assert_fresh, assert_optimised

__all__ = ["scan_byte_patterns", "scan_regex_patterns"]

try:
    import odoo_lint
except ImportError as exc:  # pragma: no cover - exercised by not installing it
    raise ImportError(
        "The 'odoo_lint' native extension is not importable. It carries the "
        "parallel source scanner behind the test_lint gates and is a separate "
        "wheel from odoo_rust, so a checkout that can run the server can still "
        "be missing it. Build it with `maturin develop --release` in crates/odoo_lint, or "
        "`maturin build --release --manifest-path crates/odoo_lint/Cargo.toml`."
    ) from exc

assert_fresh(
    odoo_lint,
    Path(__file__).resolve().parents[3] / "crates" / "odoo_lint",
    rebuild_hint=(
        " Until it is rebuilt the test_lint ratchets are measuring the previous"
        " version of the scanner."
    ),
)

assert_optimised(odoo_lint)

scan_byte_patterns = odoo_lint.scan_byte_patterns
scan_regex_patterns = odoo_lint.scan_regex_patterns
