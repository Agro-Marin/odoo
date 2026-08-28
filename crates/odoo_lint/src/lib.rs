//! Parallel source scanning for the `test_lint` gates.
//!
//! Split out of `odoo_rust` because it does not belong in it. `odoo_rust` is a
//! **hard runtime dependency** — `odoo/init.py` refuses to start without it, so
//! every deployment, every worker and every CI lane carries whatever it
//! contains. This scanner is used by exactly four lint suites and never by a
//! running server, yet it dominated the wheel: measured on the same sources,
//! removing it took the production extension from **1156 KB to 266 KB** and its
//! dependency graph from **35 crates to 15**, dropping `ignore`, `regex`,
//! `memchr`, `walkdir`, `globset`, `aho-corasick`, `bstr`, the three
//! `crossbeam` crates, `serde` and eight more — none of which any production
//! code path can reach.
//!
//! It is a separate wheel rather than a cargo feature because a feature that is
//! on by default saves nothing, and one that is off by default has to be turned
//! on by every workflow that runs a lint gate — which is the same work as
//! installing a second wheel, with the failure mode of silently shipping a
//! module missing half its symbols instead of a clean `ImportError`.
//!
//! `odoo/libs/lint/scan.py` is the only importer.

use pyo3::prelude::*;

mod scan;

/// The Python module exported as `odoo_lint`.
///
/// `gil_used = true` for the same reason `odoo_rust` declares it: PyO3 0.28
/// inverted the default, so an unannotated module now tells a free-threaded
/// CPython it is safe to run without the GIL. This crate has never been
/// executed under a free-threaded interpreter — `freethreading.yml` scopes
/// itself to the pure-Python suites — and asserting safety that has never been
/// tested is wrong whether or not it happens to hold.
///
/// The scanner does release the GIL, deliberately and narrowly, with
/// `py.detach()` around the walk; that is unrelated. It hands Rust-native data
/// to Rust threads that touch no Python object at all, and reacquires before
/// returning.
#[pymodule(gil_used = true)]
fn odoo_lint(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Fingerprint of the sources this binary was built from, stamped by
    // build.rs. `odoo/libs/lint/scan.py` compares it against the crate on disk:
    // a stale scanner reports different findings, and the gates it feeds are
    // exact-mode ratchets that fail in BOTH directions, so the symptom is a
    // ratchet failure that sends you looking through the tree for a change
    // nobody made.
    m.add("__source_crc__", env!("ODOO_LINT_SOURCE_CRC"))?;
    m.add_function(wrap_pyfunction!(scan::scan_byte_patterns, m)?)?;
    m.add_function(wrap_pyfunction!(scan::scan_regex_patterns, m)?)?;
    Ok(())
}
