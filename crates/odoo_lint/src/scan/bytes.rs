use std::sync::Arc;

use pyo3::prelude::*;

use super::lines::LineCursor;
use super::walk::scan_files;

type ByteMatch = (String, usize, usize);

#[pyfunction]
pub fn scan_byte_patterns(
    py: Python<'_>,
    roots: Vec<String>,
    extensions: Vec<String>,
    patterns: Vec<Vec<u8>>,
    exclude_dirs: Vec<String>,
) -> PyResult<Vec<ByteMatch>> {
    if patterns.iter().any(Vec::is_empty) {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "scan_byte_patterns: patterns must not be empty",
        ));
    }
    let pats: Arc<[Vec<u8>]> = patterns.into();

    Ok(scan_files(
        py,
        &roots,
        &extensions,
        exclude_dirs,
        move |path, content, hits| {
            let mut lines = LineCursor::new(content);
            let path_str = path.to_string_lossy().into_owned();

            for (idx, pat) in pats.iter().enumerate() {
                let mut start = 0;
                let mut last_line = 0;
                lines.restart();
                while let Some(pos) = memchr::memmem::find(&content[start..], pat) {
                    let abs = start + pos;
                    let line = lines.line_of(abs);

                    if line != last_line {
                        hits.push((path_str.clone(), line, idx));
                        last_line = line;
                    }

                    start = abs + pat.len();
                }
            }
        },
    ))
}
