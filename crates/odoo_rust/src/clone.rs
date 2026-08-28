//! Fast deep-clone for JSON-like Python objects using raw CPython C-API.
//!
//! Replaces `copy.deepcopy` for JSON-like data (dict/list/tuple of scalars).
//! Uses `_PyDict_NewPresized` + `PyDict_Next` for zero-resize dict cloning,
//! and `PyList_SET_ITEM` / `PyTuple_SET_ITEM` for direct slot writes.
//!
//! The Rust version is faster because:
//! - `_PyDict_NewPresized` pre-allocates the hash table (no resizes)
//! - `PyDict_Next` iterates the internal array directly (no iterator object)
//! - `PyList_SET_ITEM` writes slots directly (no bounds check, steals ref)
//! - Type dispatch via a single type-flag test (`PyDict_Check` et al.)
//! - No Python function-call overhead per recursion level
//!
//! # What is copied and what is shared
//!
//! Dicts, lists and tuples are rebuilt — **including subclasses**, which are
//! normalized to the plain builtin type.
//!
//! Handling subclasses at all is not hypothetical hardening. While the
//! dispatch used `CheckExact` a subclass matched no container branch and fell
//! through to the share-by-reference tail, so the "clone" returned the
//! caller's own object — and `Properties.convert_to_cache` reaches here with
//! whatever `isinstance(value, dict)` accepted, handed straight back by
//! `_recordsets_to_ids` when it holds no recordset. Writing an `OrderedDict`
//! to a Properties field therefore put the caller's live mapping in the field
//! cache, and mutating that mapping afterwards rewrote the record with nothing
//! raised. `PropertiesCallerIsolationCase` in `test_orm` is that path, and it
//! fails against a build without this.
//!
//! Normalizing the type rather than preserving it is deliberate: what the
//! callers buy is isolation, not type fidelity, and reconstructing the exact
//! class would mean calling back into Python for its constructor — which no
//! caller needs and every caller would pay for. The visible cost is that a
//! `namedtuple` comes back as a plain tuple; JSON and Properties values cannot
//! contain one.
//!
//! Everything else is shared by reference. For the immutable leaves this
//! clone exists for (str/int/float/bool/None) that is free and invisible.
//! It also means a **mutable non-container leaf is aliased, not copied** — a
//! `set` or `bytearray` reached through a cloned dict is the original object.
//! JSON and Properties values cannot hold one (both round-trip through
//! `orjson` before reaching here), which is why this is a documented boundary
//! rather than a supported case.
//!
//! Aliasing *between* slots is not preserved either: `copy.deepcopy` memoizes,
//! so a substructure reachable twice stays one object in the copy, while this
//! clone duplicates it. For a tree — which JSON is — the two agree.

use pyo3::ffi;
use pyo3::prelude::*;

use crate::ffi_ext::_PyDict_NewPresized;

/// Maximum container nesting `clone_inner` will follow before refusing.
///
/// Unlike `copy.deepcopy`, this clone keeps no `memo`, so a *cyclic* structure
/// (a dict that contains itself — reachable because Json/Properties field
/// values come from addon-writable data) would recurse until the native stack
/// overflows and the interpreter **segfaults**, not raises. A finite cap turns
/// that into a `RecursionError`. 500 is far deeper than any legitimate JSON /
/// Properties blob (which nest a handful of levels) yet well below the frame
/// count that would exhaust an 8 MB stack, so it fails safe on both cycles and
/// pathologically deep input without rejecting real data.
const MAX_CLONE_DEPTH: usize = 500;

/// Deep-clone a JSON-like Python object (dict/list/tuple of scalars).
///
/// Dicts, lists, and tuples are recursively copied.  All other values
/// (str, int, float, bool, None) are shared by reference (zero-copy).
#[pyfunction]
pub fn fast_clone<'py>(obj: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let py = obj.py();
    unsafe { Ok(Bound::from_owned_ptr(py, clone_inner(py, obj.as_ptr(), 0)?)) }
}

