use pyo3::ffi;

unsafe extern "C" {
    pub fn _PyDict_NewPresized(minused: ffi::Py_ssize_t) -> *mut ffi::PyObject;
}
