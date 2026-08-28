//! Multi-pattern regex search: JS/XML/SCSS shape detection.

use std::sync::Arc;

use pyo3::prelude::*;

use super::lines::LineCursor;
use super::walk::scan_files;

/// One regex hit: `(file_path, line_number, pattern_index, matched_text)`.
/// Factored into an alias to satisfy `clippy::type_complexity`.
type ScanMatch = (String, usize, usize, String);

/// Scan files under *roots* for regex patterns.
///
/// Returns a list of ``(file_path, line_number, pattern_index, matched_text)``
/// for every match — matches are distinguished by their text, so unlike
/// [`super::scan_byte_patterns`] this does not collapse a line (see the module
/// docs). Patterns are compiled once and reused across all files. Use ``(?s)``
/// inline flag for dot-matches-newline (DOTALL). Nested roots are pruned, so a
/// file reachable from two of them is still reported once.
///
/// The GIL is released during scanning so other Python threads are not blocked.
///
/// Example (JS translation misuse)::
///
///     results = scan_regex_patterns(
///         ["/srv/odoo/core"],
///         [".js"],
///         [r"(?s)_t\(\s*`.*?\s*`\s*\)", r"\b_\(\s*['\"]"],
///         ["node_modules"],
///     )
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

    Ok(scan_files(
        py,
        &roots,
        &extensions,
        exclude_dirs,
        move |path, content, hits| {
            // Borrows when the file is valid UTF-8 (the overwhelming case);
            // only a file with invalid bytes pays for a copy. Lossy
            // replacement never adds or removes a `\n`, so line numbers over
            // the converted text are the file's own.
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
    ))
}