/// Recursive deep-clone using raw CPython C-API.
///
/// SAFETY: `obj` must be a valid Python object with the GIL held.
/// Returns a new (owned) reference.  On error, all partially-constructed
/// containers are cleaned up before returning.
unsafe fn clone_inner(
    py: Python<'_>,
    obj: *mut ffi::PyObject,
    depth: usize,
) -> PyResult<*mut ffi::PyObject> {
    if depth >= MAX_CLONE_DEPTH {
        return Err(pyo3::exceptions::PyRecursionError::new_err(
            "fast_clone: maximum nesting depth exceeded (cyclic or too-deep structure)",
        ));
    }
    unsafe {
        // Dict — most common container in Odoo JSON blobs.
        // `PyDict_Check` is a `Py_TPFLAGS_DICT_SUBCLASS` flag test, so taking
        // subclasses too costs nothing; `PyDict_Next` walks the concrete
        // storage a subclass shares with `dict`, ignoring any Python-level
        // `keys`/`__iter__` override. The result is a plain dict (see above).
        if ffi::PyDict_Check(obj) != 0 {
            let size = ffi::PyDict_Size(obj);
            let new_dict = _PyDict_NewPresized(size);
            if new_dict.is_null() {
                return Err(PyErr::fetch(py));
            }

            // PyDict_Next iterates the internal hash table directly —
            // no iterator object created, borrowed key/val refs.
            let mut pos: ffi::Py_ssize_t = 0;
            let mut key: *mut ffi::PyObject = std::ptr::null_mut();
            let mut val: *mut ffi::PyObject = std::ptr::null_mut();

            while ffi::PyDict_Next(obj, &mut pos, &mut key, &mut val) != 0 {
                let cloned_val = match clone_inner(py, val, depth + 1) {
                    Ok(v) => v,
                    Err(e) => {
                        ffi::Py_DECREF(new_dict);
                        return Err(e);
                    }
                };
                // PyDict_SetItem INCREFs both key and value
                if ffi::PyDict_SetItem(new_dict, key, cloned_val) < 0 {
                    ffi::Py_DECREF(cloned_val);
                    ffi::Py_DECREF(new_dict);
                    return Err(PyErr::fetch(py));
                }
                // SetItem INCREFed cloned_val, release our reference
                ffi::Py_DECREF(cloned_val);
            }

            return Ok(new_dict);
        }

        // List — second most common (JSON arrays, One2many values).
        if ffi::PyList_Check(obj) != 0 {
            let n = ffi::PyList_GET_SIZE(obj);
            let new_list = ffi::PyList_New(n);
            if new_list.is_null() {
                return Err(PyErr::fetch(py));
            }

            for i in 0..n {
                let item = ffi::PyList_GET_ITEM(obj, i);
                let cloned = match clone_inner(py, item, depth + 1) {
                    Ok(v) => v,
                    Err(e) => {
                        // Slots 0..i owned, i..n NULL — Py_DECREF handles it
                        ffi::Py_DECREF(new_list);
                        return Err(e);
                    }
                };
                // PyList_SET_ITEM steals the reference
                ffi::PyList_SET_ITEM(new_list, i, cloned);
            }

            return Ok(new_list);
        }

        // Tuple — rare in JSON data, and immutable, but still rebuilt: a
        // tuple's *elements* can be mutable dicts that the caller must not
        // share with the cache.
        if ffi::PyTuple_Check(obj) != 0 {
            let n = ffi::PyTuple_GET_SIZE(obj);
            let new_tuple = ffi::PyTuple_New(n);
            if new_tuple.is_null() {
                return Err(PyErr::fetch(py));
            }

            for i in 0..n {
                let item = ffi::PyTuple_GET_ITEM(obj, i);
                let cloned = match clone_inner(py, item, depth + 1) {
                    Ok(v) => v,
                    Err(e) => {
                        ffi::Py_DECREF(new_tuple);
                        return Err(e);
                    }
                };
                // PyTuple_SET_ITEM steals the reference
                ffi::PyTuple_SET_ITEM(new_tuple, i, cloned);
            }

            return Ok(new_tuple);
        }

        // Leaf — anything that is not a dict/list/tuple. Shared by reference;
        // see the module docs for why that is safe here and where it is not.
        ffi::Py_INCREF(obj);
        Ok(obj)
    }
}
