//! Byte-literal search: conflict markers, NUL bytes.

use std::sync::Arc;

use pyo3::prelude::*;

use super::lines::LineCursor;
use super::walk::scan_files;

/// One byte-pattern hit: `(file_path, line_number, pattern_index)`.
type ByteMatch = (String, usize, usize);

/// Scan files under *roots* for byte-literal patterns.
///
/// Returns a list of ``(file_path, line_number, pattern_index)`` — one entry per
/// *line* that contains the pattern, not per occurrence (see the module docs).
/// Line numbers are 1-based. Nested roots are pruned, so a file reachable from
/// two of them is still reported once.
///
/// The GIL is released during scanning so other Python threads are not blocked.
///
/// Example (conflict markers)::
///
///     results = scan_byte_patterns(
///         ["/srv/odoo/core"],
///         [".py", ".js", ".xml"],
///         [b"<<<<<<<", b">>>>>>>"],
///         ["node_modules", "__pycache__"],
///     )
#[pyfunction]
pub fn scan_byte_patterns(
    py: Python<'_>,
    roots: Vec<String>,
    extensions: Vec<String>,
    patterns: Vec<Vec<u8>>,
    exclude_dirs: Vec<String>,
) -> PyResult<Vec<ByteMatch>> {
    // An empty needle matches at every offset; `memmem::find` would return
    // Some(start) forever and the advance below could never outrun it.
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
                let mut last_line = 0; // 0 is not a line number — never equal on the first hit
                lines.restart();
                while let Some(pos) = memchr::memmem::find(&content[start..], pat) {
                    let abs = start + pos;
                    let line = lines.line_of(abs);
                    // One hit per line per pattern. Matches arrive in ascending
                    // offset order, so the previous line number is all the
                    // state deduplication needs.
                    if line != last_line {
                        hits.push((path_str.clone(), line, idx));
                        last_line = line;
                    }
                    // Advance past the match, not one byte into it: overlapping
                    // matches are not distinct findings.
                    start = abs + pat.len();
                }
            }
        },
    ))
}
