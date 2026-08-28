//! Rust/PyO3 accelerator for Odoo ORM field cache access hot paths.
//!
//! Uses raw CPython C-API (`pyo3::ffi`) internally to minimize per-operation
//! overhead.  The semantic reference is `odoo/libs/_field_access/_fallback.py`
//! — a pure-Python implementation of every function here that the Python test
//! suite runs the *same* assertions against, so the two cannot drift unnoticed.
//! Rust-side `_safe` twins were kept for that job once and could not do it:
//! nothing called them, so nothing compared them, and `clone_inner_safe` had
//! silently acquired different subclass semantics from the function it
//! documented.
//!
//! Design invariants:
//! - Sentinel comparison uses pointer identity (`==`), NOT Python `__eq__`.
//! - `PyDict_GetItem` returns borrowed refs — no refcount on lookup.
//! - `PyTuple_GET_ITEM` skips bounds checks — caller guarantees valid indices.
//! - The functions work with raw Python dicts — no Odoo imports in Rust.
//!
//! Python 3.14 notes:
//! - `PyDict_GetItem` returns borrowed refs and is safe under the GIL, which
//!   is the only reason the `Py_INCREF` a few instructions later is sound: no
//!   other thread can replace the dict entry and free the object in between.
//!   Free-threaded builds need `PyDict_GetItemRef` (strong refs) on every one
//!   of these paths — `batch_group_ids` already took that change — plus an
//!   audit of the remaining borrows. Until then the module declares
//!   `gil_used = true` (see `lib.rs`), which is what keeps a free-threaded
//!   interpreter from running these concurrently.

use std::ptr::NonNull;

use pyo3::exceptions::PyValueError;
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString, PyTuple};

// ── Helpers ──────────────────────────────────────────────────────────────────

/// Probe the field cache for one record id.
///
/// Returns the cached value, or `None` when it is not usable. "Not usable" is
/// one rule with two spellings — the id is absent, or it holds the `PENDING`
/// sentinel — and it is the branch every function in this module turns on, as
/// well as every one of their counterparts in `_fallback.py`. Stating it once
/// is the point: the four copies that used to spell it out could disagree, and
/// nothing would have compared them.
///
/// Returns a **borrowed** pointer. `PyDict_GetItem` is the right primitive
/// here, not `PyDict_GetItemRef`: its hazard is that it swallows an exception
/// raised while hashing the key, and these keys are record ids — `int`, always
/// hashable, never able to raise. Skipping the strong reference keeps the hot
/// path free of refcount traffic. `batch_group_ids` in `sort.rs` looks the same
/// and is not: its keys are arbitrary cached *values*, so it uses
/// `PyDict_GetItemRef` and pays for it.
///
/// `Option<NonNull<_>>`, which is pointer-sized — a bare `*mut` has no niche,
/// so `Option<*mut _>` would carry a tag word. Three shapes were measured on
/// `batch_cache_filter` over a half-missing cache, against the four
/// hand-written copies this replaced: `Option<*mut>` testing the sentinel first
/// +6%, a raw `*mut` return +7%, and this one **+3.7% on the miss path with
/// the hit paths at parity** (five interleaved runs, half-missing cache). The
/// residual is real and it is the price of stating the rule once; it is also
/// about half a nanosecond per missing id, on a path whose next act is a
/// database fetch. Do not "simplify" this to a raw pointer, or reorder the two
/// tests below, without re-measuring — both were tried and both were worse.
///
/// SAFETY: `cache` must be a valid `PyDict *`, `id_obj` and `pending` valid
/// object pointers, with the GIL held. The returned pointer is valid only
/// until the cache is next mutated.
#[inline]
unsafe fn cache_probe(
    cache: *mut ffi::PyObject,
    id_obj: *mut ffi::PyObject,
    pending: *mut ffi::PyObject,
) -> Option<NonNull<ffi::PyObject>> {
    // Null FIRST, then the sentinel — the order the four hand-written copies
    // used, and it is load-bearing. A miss is the common case here and a null
    // pointer settles it in one compare; testing `pending` first makes every
    // miss pay two, which measured as a consistent 4-6% on
    // `batch_cache_filter` over a half-missing cache.
    let value = NonNull::new(unsafe { ffi::PyDict_GetItem(cache, id_obj) })?;
    if value.as_ptr() == pending {
        None
    } else {
        Some(value)
    }
}

