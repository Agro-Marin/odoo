use pyo3::ffi;
use pyo3::prelude::*;

use crate::ffi_ext::_PyDict_NewPresized;

const MAX_CLONE_DEPTH: usize = 500;

#[pyfunction]
pub fn fast_clone<'py>(obj: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let py = obj.py();
    unsafe { Ok(Bound::from_owned_ptr(py, clone_inner(py, obj.as_ptr(), 0)?)) }
}

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
        if ffi::PyDict_Check(obj) != 0 {
            let size = ffi::PyDict_Size(obj);
            let new_dict = _PyDict_NewPresized(size);
            if new_dict.is_null() {
                return Err(PyErr::fetch(py));
            }

            let mut pos: ffi::Py_ssize_t = 0;
            let mut key: *mut ffi::PyObject = std::ptr::null_mut();
            let mut val: *mut ffi::PyObject = std::ptr::null_mut();

            while ffi::PyDict_Next(obj, &mut pos, &mut key, &mut val) != 0 {
                if ffi::PyDict_Size(obj) != size {
                    ffi::Py_DECREF(new_dict);
                    return Err(pyo3::exceptions::PyRuntimeError::new_err(
                        "dictionary changed size during iteration",
                    ));
                }
                let cloned_val = match clone_inner(py, val, depth + 1) {
                    Ok(v) => v,
                    Err(e) => {
                        ffi::Py_DECREF(new_dict);
                        return Err(e);
                    }
                };

                if ffi::PyDict_SetItem(new_dict, key, cloned_val) < 0 {
                    ffi::Py_DECREF(cloned_val);
                    ffi::Py_DECREF(new_dict);
                    return Err(PyErr::fetch(py));
                }

                ffi::Py_DECREF(cloned_val);
            }

            return Ok(new_dict);
        }

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
                        ffi::Py_DECREF(new_list);
                        return Err(e);
                    }
                };

                ffi::PyList_SET_ITEM(new_list, i, cloned);
            }

            return Ok(new_list);
        }

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

                ffi::PyTuple_SET_ITEM(new_tuple, i, cloned);
            }

            return Ok(new_tuple);
        }

        ffi::Py_INCREF(obj);
        Ok(obj)
    }
}
