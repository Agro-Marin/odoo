use std::sync::Arc;

use pyo3::prelude::*;

use super::lines::LineCursor;
use super::walk::scan_files;

type ScanMatch = (String, usize, usize, String);

#[pyfunction]
pub fn scan_regex_patterns(
    py: Python<'_>,
    roots: Vec<String>,
    extensions: Vec<String>,
    patterns: Vec<String>,
    exclude_dirs: Vec<String>,
) -> PyResult<Vec<ScanMatch>> {
    let regexes: Arc<[regex::Regex]> = patterns
        .iter()
        .map(|p| regex::Regex::new(p))
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid regex: {e}")))?
        .into();

    scan_files(
        py,
        &roots,
        &extensions,
        exclude_dirs,
        move |path, content, hits| {
            let text = String::from_utf8_lossy(content);
            let mut lines = LineCursor::new(text.as_bytes());
            let path_str = path.to_string_lossy().into_owned();

            for (idx, re) in regexes.iter().enumerate() {
                lines.restart();
                for m in re.find_iter(&text) {
                    let line = lines.line_of(m.start());
                    hits.push((path_str.clone(), line, idx, m.as_str().to_owned()));
                }
            }
        },
    )
}
