use pyo3::exceptions::PyAttributeError;
use pyo3::prelude::*;
use pyo3::types::PyTuple;

fn origin_of<'py>(id_obj: Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyAny>>> {
    if id_obj.is_truthy()? {
        return Ok(Some(id_obj));
    }
    match id_obj.getattr(pyo3::intern!(id_obj.py(), "origin")) {
        Ok(origin) if origin.is_truthy()? => Ok(Some(origin)),
        Ok(_) => Ok(None),
        Err(e) if e.is_instance_of::<PyAttributeError>(id_obj.py()) => Ok(None),
        Err(e) => Err(e),
    }
}

#[pyfunction]
pub fn origin_ids<'py>(py: Python<'py>, ids: &Bound<'py, PyAny>) -> PyResult<Py<PyTuple>> {
    let mut result: Vec<Bound<'py, PyAny>> = Vec::new();
    if let Ok(tuple) = ids.cast::<PyTuple>() {
        result.reserve(tuple.len());
        for i in 0..tuple.len() {
            if let Some(kept) = origin_of(tuple.get_item(i)?)? {
                result.push(kept);
            }
        }
    } else {
        for id_obj in ids.try_iter()? {
            if let Some(kept) = origin_of(id_obj?)? {
                result.push(kept);
            }
        }
    }
    Ok(PyTuple::new(py, &result)?.unbind())
}
