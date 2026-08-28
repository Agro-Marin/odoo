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

use pyo3::prelude::*;

mod cache;
mod clone;
mod ffi_ext;
mod ids;
mod prefetch;
mod rows;
mod sort;
mod web;

/// The Python module exported as `odoo_rust`.
///
/// `gil_used = true` is a **claim about this crate, not a default worth
/// inheriting**. PyO3 0.28 inverted the meaning of leaving it off: through
/// 0.27 an unannotated module declared `Py_MOD_GIL_USED` and a free-threaded
/// interpreter re-enabled the GIL to import it; from 0.28 an unannotated
/// module declares `Py_MOD_GIL_NOT_USED` and the interpreter takes it at its
/// word. Nothing in this crate changed when the dependency did, so the
/// unannotated module silently began telling a free-threaded CPython it was
/// safe to run these functions in parallel.
///
/// It is not, and `cache.rs` has said so all along: the batch lookups take
/// **borrowed** references out of `PyDict_GetItem` and `Py_INCREF` them a few
/// instructions later. Under the GIL nothing can run in between. Without it,
/// another thread can replace the dict entry in that window and drop the last
/// reference, and the INCREF lands on freed memory. Making this sound means
/// `PyDict_GetItemRef` on those paths — the same change `batch_group_ids`
/// already took for a different reason — plus an audit of every other borrow
/// here; until that is done the honest declaration is that the GIL is
/// required.
///
/// This costs nothing on a GIL-enabled build, which is every build the fork
/// currently ships. The sibling `odoo_lint` extension declares the same thing
/// for the same reason.
#[pymodule(gil_used = true)]
fn odoo_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Fingerprint of the sources this binary was built from, stamped by
    // build.rs.  `odoo.init` compares it against the crate on disk and refuses
    // to start on a mismatch, so a stale build reports itself instead of
    // segfaulting or silently computing the wrong answer.
    m.add("__source_crc__", env!("ODOO_RUST_SOURCE_CRC"))?;
    // clone
    m.add_function(wrap_pyfunction!(clone::fast_clone, m)?)?;
    // cache. There is deliberately no `scalar_cache_get` here: the single-record
    // lookup it would accelerate is three `dict[key]` subscripts, which CPython
    // already compiles to three C-level `PyDict_GetItem` calls, and the PyO3
    // call boundary costs more than the whole operation. It lives in
    // `_field_access/_fallback.py` and is exported from there.
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
    Ok(())
}
