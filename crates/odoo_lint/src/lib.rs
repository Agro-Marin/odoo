use pyo3::prelude::*;

mod scan;

#[pymodule(gil_used = true)]
fn odoo_lint(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__source_crc__", env!("ODOO_LINT_SOURCE_CRC"))?;

    m.add("__profile__", env!("ODOO_LINT_PROFILE"))?;
    m.add_function(wrap_pyfunction!(scan::scan_byte_patterns, m)?)?;
    m.add_function(wrap_pyfunction!(scan::scan_regex_patterns, m)?)?;
    Ok(())
}
