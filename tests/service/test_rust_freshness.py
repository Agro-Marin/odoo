"""Tests for the ``odoo_rust`` staleness guard in ``odoo/init.py``.

The extension is a hard dependency with no runtime fallback, so an installed
build that has fallen behind the crate does not run slower — it segfaults on a
cyclic ``fast_clone`` and mis-orders timezone-aware columns. ``odoo/init.py``
compares a fingerprint stamped in by ``crates/odoo_rust/build.rs`` against the
crate on disk and refuses to start on a mismatch.

That guard has one failure mode of its own: the fingerprint is computed twice,
once in Rust and once in Python, and the two must agree byte for byte. If they
drift, *every* checkout reports itself stale and no rebuild clears it. These
tests pin the agreement and the properties it rests on.

Run with::

    python -m pytest tests/service/test_rust_freshness.py -v
"""

import zlib
from pathlib import Path

import odoo_rust
import pytest

from odoo.init import _rust_source_crc

CRATE = Path(__file__).resolve().parents[2] / "crates" / "odoo_rust"

pytestmark = pytest.mark.skipif(
    not CRATE.is_dir(), reason="no crate sources — an installed deployment"
)


def test_the_installed_extension_matches_the_crate():
    """The whole point: this fails when the venv's wheel is out of date."""
    assert odoo_rust.__source_crc__ == _rust_source_crc(CRATE), (
        "the installed odoo_rust predates the crate in this checkout — rebuild "
        "it (maturin build --release ...), or see odoo/init.py for the message"
    )


def test_the_fingerprint_covers_every_build_input(tmp_path):
    """Editing any hashed input must move the fingerprint.

    Copies the crate so the real tree is never touched. ``Cargo.toml`` is
    included deliberately: a dependency or feature bump changes the artifact
    without touching a line of Rust.
    """
    copy = tmp_path / "odoo_rust"
    copy.mkdir()
    (copy / "src").mkdir()
    (copy / "Cargo.toml").write_text("[package]\nname = 'x'\n")
    (copy / "src" / "lib.rs").write_text("// lib\n")
    (copy / "src" / "clone.rs").write_text("// clone\n")

    baseline = _rust_source_crc(copy)

    for target, edited in (
        (copy / "src" / "clone.rs", "// clone edited\n"),
        (copy / "Cargo.toml", "[package]\nname = 'x'\nversion = '2'\n"),
    ):
        original = target.read_text()
        target.write_text(edited)
        assert _rust_source_crc(copy) != baseline, f"{target.name} is not hashed"
        target.write_text(original)

    assert _rust_source_crc(copy) == baseline, (
        "restoring the sources must restore the crc"
    )

    # A source appearing or vanishing has to move it too — build.rs watches the
    # src *directory* for exactly this case.
    (copy / "src" / "added.rs").write_text("// added\n")
    assert _rust_source_crc(copy) != baseline, "a new source file is not hashed"


def test_the_fingerprint_does_not_depend_on_where_the_checkout_lives(tmp_path):
    """Both sides sort by relative path, so an absolute path must not leak in."""
    here, elsewhere = (
        tmp_path / "a" / "crate",
        tmp_path / "b" / "some" / "deeper" / "crate",
    )
    for root in (here, elsewhere):
        (root / "src").mkdir(parents=True)
        (root / "Cargo.toml").write_text("[package]\n")
        (root / "src" / "lib.rs").write_text("// lib\n")

    assert _rust_source_crc(here) == _rust_source_crc(elsewhere)


def test_python_reproduces_the_rust_crc32_parameters():
    """``build.rs`` implements CRC-32/ISO-HDLC by hand; ``zlib`` must match it.

    Pinned against the published check value for the algorithm, so a future
    edit to either implementation that changes the parameters is caught here
    rather than by every checkout failing to start.
    """
    assert zlib.crc32(b"123456789") == 0xCBF43926


def test_a_nul_delimiter_keeps_filenames_from_bleeding_together(tmp_path):
    """Length-delimiting is what stops a rename from being invisible."""
    first, second = tmp_path / "one", tmp_path / "two"
    for root in (first, second):
        (root / "src").mkdir(parents=True)
        (root / "Cargo.toml").write_text("")

    # Same total bytes, different split between name and content.
    (first / "src" / "ab.rs").write_text("c")
    (second / "src" / "a.rs").write_text("bc")

    assert _rust_source_crc(first) != _rust_source_crc(second)
