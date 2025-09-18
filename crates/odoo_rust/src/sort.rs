//! Sort and group operations on (ids, values) pairs.
//!
//! Two entry points:
//! - [`sort_ids_by_values`]: stable sort of a record ID tuple by cached values,
//!   with optional null-aware (None/False) handling.
//! - [`batch_group_ids`]: group record IDs by corresponding values, returning
//!   a plain Python dict.
//!
//! Both operate on (`ids: tuple`, `values: list`) pairs that are produced by
//! [`crate::cache::batch_cache_get`] / [`crate::cache::batch_cache_values`],
//! replacing the Python-level loops in `sorted()` and `grouped()`.
//!
//! # Performance notes
//!
//! `sort_ids_by_values` avoids the Python pattern:
//!   `list(zip(ids, values)) + sort(key=itemgetter(1)) + tuple(pair[0] for ...)`
//! which creates N two-element Python tuples before sorting and N key-function
//! calls during the sort.  The Rust version builds a `Vec<usize>` index array,
//! sorts it in-place (stable, Timsort equivalent), then builds the result tuple
//! from the original `ids` — zero new Python objects during sort.
//!
//! `batch_group_ids` replaces the `defaultdict(list)` loop in `grouped()`:
//!   `for i, rec_id in enumerate(ids): collator[results[i]].append(rec_id)`
//! with a tight C loop using `PyDict_GetItem` + `PyList_Append`, eliminating
//! Python loop overhead and `defaultdict.__missing__` dispatch.

use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};

// ── Helpers ──────────────────────────────────────────────────────────────────

/// Compare two Python objects using `<` / `>` (Python's `__lt__`/`__gt__`).
///
/// Equivalent to Python's `Py_LT` / `Py_GT` rich comparison.  Returns
/// `Ordering::Equal` and sets `*sort_err` on any comparison error.
///
/// SAFETY: `va` and `vb` must be valid, non-null Python object pointers.
#[inline]
unsafe fn compare_py(
    py: Python<'_>,
    va: *mut ffi::PyObject,
    vb: *mut ffi::PyObject,
    sort_err: &mut Option<PyErr>,
) -> std::cmp::Ordering {
    unsafe {
        let lt = ffi::PyObject_RichCompareBool(va, vb, ffi::Py_LT);
        if lt < 0 {
            *sort_err = Some(PyErr::fetch(py));
            return std::cmp::Ordering::Equal;
        }
        if lt != 0 {
            return std::cmp::Ordering::Less;
        }
        let gt = ffi::PyObject_RichCompareBool(va, vb, ffi::Py_GT);
        if gt < 0 {
            *sort_err = Some(PyErr::fetch(py));
            return std::cmp::Ordering::Equal;
        }
        if gt != 0 {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Equal
        }
    }
}

// ── Public functions ──────────────────────────────────────────────────────────

/// Sort record IDs by corresponding cached values.
///
/// `sort_ids_by_values(ids, values, reverse, null_high=None) -> tuple`
///
/// - `ids`: tuple of record IDs (the `self._ids` tuple)
/// - `values`: list of cached values, one per id (same length as ids)
/// - `reverse`: if True, sort descending
/// - `null_high`: `None` = no null handling (treat None/False as regular values);
///                `True` = None/False sort last in ASC (high/after non-nulls);
///                `False` = None/False sort first in ASC (low/before non-nulls)
///
/// Returns a new tuple of IDs in sorted order.
///
/// Replaces the Python pattern used in `_sorted_by_ids`:
/// ```text
/// # no-null path:
/// pairs = list(zip(ids, values))
/// pairs.sort(key=itemgetter(1), reverse=reverse_param)
/// return tuple(pair[0] for pair in pairs)
///
/// # null-aware path:
/// keys = [(_null_rank, "") if v is None or v is False else (_val_rank, v) ...]
/// ... same sort + extract ...
/// ```
///
/// The Rust version uses a `Vec<usize>` index array sorted in-place (stable
/// Timsort equivalent), then builds the output tuple from the original `ids`.
/// Zero new Python objects are created during the sort itself.
#[pyfunction]
#[pyo3(signature = (ids, values, reverse, null_high = None))]
pub fn sort_ids_by_values<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    values: &Bound<'py, PyList>,
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Py<PyTuple>> {
    let n = ids.len();
    if n <= 1 {
        return Ok(ids.clone().unbind());
    }

    let ids_ptr = ids.as_ptr();
    let values_ptr = values.as_ptr();

    // Build index array [0, 1, ..., n-1] and sort it by values[i].
    // `sort_by` is a stable sort (like Python's Timsort), so equal values
    // preserve the original relative order of their IDs.
    let mut indices: Vec<usize> = (0..n).collect();
    let mut sort_err: Option<PyErr> = None;

    // SAFETY: ids_ptr from a live PyTuple; values_ptr from a live PyList.
    // Both are indexed in range [0, n-1].  PyList_GET_ITEM / PyTuple_GET_ITEM
    // skip bounds checks — safe here because we iterate 0..n.
    // PyObject_RichCompareBool is safe to call with the GIL held.
    unsafe {
        let none_ptr = ffi::Py_None();
        let false_ptr = ffi::Py_False();

        indices.sort_by(|&a, &b| {
            if sort_err.is_some() {
                return std::cmp::Ordering::Equal;
            }

            let va = ffi::PyList_GET_ITEM(values_ptr, a as ffi::Py_ssize_t);
            let vb = ffi::PyList_GET_ITEM(values_ptr, b as ffi::Py_ssize_t);

            let ord = match null_high {
                None => compare_py(py, va, vb, &mut sort_err),
                Some(nh) => {
                    let a_null = va == none_ptr || va == false_ptr;
                    let b_null = vb == none_ptr || vb == false_ptr;
                    match (a_null, b_null) {
                        (true, true) => std::cmp::Ordering::Equal,
                        // null_high=true  → nulls are "high" (sort after non-nulls in ASC)
                        // null_high=false → nulls are "low"  (sort before non-nulls in ASC)
                        (true, false) => {
                            if nh {
                                std::cmp::Ordering::Greater
                            } else {
                                std::cmp::Ordering::Less
                            }
                        }
                        (false, true) => {
                            if nh {
                                std::cmp::Ordering::Less
                            } else {
                                std::cmp::Ordering::Greater
                            }
                        }
                        (false, false) => compare_py(py, va, vb, &mut sort_err),
                    }
                }
            };

            if reverse {
                ord.reverse()
            } else {
                ord
            }
        });
    }

    if let Some(err) = sort_err {
        return Err(err);
    }

    // Build the output tuple: copy IDs from the original tuple in sorted order.
    // SAFETY: result has n pre-allocated slots. PyTuple_GET_ITEM is safe for
    // 0..n.  PyTuple_SET_ITEM steals the reference; we INCREF each id first.
    unsafe {
        let result = ffi::PyTuple_New(n as ffi::Py_ssize_t);
        if result.is_null() {
            return Err(PyErr::fetch(py));
        }
        for (slot, &orig_idx) in indices.iter().enumerate() {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, orig_idx as ffi::Py_ssize_t);
            ffi::Py_INCREF(id_obj);
            ffi::PyTuple_SET_ITEM(result, slot as ffi::Py_ssize_t, id_obj);
        }
        Ok(Bound::from_owned_ptr(py, result)
            .cast_into_unchecked::<PyTuple>()
            .unbind())
    }
}

