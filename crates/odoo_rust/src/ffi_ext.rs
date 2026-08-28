//! CPython C-API entry points PyO3 does not re-export.
//!
//! Declared once here rather than in each module that wants them: two `unsafe
//! extern "C"` blocks for the same symbol are two declarations that can drift
//! apart in signature, and only one of them would be checked against the real
//! header (neither is — the linker matches on the name alone).

use pyo3::ffi;

unsafe extern "C" {
    /// Pre-allocate a dict's hash table for `minused` entries so filling it
    /// never resizes.
    ///
    /// CPython-internal (it is in `pycore_dict.h`, not `dictobject.h`) but
    /// exported from `libpython` and used heavily by CPython itself. If a
    /// future CPython drops the export the crate fails to *link*, which is the
    /// failure we want: loud, at build time, not a silent behaviour change.
    /// There is no runtime fallback and callers must not assume one.
    ///
    /// It still earns the internal-API dependency on 3.14. Measured against
    /// the public `PyDict_New` on the same sources:
    ///
    /// | workload | presized | `PyDict_New` |
    /// |---|---|---|
    /// | `rows_to_dicts`, 20 cols x 5000 rows | **1069 us** | 1438 us |
    /// | `rows_to_dicts`, 3 cols x 5000 rows | 238 us | 237 us |
    /// | `fast_clone`, nested blob | 0.741 us | 0.770 us |
    ///
    /// The win is entirely the resize it avoids: a 20-column dict grows twice
    /// while filling, a 3-column one never does — which is why the narrow case
    /// is a dead heat and not evidence against. Re-measure before removing it;
    /// do not remove it on the strength of "it is internal API".
    pub fn _PyDict_NewPresized(minused: ffi::Py_ssize_t) -> *mut ffi::PyObject;
}
