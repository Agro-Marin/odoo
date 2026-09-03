use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use std::collections::HashSet;
use std::hash::{BuildHasherDefault, Hasher};

#[derive(Default)]
struct IdHasher(u64);

impl Hasher for IdHasher {
    fn write(&mut self, bytes: &[u8]) {
        for &byte in bytes {
            self.0 = (self.0 ^ u64::from(byte)).wrapping_mul(0x0100_0000_01b3);
        }
    }

    fn write_i64(&mut self, value: i64) {
        self.0 = (value as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    }

    fn write_u64(&mut self, value: u64) {
        self.0 = value.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    }

    fn finish(&self) -> u64 {
        self.0
    }
}

type IdBuild = BuildHasherDefault<IdHasher>;
type IdSet = HashSet<i64, IdBuild>;

#[inline]
fn as_positive_id(obj: &Bound<'_, PyAny>) -> Option<i64> {
    if unsafe { ffi::PyLong_Check(obj.as_ptr()) } == 0 {
        return None;
    }
    match obj.extract::<i64>() {
        Ok(value) if value > 0 => Some(value),

        _ => None,
    }
}

#[pyfunction]
pub fn to_prefetch_ids<'py>(
    py: Python<'py>,
    record_id: &Bound<'py, PyAny>,
    prefetch_ids: &Bound<'py, PyTuple>,
    field_cache: &Bound<'py, PyDict>,
    prefetch_max: isize,
) -> PyResult<Option<Py<PyTuple>>> {
    let Some(rec_id) = as_positive_id(record_id) else {
        return Ok(None);
    };

    let budget = prefetch_max.max(0) as usize;
    let mut seen: IdSet = IdSet::with_capacity_and_hasher(budget.min(32), IdBuild::default());
    seen.insert(rec_id);

    let n = prefetch_ids.len();
    let capacity = budget.min(n + 1);
    let mut result: Vec<Bound<'py, PyAny>> = Vec::with_capacity(capacity);
    result.push(record_id.clone());

    let cache_ptr = field_cache.as_ptr();

    for i in 0..n {
        if result.len() >= budget {
            break;
        }
        let id_obj = prefetch_ids.get_item(i)?;

        if let Some(id_val) = as_positive_id(&id_obj) {
            let in_cache = unsafe { ffi::PyDict_Contains(cache_ptr, id_obj.as_ptr()) };
            if in_cache < 0 {
                return Err(PyErr::fetch(py));
            }

            if in_cache == 0 && seen.insert(id_val) {
                result.push(id_obj);
            }
        }
    }

    Ok(Some(PyTuple::new(py, &result)?.unbind()))
}