// ── Public functions ──────────────────────────────────────────────────────────

/// Batch cache lookup for `mapped()` and `grouped()` identity-type fast paths.
///
/// For each id in `ids`, looks up `field_cache[id]`:
/// - Cache hit (not `pending`): appends value (or `none_val` if value is None).
/// - Cache miss or `pending`: appends `none_val` placeholder, records index.
///
/// Returns `(results: list, miss_indices: list[int])`.
#[pyfunction]
pub fn batch_cache_get<'py>(
    py: Python<'py>,
    field_cache: &Bound<'py, PyDict>,
    ids: &Bound<'py, PyTuple>,
    pending: &Bound<'py, PyAny>,
    none_val: &Bound<'py, PyAny>,
) -> PyResult<(Py<PyList>, Py<PyList>)> {
    let n = ids.len() as ffi::Py_ssize_t;

    // SAFETY: All pointers are borrowed from live Python objects with 'py
    // lifetime.  PyDict_GetItem returns borrowed refs (no refcount on lookup).
    // PyList_SET_ITEM steals one owned reference per slot.
    // ffi::Py_None() returns a borrowed pointer to the immortal None singleton
    // — no INCREF needed, avoids the INCREF/DECREF pair from py.None().
    unsafe {
        let cache_ptr = field_cache.as_ptr();
        let ids_ptr = ids.as_ptr();
        let pending_ptr = pending.as_ptr();
        let none_val_ptr = none_val.as_ptr();
        let none_ptr = ffi::Py_None();

        let result = ffi::PyList_New(n);
        if result.is_null() {
            return Err(PyErr::fetch(py));
        }

        let mut miss_items: Vec<ffi::Py_ssize_t> = Vec::new();

        for i in 0..n {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i);
            let Some(value) = cache_probe(cache_ptr, id_obj, pending_ptr) else {
                // Cache miss or PENDING sentinel
                ffi::Py_INCREF(none_val_ptr);
                ffi::PyList_SET_ITEM(result, i, none_val_ptr);
                miss_items.push(i);
                continue;
            };
            let value = value.as_ptr();
            if value == none_ptr {
                // Cache hit but value is None — substitute none_val
                ffi::Py_INCREF(none_val_ptr);
                ffi::PyList_SET_ITEM(result, i, none_val_ptr);
            } else {
                // Cache hit with real value
                ffi::Py_INCREF(value);
                ffi::PyList_SET_ITEM(result, i, value);
            }
        }

        // The results list is the hot output and stays hand-built; the miss
        // list is empty on the path that matters (every id cached), so it is
        // built with the checked API. The hand-rolled version needed a helper
        // that took over cleanup of BOTH half-built lists through an
        // `extra_decref` out-parameter — an ownership contract spread across
        // three call sites, to save an allocation on a list that is usually
        // length zero.
        let result = Bound::from_owned_ptr(py, result).cast_into_unchecked::<PyList>();
        Ok((result.unbind(), PyList::new(py, &miss_items)?.unbind()))
    }
}

/// Batch cache truthiness filter for `filtered()` field-name fast path.
///
/// For each id in `ids`, looks up `field_cache[id]`:
/// - Cache hit, not `pending`, truthy: appends id to passing list.
/// - Cache miss or `pending`: records index in miss list.
/// - Cache hit but falsy: skipped (not a miss either).
///
/// Returns `(passing_ids: list, miss_indices: list[int])`.
#[pyfunction]
pub fn batch_cache_filter<'py>(
    py: Python<'py>,
    field_cache: &Bound<'py, PyDict>,
    ids: &Bound<'py, PyTuple>,
    pending: &Bound<'py, PyAny>,
) -> PyResult<(Py<PyList>, Py<PyList>)> {
    let n = ids.len() as ffi::Py_ssize_t;

    // SAFETY: Same as batch_cache_get.  PyObject_IsTrue can call __bool__
    // but Odoo field values are immutable types (int/str/bool/float) whose
    // truthiness check is a pure C-level operation with no side effects.
    unsafe {
        let cache_ptr = field_cache.as_ptr();
        let ids_ptr = ids.as_ptr();
        let pending_ptr = pending.as_ptr();

        // Collect into Vecs first — no cleanup needed on error since
        // all pointers are borrowed (no INCREF yet).
        let mut passing: Vec<*mut ffi::PyObject> = Vec::new();
        let mut miss_items: Vec<ffi::Py_ssize_t> = Vec::new();

        for i in 0..n {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i);
            match cache_probe(cache_ptr, id_obj, pending_ptr) {
                None => miss_items.push(i),
                Some(value) => {
                    let truthy = ffi::PyObject_IsTrue(value.as_ptr());
                    if truthy < 0 {
                        return Err(PyErr::fetch(py));
                    }
                    if truthy == 1 {
                        passing.push(id_obj);
                    }
                    // falsy (truthy == 0): neither pass nor miss
                }
            }
        }

        // Build passing list
        let pass_n = passing.len() as ffi::Py_ssize_t;
        let pass_list = ffi::PyList_New(pass_n);
        if pass_list.is_null() {
            return Err(PyErr::fetch(py));
        }
        for (j, &id_ptr) in passing.iter().enumerate() {
            ffi::Py_INCREF(id_ptr);
            ffi::PyList_SET_ITEM(pass_list, j as ffi::Py_ssize_t, id_ptr);
        }

        // See `batch_cache_get`: the passing list is the hot output, the miss
        // list is normally empty.
        let pass_list = Bound::from_owned_ptr(py, pass_list).cast_into_unchecked::<PyList>();
        Ok((pass_list.unbind(), PyList::new(py, &miss_items)?.unbind()))
    }
}

