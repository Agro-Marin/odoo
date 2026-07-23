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
//! calls during the sort.
//!
//! The fast path is **decorate-sort-undecorate done in Rust**: each value is
//! extracted *once* into a native Rust key ([`Key`] — `i64` / `f64` / boxed
//! `str`), then the index array is sorted with a pure-Rust comparator.  This is
//! the crucial difference from a naive port: comparing Python objects directly
//! would call `PyObject_RichCompareBool` (up to twice) on every one of the
//! `~n·log n` comparison nodes, and those FFI boundary crossings cost *more*
//! than the N temporary tuples the Python version allocates — so a naive port
//! is actually slower than CPython's Timsort.  Extracting native keys up front
//! turns `2·n·log n` boundary crossings into `n` extractions, after which the
//! sort itself touches no Python objects at all.
//!
//! Anything the native path cannot represent (heterogeneous columns, huge ints
//! that overflow `i64`, exotic types, non-UTF-8 strings) makes [`build_entries`]
//! return `None`, and we fall back to [`sort_objects_to_tuple`] — the
//! object-comparison implementation — which preserves exact Python ordering
//! semantics (including raising the same `TypeError` on incomparable values).
//!
//! [`sort_ids_by_cache`] fuses the cache read into the sort: it reads each value
//! straight from the field-cache dict, so the single-field `sorted()` fast path
//! never materializes an intermediate Python values list.
//!
//! `batch_group_ids` replaces the `defaultdict(list)` loop in `grouped()`:
//!   `for i, rec_id in enumerate(ids): collator[results[i]].append(rec_id)`
//! with a tight C loop using `PyDict_GetItem` + `PyList_Append`, eliminating
//! Python loop overhead and `defaultdict.__missing__` dispatch.

use std::cmp::Ordering;

use pyo3::exceptions::PyValueError;
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{
    PyDate, PyDateAccess, PyDateTime, PyDict, PyFloat, PyInt, PyList, PyString, PyTimeAccess,
    PyTuple,
};

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

    // Materialize owned refs to the values so `Key::Str` can borrow into each
    // PyUnicode buffer (no copy); they stay alive for the whole sort.
    let holder: Vec<Bound<'py, PyAny>> = (0..n)
        .map(|i| values.get_item(i))
        .collect::<PyResult<Vec<_>>>()?;
    sort_holder(py, ids, &holder, reverse, null_high)
}

/// Fused cache-read + sort — the single-field `sorted()` fast path.
///
/// Reads each `field_cache[id]` directly (`PyDict_GetItem`, borrowed) instead of
/// having Python first build an intermediate values list via `batch_cache_values`
/// and hand it back in a second call. Returns:
/// - `Ok(None)` if any id is a cache miss or holds `pending` — the caller then
///   abandons the fast path (exactly as `batch_cache_values` returning `None`);
/// - `Ok(Some(tuple))` with the sorted ids otherwise (native fast path, or the
///   object-comparison fallback for exotic / heterogeneous columns).
#[pyfunction]
#[pyo3(signature = (field_cache, ids, pending, reverse, null_high = None))]
pub fn sort_ids_by_cache<'py>(
    py: Python<'py>,
    field_cache: &Bound<'py, PyDict>,
    ids: &Bound<'py, PyTuple>,
    pending: &Bound<'py, PyAny>,
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Option<Py<PyTuple>>> {
    let n = ids.len();

    // Read all cached values as owned refs; bail (None) on the first miss/pending
    // so the caller falls back to the general record-based sort.
    //
    // SAFETY: cache_ptr/ids_ptr borrowed from live objects with 'py lifetime.
    // PyDict_GetItem returns a borrowed ref (NULL on a clean miss, no exception —
    // ids are always hashable ints). PyTuple_GET_ITEM skips bounds checks (i in
    // 0..n). from_borrowed_ptr INCREFs the value into the holder.
    let holder: Vec<Bound<'py, PyAny>> = unsafe {
        let cache_ptr = field_cache.as_ptr();
        let ids_ptr = ids.as_ptr();
        let pending_ptr = pending.as_ptr();
        let mut holder = Vec::with_capacity(n);
        for i in 0..n {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i as ffi::Py_ssize_t);
            let v = ffi::PyDict_GetItem(cache_ptr, id_obj);
            if v.is_null() || v == pending_ptr {
                return Ok(None);
            }
            holder.push(Bound::from_borrowed_ptr(py, v));
        }
        holder
    };

    if n <= 1 {
        return Ok(Some(ids.clone().unbind()));
    }
    sort_holder(py, ids, &holder, reverse, null_high).map(Some)
}

