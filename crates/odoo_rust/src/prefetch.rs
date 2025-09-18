//! Prefetch ID selection for Field.__get__ cache misses.
//!
//! Replaces `Field._to_prefetch()` — the set-based filtering loop that selects
//! which record IDs to fetch in a single SQL query when a cache miss occurs.
//!
//! Called on *every* lazy field access (potentially 1000s of times per RPC),
//! this is one of the highest-frequency functions in the ORM.
//!
//! The Rust version is faster because:
//! - `PyDict_Contains` for O(1) cache membership testing (same as Python's
//!   `id_ not in field_cache`) without the O(n) cost of building a HashSet
//!   from all cache keys upfront.  The previous HashSet approach was slower
//!   than Python for warm caches (field_cache.len() > PREFETCH_MAX).
//! - `HashSet<i64>` for the small "already added" tracking set (deduplicate
//!   prefetch_ids without re-adding IDs already in the result).
//! - No Python `bool()` coercion dispatch per ID.
//! - No generator frame creation/suspension overhead.

use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use std::collections::HashSet;

/// Build the list of IDs to prefetch for a given record.
///
/// This is the computational core of `Field._to_prefetch()`:
/// 1. `result = [record_id]`
/// 2. For each id in prefetch_ids (up to `prefetch_max`):
///    - If id is a positive int not in `field_cache` and not already added:
///      append to result.
///    - Skip NewId objects (falsy) and already-seen/cached ids.
/// 3. Return result as a Python tuple (ready for `browse()`)
///
/// Returns `None` if `record_id` is not a positive integer (NewId case),
/// signaling the caller to use the Python fallback.
#[pyfunction]
pub fn to_prefetch_ids<'py>(
    py: Python<'py>,
    record_id: &Bound<'py, PyAny>,
    prefetch_ids: &Bound<'py, PyTuple>,
    field_cache: &Bound<'py, PyDict>,
    prefetch_max: usize,
) -> PyResult<Option<Py<PyTuple>>> {
    // Only handle real records (positive int IDs).
    // NewId objects fail extract::<i64>(), and id=0 is not a valid DB id.
    let rec_id: i64 = match record_id.extract() {
        Ok(id) if id > 0 => id,
        _ => return Ok(None), // Fall back to Python for NewId
    };

    // `seen` tracks only the IDs WE'VE added to result (to deduplicate).
    // Field cache membership is checked per-ID via PyDict_Contains — O(1)
    // per lookup, matching Python's `id_ not in field_cache`.  This avoids
    // the O(n) cost of iterating all cache keys to build a HashSet upfront,
    // which was slower than Python for warm caches (large n).
    let mut seen: HashSet<i64> = HashSet::with_capacity(prefetch_max.min(32));
    seen.insert(rec_id);

    let n = prefetch_ids.len();
    let capacity = prefetch_max.min(n + 1);
    let mut result: Vec<Bound<'py, PyAny>> = Vec::with_capacity(capacity);
    result.push(record_id.clone());

    // SAFETY: cache_ptr is borrowed from a live Python dict with 'py lifetime.
    // PyDict_Contains: returns 1 (present), 0 (absent), -1 (error — key not
    // hashable).  i64 record IDs are always hashable so -1 won't occur, but
    // we check anyway for correctness.
    let cache_ptr = field_cache.as_ptr();

    for i in 0..n {
        if result.len() >= prefetch_max {
            break;
        }
        let id_obj = prefetch_ids.get_item(i)?;
        if let Ok(id_val) = id_obj.extract::<i64>() {
            if id_val > 0 {
                // O(1) dict lookup — mirrors Python's `id_ not in field_cache`
                let in_cache =
                    unsafe { ffi::PyDict_Contains(cache_ptr, id_obj.as_ptr()) };
                if in_cache < 0 {
                    return Err(PyErr::fetch(py));
                }
                // seen.insert() returns true if newly inserted (not a duplicate)
                if in_cache == 0 && seen.insert(id_val) {
                    result.push(id_obj);
                }
            }
        }
        // Non-int IDs (NewId): bool(NewId) == False → skip (kind == True path only)
    }

    // Return a tuple — browse() uses tuples directly without conversion.
    Ok(Some(PyTuple::new(py, &result)?.unbind()))
}
