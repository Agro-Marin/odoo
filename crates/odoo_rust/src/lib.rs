//! Rust-accelerated hot paths for the Odoo ORM.
//!
//! Each submodule targets a specific Python function that was benchmarked
//! and identified as a bottleneck.  This extension is a **hard requirement** of
//! the fork — `odoo.init` raises `ImportError` when it is not importable — so
//! there is no runtime fallback. The pure-Python originals are kept as the test
//! oracle and, in a couple of hit-path cases, as a deliberately-chosen faster
//! variant (see `odoo/libs/_field_access/_fallback.py`), not as a fallback.
//!
//! Submodules:
//! - `clone`: Fast deep-clone for JSON-like data (replaces copy.deepcopy)
//! - `cache`: Batch cache lookups and fills for mapped/filtered/sorted/read
//! - `ids`: Origin ID extraction for NewId-aware record collections
//! - `rows`: Cursor dictfetchall/dictfetchmany acceleration
//! - `web`: CSV export with QUOTE_ALL formatting and cell sanitization
//! - `scan`: Parallel file scanning for lint tests (SIMD + multi-core)

use pyo3::prelude::*;

mod cache;
mod clone;
mod ids;
mod prefetch;
mod rows;
mod scan;
mod sort;
mod web;

/// The Python module exported as `odoo_rust`.
#[pymodule]
fn odoo_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Fingerprint of the sources this binary was built from, stamped by
    // build.rs.  `odoo.init` compares it against the crate on disk and refuses
    // to start on a mismatch, so a stale build reports itself instead of
    // segfaulting or silently computing the wrong answer.
    m.add("__source_crc__", env!("ODOO_RUST_SOURCE_CRC"))?;
    // clone
    m.add_function(wrap_pyfunction!(clone::fast_clone, m)?)?;
    // cache (scalar_cache_get intentionally not exported — the Python
    // fallback is faster on the hit path due to PyO3 boundary overhead)
    m.add_function(wrap_pyfunction!(cache::batch_cache_get, m)?)?;
    m.add_function(wrap_pyfunction!(cache::batch_cache_filter, m)?)?;
    m.add_function(wrap_pyfunction!(cache::batch_cache_values, m)?)?;
    m.add_function(wrap_pyfunction!(cache::batch_cache_fill, m)?)?;
    // ids
    m.add_function(wrap_pyfunction!(ids::origin_ids, m)?)?;
    // prefetch
    m.add_function(wrap_pyfunction!(prefetch::to_prefetch_ids, m)?)?;
    // rows
    m.add_function(wrap_pyfunction!(rows::rows_to_dicts, m)?)?;
    // web
    m.add_function(wrap_pyfunction!(web::csv_export, m)?)?;
    // sort + group (sorted() and grouped() fast paths)
    m.add_function(wrap_pyfunction!(sort::sort_ids_by_values, m)?)?;
    m.add_function(wrap_pyfunction!(sort::sort_ids_by_cache, m)?)?;
    m.add_function(wrap_pyfunction!(sort::batch_group_ids, m)?)?;
    // scan (parallel file scanning for lint tests)
    m.add_function(wrap_pyfunction!(scan::scan_byte_patterns, m)?)?;
    m.add_function(wrap_pyfunction!(scan::scan_regex_patterns, m)?)?;
    Ok(())
}
