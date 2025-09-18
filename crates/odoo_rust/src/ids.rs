//! Origin ID extraction for NewId-aware record collections.
//!
//! Replaces `OriginIds.__iter__` — a Python generator that for each id:
//! - Yields it directly if truthy (int > 0)
//! - Checks `getattr(id, "origin", None)` and yields origin if truthy
//! - Skips the id otherwise (no origin, or origin is falsy)
//!
//! The Rust version is faster because:
//! - No generator frame creation/suspension overhead
//! - Interned "origin" attribute lookup (single hash, cached across calls)
//! - Direct C-API truthiness check instead of Python `bool()`

use pyo3::exceptions::PyAttributeError;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyTuple};

/// Extract origin IDs from a tuple of record IDs.
///
/// For each element in `ids`:
/// - If truthy (int > 0, or any truthy object): included as-is.
/// - If falsy (NewId, 0): checks `getattr(id, "origin", None)`.
///   If origin is truthy, includes the origin; otherwise skips.
///   Only `AttributeError` is suppressed — other exceptions from `__getattr__`
///   propagate, matching the semantics of Python's `getattr(id, "origin", None)`.
///
/// Returns a list of origin IDs (never None — always succeeds).
#[pyfunction]
pub fn origin_ids<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
) -> PyResult<Py<PyList>> {
    let n = ids.len();
    let mut result: Vec<Bound<'py, PyAny>> = Vec::with_capacity(n);
    let origin_attr = pyo3::intern!(py, "origin");

    for i in 0..n {
        let id_obj = ids.get_item(i)?;
        if id_obj.is_truthy()? {
            result.push(id_obj);
        } else {
            match id_obj.getattr(origin_attr) {
                Ok(origin) => {
                    if origin.is_truthy()? {
                        result.push(origin);
                    }
                }
                Err(e) if e.is_instance_of::<PyAttributeError>(py) => {
                    // No 'origin' attribute — matches getattr(id_, 'origin', None)
                }
                Err(e) => return Err(e), // Re-raise unexpected exceptions
            }
        }
    }

    Ok(PyList::new(py, &result)?.unbind())
}
