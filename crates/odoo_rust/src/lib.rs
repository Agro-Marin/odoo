use pyo3::prelude::*;

mod cache;
mod clone;
mod ffi_ext;
mod ids;
mod prefetch;
mod rows;
mod sort;
mod web;

#[pymodule(gil_used = true)]
fn odoo_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__source_crc__", env!("ODOO_RUST_SOURCE_CRC"))?;
    m.add("__profile__", env!("ODOO_RUST_PROFILE"))?;
    m.add_function(wrap_pyfunction!(clone::fast_clone, m)?)?;
    m.add_function(wrap_pyfunction!(cache::batch_cache_get, m)?)?;
    m.add_function(wrap_pyfunction!(cache::batch_cache_filter, m)?)?;
    m.add_function(wrap_pyfunction!(cache::batch_cache_fill, m)?)?;
    m.add_function(wrap_pyfunction!(ids::origin_ids, m)?)?;
    m.add_function(wrap_pyfunction!(prefetch::to_prefetch_ids, m)?)?;
    m.add_function(wrap_pyfunction!(rows::rows_to_dicts, m)?)?;
    m.add_function(wrap_pyfunction!(web::csv_export, m)?)?;
    m.add_function(wrap_pyfunction!(sort::sort_ids_by_cache, m)?)?;
    m.add_function(wrap_pyfunction!(sort::batch_group_ids, m)?)?;
    Ok(())
}
