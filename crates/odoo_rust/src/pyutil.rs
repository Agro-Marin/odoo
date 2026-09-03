use pyo3::ffi;
use pyo3::prelude::*;

#[inline]
pub(crate) fn is_none_or_false(value: &Bound<'_, PyAny>) -> bool {
    let ptr = value.as_ptr();
    unsafe { ptr == ffi::Py_None() || ptr == ffi::Py_False() }
}