/// Shared core: decorate the holder values into native keys and sort, falling
/// back to object comparison when a column isn't natively representable.
fn sort_holder<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    holder: &[Bound<'py, PyAny>],
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Py<PyTuple>> {
    let false_ptr = unsafe { ffi::Py_False() };
    match build_entries(holder, null_high.is_some(), false_ptr) {
        Some(entries) => sort_entries_to_tuple(py, ids, &entries, reverse, null_high),
        None => sort_objects_to_tuple(py, ids, holder, reverse, null_high),
    }
}

// ── Native fast path (decorate-sort-undecorate) ────────────────────────────────

/// A native comparison key extracted from a Python cache value.
///
/// `Str` borrows directly into the live `PyUnicode` UTF-8 buffer (no copy) — the
/// borrowed values are kept alive for the whole sort.  `date`/`datetime` are
/// packed into `[year, month, day, hour, minute, second, microsecond]`; the
/// array's lexicographic `Ord` is exactly chronological order (a plain `date`
/// leaves the four time components at 0).
enum Key<'a> {
    Int(i64),
    Float(f64),
    Str(&'a str),
    Date([i32; 7]),
}

/// One decorated slot: a null (None/False, only in null-aware mode) or a value.
enum Entry<'a> {
    Null,
    Val(Key<'a>),
}

/// Total order between two non-null keys.  The column is uniform, so both keys
/// always share a variant; the mismatched arm is unreachable and returns Equal.
#[inline]
fn cmp_key(a: &Key<'_>, b: &Key<'_>) -> Ordering {
    match (a, b) {
        (Key::Int(x), Key::Int(y)) => x.cmp(y),
        // `total_cmp` gives a total order (NaN-safe) so `sort_by` never panics.
        (Key::Float(x), Key::Float(y)) => x.total_cmp(y),
        (Key::Str(x), Key::Str(y)) => x.cmp(y),
        (Key::Date(x), Key::Date(y)) => x.cmp(y),
        _ => Ordering::Equal,
    }
}

/// Order two decorated entries, mirroring `sort_objects_to_tuple`'s null placement.
#[inline]
fn cmp_entries(a: &Entry<'_>, b: &Entry<'_>, null_high: Option<bool>) -> Ordering {
    match (a, b) {
        (Entry::Val(x), Entry::Val(y)) => cmp_key(x, y),
        (Entry::Null, Entry::Null) => Ordering::Equal,
        // null_high=true → nulls sort after non-nulls in ASC; false → before.
        (Entry::Null, Entry::Val(_)) => {
            if matches!(null_high, Some(true)) {
                Ordering::Greater
            } else {
                Ordering::Less
            }
        }
        (Entry::Val(_), Entry::Null) => {
            if matches!(null_high, Some(true)) {
                Ordering::Less
            } else {
                Ordering::Greater
            }
        }
    }
}

/// Build the result tuple by copying IDs from `ids` in `order`.
///
/// SAFETY: every index in `order` is in `0..ids.len()`.  `PyTuple_GET_ITEM`
/// skips bounds checks; `PyTuple_SET_ITEM` steals the reference we INCREF.
fn build_sorted_tuple<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    order: &[usize],
) -> PyResult<Py<PyTuple>> {
    let ids_ptr = ids.as_ptr();
    unsafe {
        let result = ffi::PyTuple_New(order.len() as ffi::Py_ssize_t);
        if result.is_null() {
            return Err(PyErr::fetch(py));
        }
        for (slot, &orig_idx) in order.iter().enumerate() {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, orig_idx as ffi::Py_ssize_t);
            ffi::Py_INCREF(id_obj);
            ffi::PyTuple_SET_ITEM(result, slot as ffi::Py_ssize_t, id_obj);
        }
        Ok(Bound::from_owned_ptr(py, result)
            .cast_into_unchecked::<PyTuple>()
            .unbind())
    }
}

