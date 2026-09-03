use std::ptr::NonNull;

use pyo3::exceptions::PyValueError;
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString, PyTuple};

#[inline]
pub(crate) unsafe fn cache_probe(
    cache: *mut ffi::PyObject,
    id_obj: *mut ffi::PyObject,
    pending: *mut ffi::PyObject,
) -> Option<NonNull<ffi::PyObject>> {
    let value = NonNull::new(unsafe { ffi::PyDict_GetItem(cache, id_obj) })?;
    if value.as_ptr() == pending {
        None
    } else {
        Some(value)
    }
}

#[pyfunction]
pub fn batch_cache_get<'py>(
    py: Python<'py>,
    field_cache: &Bound<'py, PyDict>,
    ids: &Bound<'py, PyTuple>,
    pending: &Bound<'py, PyAny>,
    none_val: &Bound<'py, PyAny>,
) -> PyResult<(Py<PyList>, Py<PyList>)> {
    let n = ids.len() as ffi::Py_ssize_t;

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
                ffi::Py_INCREF(none_val_ptr);
                ffi::PyList_SET_ITEM(result, i, none_val_ptr);
                miss_items.push(i);
                continue;
            };
            let value = value.as_ptr();
            if value == none_ptr {
                ffi::Py_INCREF(none_val_ptr);
                ffi::PyList_SET_ITEM(result, i, none_val_ptr);
            } else {
                ffi::Py_INCREF(value);
                ffi::PyList_SET_ITEM(result, i, value);
            }
        }

        let result = Bound::from_owned_ptr(py, result).cast_into_unchecked::<PyList>();
        Ok((result.unbind(), PyList::new(py, &miss_items)?.unbind()))
    }
}

#[pyfunction]
pub fn batch_cache_filter<'py>(
    py: Python<'py>,
    field_cache: &Bound<'py, PyDict>,
    ids: &Bound<'py, PyTuple>,
    pending: &Bound<'py, PyAny>,
) -> PyResult<(Py<PyList>, Py<PyList>)> {
    let n = ids.len() as ffi::Py_ssize_t;

    unsafe {
        let cache_ptr = field_cache.as_ptr();
        let ids_ptr = ids.as_ptr();
        let pending_ptr = pending.as_ptr();

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
                }
            }
        }

        let pass_n = passing.len() as ffi::Py_ssize_t;
        let pass_list = ffi::PyList_New(pass_n);
        if pass_list.is_null() {
            return Err(PyErr::fetch(py));
        }
        for (j, &id_ptr) in passing.iter().enumerate() {
            ffi::Py_INCREF(id_ptr);
            ffi::PyList_SET_ITEM(pass_list, j as ffi::Py_ssize_t, id_ptr);
        }

        let pass_list = Bound::from_owned_ptr(py, pass_list).cast_into_unchecked::<PyList>();
        Ok((pass_list.unbind(), PyList::new(py, &miss_items)?.unbind()))
    }
}

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
    if results.len() != ids.len() {
        return Err(PyValueError::new_err(
            "batch_cache_fill: `results` must have the same length as `ids`",
        ));
    }
    let n = ids.len() as ffi::Py_ssize_t;

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
            if ffi::PyList_GET_SIZE(results_ptr) != n {
                return Err(PyValueError::new_err(
                    "batch_cache_fill: `results` changed length during the fill",
                ));
            }
            let vals_ptr = ffi::PyList_GET_ITEM(results_ptr, i);

            let exact = ffi::PyDict_CheckExact(vals_ptr) != 0;
            let empty = if exact {
                ffi::PyDict_Size(vals_ptr) == 0
            } else {
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
                miss_items.push(i);
                continue;
            };
            let value = value.as_ptr();

            let write_val = if value == none_ptr {
                none_val_ptr
            } else {
                value
            };
            let stored = if exact {
                ffi::PyDict_SetItem(vals_ptr, name_ptr, write_val)
            } else {
                ffi::PyObject_SetItem(vals_ptr, name_ptr, write_val)
            };
            if stored < 0 {
                return Err(PyErr::fetch(py));
            }
        }

        Ok(PyList::new(py, &miss_items)?.unbind())
    }
}
