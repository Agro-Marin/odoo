import zlib
from pathlib import Path

import odoo_rust
import pytest

from odoo.libs.native import assert_fresh, source_crc

_rust_source_crc = source_crc

CRATES = Path(__file__).resolve().parents[2] / "crates"
CRATE = CRATES / "odoo_rust"

pytestmark = pytest.mark.skipif(
    not CRATE.is_dir(), reason="no crate sources — an installed deployment"
)


def test_the_installed_extension_matches_the_crate():
    assert odoo_rust.__source_crc__ == source_crc(CRATE), (
        "the installed odoo_rust predates the crate in this checkout — rebuild "
        "it (maturin build --release ...), or see odoo/init.py for the message"
    )


def test_every_native_crate_is_covered_by_a_freshness_check():
    """The check is per crate; a new one must not be able to arrive unguarded.

    `odoo_lint` was split out of `odoo_rust` and inherited nothing
    automatically — its guard lives in `odoo/libs/lint/scan.py`, at its own
    single import site, because that module is the only importer and is loaded
    only by the lint gates.
    """
    crates = {p.name for p in CRATES.iterdir() if (p / "Cargo.toml").is_file()}
    # odoo_build ships no extension: it is a build script's dependency.
    extensions = crates - {"odoo_build"}
    assert extensions == {"odoo_rust", "odoo_lint"}, (
        f"native extension crates are now {sorted(extensions)}; each needs an "
        f"assert_fresh() at its import site, and this list updated"
    )
    for name in sorted(extensions):
        assert (CRATES / name / "build.rs").read_text().find("stamp_source_crc") > 0, (
            f"{name}/build.rs does not stamp a source crc, so nothing can "
            f"detect a stale build of it"
        )


def test_assert_fresh_raises_on_a_mismatch_and_passes_on_a_match(tmp_path):
    class Module:
        __name__ = "pretend_ext"
        __source_crc__ = "deadbeef"

    crate = tmp_path / "pretend_ext"
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text("[package]\n")
    (crate / "src" / "lib.rs").write_text("// lib\n")

    module = Module()
    with pytest.raises(RuntimeError, match="stale"):
        assert_fresh(module, crate)

    module.__source_crc__ = source_crc(crate)
    assert_fresh(module, crate)  # matching: silent

    # A crate that is not on disk is an installed deployment, not a failure.
    assert_fresh(Module(), tmp_path / "absent")


def test_the_fingerprint_covers_every_build_input(tmp_path):
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

    (copy / "src" / "added.rs").write_text("// added\n")
    assert _rust_source_crc(copy) != baseline, "a new source file is not hashed"


def test_the_fingerprint_does_not_depend_on_where_the_checkout_lives(tmp_path):
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
    assert zlib.crc32(b"123456789") == 0xCBF43926


def test_a_nul_delimiter_keeps_filenames_from_bleeding_together(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    for root in (first, second):
        (root / "src").mkdir(parents=True)
        (root / "Cargo.toml").write_text("")

    (first / "src" / "ab.rs").write_text("c")
    (second / "src" / "a.rs").write_text("bc")

    assert _rust_source_crc(first) != _rust_source_crc(second)