/// Decorate each holder value into a native [`Entry`].
///
/// Returns `None` to signal the column can't be represented natively (mixed
/// types, `i64` overflow, non-UTF-8 string, NaN float, or an unknown type) — the
/// caller then uses the object-comparison fallback. `Key::Str` borrows into the
/// holder's live `PyUnicode` buffers, so the result borrows `holder`.
fn build_entries<'a>(
    holder: &'a [Bound<'_, PyAny>],
    null_aware: bool,
    false_ptr: *mut ffi::PyObject,
) -> Option<Vec<Entry<'a>>> {
    let mut entries: Vec<Entry<'a>> = Vec::with_capacity(holder.len());
    // Column kind tag (1=int, 2=float, 3=str, 4=date/datetime) for uniformity.
    let mut kind: u8 = 0;

    for v in holder {
        // In null-aware mode None/False are nulls, never compared as values.
        // (When null_high is None the caller guarantees no None/False present.)
        if null_aware && (v.is_none() || v.as_ptr() == false_ptr) {
            entries.push(Entry::Null);
            continue;
        }

        let (k, key) = if let Ok(s) = v.cast::<PyString>() {
            match s.to_str() {
                Ok(st) => (3, Key::Str(st)),
                Err(_) => return None, // non-UTF-8 (lone surrogate) → FFI
            }
        } else if let Ok(f) = v.cast::<PyFloat>() {
            let fv = f.value();
            // NaN: Python's `<`/`>` are both false, giving order-dependent
            // results that `total_cmp` can't reproduce — defer to FFI.
            if fv.is_nan() {
                return None;
            }
            // Normalize -0.0 → 0.0: Python treats them as equal (a tie), but
            // `total_cmp` would order -0.0 before +0.0 and reshuffle the tie.
            (2, Key::Float(if fv == 0.0 { 0.0 } else { fv }))
        } else if let Ok(iobj) = v.cast::<PyInt>() {
            match iobj.extract::<i64>() {
                Ok(iv) => (1, Key::Int(iv)),
                Err(_) => return None, // > i64 → FFI
            }
        } else if let Ok(dt) = v.cast::<PyDateTime>() {
            // Check datetime before date: datetime is a subclass of date, so a
            // `PyDate` cast would also succeed and drop the time components.
            (
                4,
                Key::Date([
                    dt.get_year(),
                    dt.get_month() as i32,
                    dt.get_day() as i32,
                    dt.get_hour() as i32,
                    dt.get_minute() as i32,
                    dt.get_second() as i32,
                    dt.get_microsecond() as i32,
                ]),
            )
        } else if let Ok(d) = v.cast::<PyDate>() {
            (
                4,
                Key::Date([
                    d.get_year(),
                    d.get_month() as i32,
                    d.get_day() as i32,
                    0,
                    0,
                    0,
                    0,
                ]),
            )
        } else {
            return None; // unknown type → FFI (preserves Python semantics)
        };

        if kind == 0 {
            kind = k;
        } else if kind != k {
            return None; // mixed types in one column → FFI (matches Python)
        }
        entries.push(Entry::Val(key));
    }

    Some(entries)
}

