use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyTuple};

use crate::ffi_ext::_PyDict_NewPresized;

#[pyfunction]
pub fn rows_to_dicts<'py>(
    py: Python<'py>,
    names: &Bound<'py, PyTuple>,
    rows: &Bound<'py, PyList>,
) -> PyResult<Py<PyList>> {
    let ncols = names.len() as ffi::Py_ssize_t;
    let nrows = rows.len() as ffi::Py_ssize_t;

    let names_ptr = names.as_ptr();
    let rows_ptr = rows.as_ptr();

    unsafe {
        let result_ptr = ffi::PyList_New(nrows);
        if result_ptr.is_null() {
            return Err(PyErr::fetch(py));
        }

        for i in 0..nrows {
            let row_ptr = ffi::PyList_GET_ITEM(rows_ptr, i);

            if ffi::PyTuple_Check(row_ptr) == 0 {
                ffi::Py_DECREF(result_ptr);
                return Err(pyo3::exceptions::PyTypeError::new_err(format!(
                    "row {} is not a tuple",
                    i,
                )));
            }

            let row_len = ffi::PyTuple_GET_SIZE(row_ptr);
            if row_len != ncols {
                ffi::Py_DECREF(result_ptr);
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "row {} has {} elements, expected {}",
                    i, row_len, ncols
                )));
            }

            let dict_ptr = _PyDict_NewPresized(ncols);
            if dict_ptr.is_null() {
                ffi::Py_DECREF(result_ptr);
                return Err(PyErr::fetch(py));
            }

            for j in 0..ncols {
                let key = ffi::PyTuple_GET_ITEM(names_ptr, j);
                let val = ffi::PyTuple_GET_ITEM(row_ptr, j);
                if ffi::PyDict_SetItem(dict_ptr, key, val) < 0 {
                    ffi::Py_DECREF(dict_ptr);
                    ffi::Py_DECREF(result_ptr);
                    return Err(PyErr::fetch(py));
                }
            }

            ffi::PyList_SET_ITEM(result_ptr, i, dict_ptr);
        }

        Ok(Bound::from_owned_ptr(py, result_ptr)
            .cast_into_unchecked::<PyList>()
            .unbind())
    }
}