/// All-or-nothing batch cache extraction for `sorted()` fast path.
///
/// For each id in `ids`, looks up `field_cache[id]`:
/// - Cache hit (not `pending`): collects the raw value.
/// - Cache miss or `pending`: **immediately returns `None`** (early bailout).
///
/// Returns `Some(list)` with all cached values, or `None` on any miss.
/// This is the optimal pattern for `_sorted_by_ids` which needs all values
/// present to sort — a single miss means fallback to the record-based path.
#[pyfunction]
pub fn batch_cache_values<'py>(
    py: Python<'py>,
    field_cache: &Bound<'py, PyDict>,
    ids: &Bound<'py, PyTuple>,
    pending: &Bound<'py, PyAny>,
) -> PyResult<Option<Py<PyList>>> {
    let n = ids.len() as ffi::Py_ssize_t;

    // SAFETY: PyList_New initializes all slots to NULL.  On early bailout,
    // Py_DECREF on the list correctly DECREFs filled slots (0..i) and
    // skips NULL slots (i..n).
    unsafe {
        let cache_ptr = field_cache.as_ptr();
        let ids_ptr = ids.as_ptr();
        let pending_ptr = pending.as_ptr();

        let result = ffi::PyList_New(n);
        if result.is_null() {
            return Err(PyErr::fetch(py));
        }

        for i in 0..n {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i);
            let Some(value) = cache_probe(cache_ptr, id_obj, pending_ptr) else {
                // Miss or PENDING — bail.  Slots 0..i are owned,
                // slots i..n are NULL.  Py_DECREF handles cleanup.
                ffi::Py_DECREF(result);
                return Ok(None);
            };
            let value = value.as_ptr();

            ffi::Py_INCREF(value);
            ffi::PyList_SET_ITEM(result, i, value);
        }

        Ok(Some(
            Bound::from_owned_ptr(py, result)
                .cast_into_unchecked::<PyList>()
                .unbind(),
        ))
    }
}