/// Group record IDs by their corresponding values.
///
/// `batch_group_ids(ids, values) -> dict[value, list[id]]`
///
/// - `ids`: tuple of record IDs
/// - `values`: list of group keys, one per id (same length as ids)
///
/// Returns a plain `dict` mapping each distinct value to the list of IDs
/// that have that value.  Order within each group list is the original
/// order of `ids`.
///
/// Replaces the Python pattern in `grouped()` after `batch_cache_get`:
/// ```text
/// collator = defaultdict(list)
/// for i, rec_id in enumerate(ids):
///     collator[results[i]].append(rec_id)
/// ```
///
/// Uses `PyDict_GetItem` + `PyList_Append` in a tight C loop, eliminating
/// Python loop overhead and `defaultdict.__missing__` dispatch.
#[pyfunction]
pub fn batch_group_ids<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    values: &Bound<'py, PyList>,
) -> PyResult<Py<PyDict>> {
    let n = ids.len() as ffi::Py_ssize_t;

    // SAFETY: All pointers are borrowed from live Python objects.
    // PyDict_GetItem returns a borrowed ref (NULL on miss, no exception set
    // unless the hash fails — we check PyErr_Occurred for that case).
    // PyList_Append INCREFs the appended object internally.
    // PyDict_SetItem INCREFs both key and value — we DECREF our local ref
    // to the new list after SetItem so the dict owns the only reference.
    unsafe {
        let ids_ptr = ids.as_ptr();
        let values_ptr = values.as_ptr();

        let result = ffi::PyDict_New();
        if result.is_null() {
            return Err(PyErr::fetch(py));
        }

        for i in 0..n {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i);
            let val_obj = ffi::PyList_GET_ITEM(values_ptr, i);

            // Try to find the existing group list.
            let existing = ffi::PyDict_GetItem(result, val_obj);
            if !existing.is_null() {
                // Found — append to existing list.
                if ffi::PyList_Append(existing, id_obj) < 0 {
                    ffi::Py_DECREF(result);
                    return Err(PyErr::fetch(py));
                }
            } else {
                // Check for a real error (e.g. unhashable type).
                // PyDict_GetItem sets no exception on a clean miss.
                if !ffi::PyErr_Occurred().is_null() {
                    ffi::Py_DECREF(result);
                    return Err(PyErr::fetch(py));
                }

                // New key — create a fresh list with this first element.
                // Use PyList_New(1) + SET_ITEM to avoid Append's resize path
                // for the common case of small singleton groups.
                let new_list = ffi::PyList_New(1);
                if new_list.is_null() {
                    ffi::Py_DECREF(result);
                    return Err(PyErr::fetch(py));
                }
                // SET_ITEM steals the reference; INCREF first.
                ffi::Py_INCREF(id_obj);
                ffi::PyList_SET_ITEM(new_list, 0, id_obj);

                // Insert into result dict; dict acquires its own reference.
                if ffi::PyDict_SetItem(result, val_obj, new_list) < 0 {
                    ffi::Py_DECREF(new_list);
                    ffi::Py_DECREF(result);
                    return Err(PyErr::fetch(py));
                }
                // Release our local reference — dict holds the only one now.
                ffi::Py_DECREF(new_list);
            }
        }

        Ok(Bound::from_owned_ptr(py, result)
            .cast_into_unchecked::<PyDict>()
            .unbind())
    }
}