/// Sort an index array by native keys, then build the result tuple.
///
/// `sort_by` is stable, so equal keys keep the original ID order — matching
/// CPython's stable sort (and its `reverse` semantics).
fn sort_entries_to_tuple<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    entries: &[Entry<'_>],
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Py<PyTuple>> {
    let mut indices: Vec<usize> = (0..entries.len()).collect();
    indices.sort_by(|&a, &b| {
        let ord = cmp_entries(&entries[a], &entries[b], null_high);
        if reverse { ord.reverse() } else { ord }
    });
    build_sorted_tuple(py, ids, &indices)
}

// ── Object-comparison fallback ─────────────────────────────────────────────────

/// Sort by comparing the Python objects directly (one `PyObject_RichCompareBool`
/// per node).  Used when [`build_entries`] cannot extract native keys; it
/// preserves exact Python ordering, including raising `TypeError` on values that
/// are not mutually comparable.
fn sort_objects_to_tuple<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    holder: &[Bound<'py, PyAny>],
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Py<PyTuple>> {
    // Build index array [0, 1, ..., n-1] and sort it by holder[i].
    // `sort_by` is a stable sort (like Python's Timsort), so equal values
    // preserve the original relative order of their IDs.
    let mut indices: Vec<usize> = (0..holder.len()).collect();
    let mut sort_err: Option<PyErr> = None;

    // SAFETY: each holder[i] is a live Bound; as_ptr() is a valid borrowed
    // pointer. PyObject_RichCompareBool is safe to call with the GIL held.
    unsafe {
        let none_ptr = ffi::Py_None();
        let false_ptr = ffi::Py_False();

        indices.sort_by(|&a, &b| {
            if sort_err.is_some() {
                return Ordering::Equal;
            }

            let va = holder[a].as_ptr();
            let vb = holder[b].as_ptr();

            let ord = match null_high {
                None => compare_py(py, va, vb, &mut sort_err),
                Some(nh) => {
                    let a_null = va == none_ptr || va == false_ptr;
                    let b_null = vb == none_ptr || vb == false_ptr;
                    match (a_null, b_null) {
                        (true, true) => Ordering::Equal,
                        // null_high=true  → nulls are "high" (sort after non-nulls in ASC)
                        // null_high=false → nulls are "low"  (sort before non-nulls in ASC)
                        (true, false) => {
                            if nh {
                                Ordering::Greater
                            } else {
                                Ordering::Less
                            }
                        }
                        (false, true) => {
                            if nh {
                                Ordering::Less
                            } else {
                                Ordering::Greater
                            }
                        }
                        (false, false) => compare_py(py, va, vb, &mut sort_err),
                    }
                }
            };

            if reverse { ord.reverse() } else { ord }
        });
    }

    if let Some(err) = sort_err {
        return Err(err);
    }

    build_sorted_tuple(py, ids, &indices)
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
    // Bounds contract: the loop indexes `values[i]` for i in 0..ids.len() with
    // the unchecked PyList_GET_ITEM.  Validate the lengths match up front — a
    // shorter `values` would otherwise read out of bounds and segfault the
    // worker (the Python fallback raises here too).
    if values.len() != ids.len() {
        return Err(PyValueError::new_err(
            "batch_group_ids: `values` must have the same length as `ids`",
        ));
    }
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

#[cfg(test)]
mod tests {
    //! Pure-Rust tests for the native comparison helpers. The full
    //! `sort_ids_by_values` path takes Python objects and is covered by
    //! Python-level tests (including a fuzz comparison against the pure-Python
    //! fallback); here we pin the ordering logic that decides the result.
    use super::{Entry, Key, cmp_entries, cmp_key};
    use std::cmp::Ordering;

    #[test]
    fn cmp_key_orders_each_variant() {
        assert_eq!(cmp_key(&Key::Int(1), &Key::Int(2)), Ordering::Less);
        assert_eq!(cmp_key(&Key::Int(2), &Key::Int(2)), Ordering::Equal);
        assert_eq!(
            cmp_key(&Key::Float(2.0), &Key::Float(1.5)),
            Ordering::Greater
        );
        assert_eq!(cmp_key(&Key::Str("abc"), &Key::Str("abd")), Ordering::Less);
        // Date keys compare component-wise (chronologically).
        assert_eq!(
            cmp_key(
                &Key::Date([2026, 6, 28, 0, 0, 0, 0]),
                &Key::Date([2026, 12, 1, 0, 0, 0, 0])
            ),
            Ordering::Less
        );
    }

    #[test]
    fn cmp_key_float_is_nan_safe() {
        // total_cmp gives a deterministic total order (no panic) for NaN.
        let _ = cmp_key(&Key::Float(f64::NAN), &Key::Float(1.0));
        assert_eq!(cmp_key(&Key::Float(1.0), &Key::Float(1.0)), Ordering::Equal);
    }

    #[test]
    fn cmp_entries_places_nulls_per_null_high() {
        let null = Entry::Null;
        let val = Entry::Val(Key::Int(5));

        // null_high=true → null sorts after the value (Greater) in ascending order
        assert_eq!(cmp_entries(&null, &val, Some(true)), Ordering::Greater);
        assert_eq!(cmp_entries(&val, &null, Some(true)), Ordering::Less);

        // null_high=false → null sorts before the value (Less)
        assert_eq!(cmp_entries(&null, &val, Some(false)), Ordering::Less);
        assert_eq!(cmp_entries(&val, &null, Some(false)), Ordering::Greater);

        // two nulls are equal (stable sort then preserves their original order)
        assert_eq!(cmp_entries(&null, &null, Some(true)), Ordering::Equal);
    }

    #[test]
    fn cmp_entries_compares_two_values_by_key() {
        let a = Entry::Val(Key::Int(1));
        let b = Entry::Val(Key::Int(2));
        assert_eq!(cmp_entries(&a, &b, None), Ordering::Less);
        assert_eq!(cmp_entries(&b, &a, None), Ordering::Greater);
    }
}