/// Batch cache fill for `_read_format()` scalar stored-field fast path.
///
/// For each index `i` in `0..len(ids)`:
/// - If `results[i]` is falsy (an empty dict = cleared = missing record): skip.
/// - Look up `ids[i]` in `field_cache`:
///   - Hit, not `pending`, not `None`: `results[i][name] = value`
///   - Hit, not `pending`, is `None`: `results[i][name] = none_val`
///   - Miss or `pending`: record index `i` for fallback
///
/// Returns `list[int]` of miss indices needing `Field.__get__` fallback.
///
/// Eliminates the Python `for id_, vals in zip(ids, results)` loop for the
/// common all-cached case, which is the hot path on every `read()` call.
#[pyfunction]
pub fn batch_cache_fill<'py>(
    py: Python<'py>,
    field_cache: &Bound<'py, PyDict>,
    ids: &Bound<'py, PyTuple>,
    results: &Bound<'py, PyList>,
    name: &Bound<'py, PyString>,
    pending: &Bound<'py, PyAny>,
    none_val: &Bound<'py, PyAny>,
) -> PyResult<Py<PyList>> {
    // Bounds contract: the loop indexes `results[i]` for i in 0..ids.len() with
    // the unchecked PyList_GET_ITEM.  Enforce the length invariant rather than
    // trusting the caller — a shorter `results` would read out of bounds.
    if results.len() != ids.len() {
        return Err(PyValueError::new_err(
            "batch_cache_fill: `results` must have the same length as `ids`",
        ));
    }
    let n = ids.len() as ffi::Py_ssize_t;

    // SAFETY: All pointers are borrowed from live Python objects with 'py
    // lifetime.  PyDict_GetItem returns borrowed refs (no refcount on lookup).
    // PyDict_SetItem INCREFs both key and value — no manual INCREF needed
    // before the call.  PyList_GET_ITEM is safe because the length guard above
    // pins results.len() == ids.len() = n.
    unsafe {
        let cache_ptr = field_cache.as_ptr();
        let ids_ptr = ids.as_ptr();
        let results_ptr = results.as_ptr();
        let name_ptr = name.as_ptr();
        let pending_ptr = pending.as_ptr();
        let none_val_ptr = none_val.as_ptr();
        let none_ptr = ffi::Py_None();

        let mut miss_items: Vec<ffi::Py_ssize_t> = Vec::new();

        for i in 0..n {
            // Re-checked every iteration, not hoisted: the generic lane below
            // runs `PyObject_IsTrue` and `PyObject_SetItem`, both of which can
            // dispatch to Python (`__bool__`, `__len__`, `__setitem__`) and so
            // can shrink `results` under us. `PyList_GET_ITEM` does not bounds
            // check, so the next iteration would read past the end. The load
            // is one compare against a length already in cache — measured at
            // the noise floor of a function that costs ~53ns per element.
            if ffi::PyList_GET_SIZE(results_ptr) != n {
                return Err(PyValueError::new_err(
                    "batch_cache_fill: `results` changed length during the fill",
                ));
            }
            let vals_ptr = ffi::PyList_GET_ITEM(results_ptr, i);

            // `results` holds plain dicts on every path the ORM takes, so that
            // is the fast lane: one pointer compare, then a size read and a
            // `PyDict_SetItem` that skip the abstract-object machinery.
            //
            // Anything else takes the generic lane rather than being skipped.
            // Skipping is what this did before, and the failure mode was
            // silent: a `dict` subclass came back WITHOUT the field and
            // WITHOUT its index in the miss list, so the caller would report a
            // record that simply had no value for it, while the Python
            // reference filled it; a non-mapping returned success where the
            // reference raises `TypeError`.
            //
            // No caller can reach that today — `_read_format` builds
            // `results` as `[{"id": id_} for id_ in ids]`, plain dicts every
            // time, and clears them with `.clear()` rather than replacing
            // them. This is the contract agreeing with its own reference
            // implementation, not a live bug being fixed. It is worth the two
            // extra branches anyway: the accelerated and pure-Python halves of
            // `_field_access` are held to the *same* assertions by the test
            // suite, and a divergence that no test can express is one the
            // suite silently stops checking.
            let exact = ffi::PyDict_CheckExact(vals_ptr) != 0;
            let empty = if exact {
                ffi::PyDict_Size(vals_ptr) == 0
            } else {
                // Mirrors the reference's `if not vals: continue`.
                match ffi::PyObject_IsTrue(vals_ptr) {
                    -1 => return Err(PyErr::fetch(py)),
                    truthy => truthy == 0,
                }
            };
            if empty {
                continue;
            }

            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i);
            let Some(value) = cache_probe(cache_ptr, id_obj, pending_ptr) else {
                // Cache miss or PENDING — needs Field.__get__ fallback
                miss_items.push(i);
                continue;
            };
            let value = value.as_ptr();

            // Cache hit — write into the result dict.
            // Both setters INCREF key and value; no manual INCREF needed.
            let write_val = if value == none_ptr {
                none_val_ptr
            } else {
                value
            };
            let stored = if exact {
                ffi::PyDict_SetItem(vals_ptr, name_ptr, write_val)
            } else {
                // Raises TypeError for a non-mapping, exactly as the
                // reference's `vals[name] = value` does.
                ffi::PyObject_SetItem(vals_ptr, name_ptr, write_val)
            };
            if stored < 0 {
                return Err(PyErr::fetch(py));
            }
        }

        Ok(PyList::new(py, &miss_items)?.unbind())
    }
}
