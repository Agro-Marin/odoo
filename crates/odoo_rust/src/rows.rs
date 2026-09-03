use pyo3::exceptions::{PyTypeError, PyValueError};
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
        let result = Bound::from_owned_ptr_or_err(py, ffi::PyList_New(nrows))?;
        let result_ptr = result.as_ptr();

        for i in 0..nrows {
            if ffi::PyList_GET_SIZE(rows_ptr) != nrows {
                return Err(PyValueError::new_err(
                    "rows_to_dicts: `rows` changed length during the conversion",
                ));
            }
            let row = Bound::from_borrowed_ptr(py, ffi::PyList_GET_ITEM(rows_ptr, i));
            let row_ptr = row.as_ptr();

            if ffi::PyTuple_Check(row_ptr) == 0 {
                return Err(PyTypeError::new_err(format!("row {} is not a tuple", i)));
            }

            let row_len = ffi::PyTuple_GET_SIZE(row_ptr);
            if row_len != ncols {
                return Err(PyValueError::new_err(format!(
                    "row {} has {} elements, expected {}",
                    i, row_len, ncols
                )));
            }

            let dict = Bound::from_owned_ptr_or_err(py, _PyDict_NewPresized(ncols))?;
            let dict_ptr = dict.as_ptr();

            for j in 0..ncols {
                let key = ffi::PyTuple_GET_ITEM(names_ptr, j);
                let val = ffi::PyTuple_GET_ITEM(row_ptr, j);
                if ffi::PyDict_SetItem(dict_ptr, key, val) < 0 {
                    return Err(PyErr::fetch(py));
                }
            }

            ffi::PyList_SET_ITEM(result_ptr, i, dict.into_ptr());
        }

        Ok(result.cast_into_unchecked::<PyList>().unbind())
    }
}
