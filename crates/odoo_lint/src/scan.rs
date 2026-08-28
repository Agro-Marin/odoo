//! Parallel file scanner for lint tests.
//!
//! Two entry points:
//! - [`scan_byte_patterns`]: SIMD-accelerated byte-literal search (conflict markers, etc.)
//! - [`scan_regex_patterns`]: Multi-pattern regex search (JS/XML pattern detection)
//!
//! Uses [`ignore::WalkParallel`] for lock-free directory traversal and
//! [`memchr::memmem`] for SIMD-accelerated byte matching.  Typically
//! 10–50× faster than sequential Python file I/O on multi-core machines.
//!
//! The GIL is released via `py.detach()` for the entire scan, allowing
//! other Python threads (request handlers, cron jobs) to run concurrently.
//! This is safe because the Rust worker threads never touch Python objects —
//! all data is Rust-native strings and bytes.
//!
//! # Reporting unit
//!
//! [`scan_byte_patterns`] reports one hit per (file, line, pattern).
//! A byte-literal hit carries no text, so two hits on one line are the
//! *identical* tuple, and counting them separately made the number depend on
//! how many times the byte repeated: `NUL = [b"\x00"]` against a line holding
//! three NUL bytes reported three findings for one line, and searching for
//! `b"<" * 7` in a run of ten `<` reported four (the search restarted one byte
//! past each match, so matches overlapped). Its callers count the findings
//! against a ratchet floor and call them "source file line(s)".
//!
//! [`scan_regex_patterns`] reports **every** match. It never had that problem
//! — `find_iter` is non-overlapping — and its hits carry the matched text, so
//! two matches on one line are two distinguishable findings that a caller
//! (`test_jstranslate` prints the offending string) has a reason to see. Per
//! line deduplication there would discard information to fix a bug the byte
//! scanner had and this one does not.
//!
use std::path::Path;
use std::sync::{Arc, Mutex};

use ignore::WalkBuilder;
use pyo3::prelude::*;

/// One byte-pattern hit: `(file_path, line_number, pattern_index)`.
type ByteMatch = (String, usize, usize);

/// One regex hit: `(file_path, line_number, pattern_index, matched_text)`.
/// Factored into an alias to satisfy `clippy::type_complexity`.
type ScanMatch = (String, usize, usize, String);

// ── Helpers ──────────────────────────────────────────────────────────

/// Turns ascending byte offsets into 1-based line numbers without allocating.
///
/// The naive `memchr_iter(b'\n', &content[..offset]).count()` per match is
/// O(file) per hit and so O(file × hits) per file — quadratic in a file that
/// matches often. Measured on a synthetic file with one match per line,
/// quadrupling the matches quadrupled the *cost per match*: 8k matches took
/// 23 ms, 32k took 191 ms and 128k took 3.0 s.
///
/// Both scanners walk one pattern's matches in ascending offset order, so the
/// newlines between two consecutive matches can be counted once and never
/// re-counted: the whole file costs O(bytes) per pattern. A precomputed
/// `Vec` of every newline offset would also be linear, but it pays for the
/// index on *every* file, and the files these gates scan overwhelmingly
/// contain no match at all — measured over the four repos, indexing eagerly
/// cost +16% peak RSS and +13% wall clock for a scan that found nothing.
/// A cursor costs zero until the first match.
struct LineCursor<'a> {
    content: &'a [u8],
    /// Last offset resolved, and its line. `(0, 1)` before the first call.
    offset: usize,
    line: usize,
}

impl<'a> LineCursor<'a> {
    fn new(content: &'a [u8]) -> Self {
        Self {
            content,
            offset: 0,
            line: 1,
        }
    }

    /// Restart at the top of the buffer, for the next pattern's matches.
    fn restart(&mut self) {
        self.offset = 0;
        self.line = 1;
    }

    /// 1-based line number holding byte `offset`.
    ///
    /// Fast when `offset` is at or after the previous call's, which is how
    /// both callers use it. A lower offset is not a caller error to punish
    /// with a panic — `&content[self.offset..offset]` would panic on an
    /// inverted range, and a panic inside a walker thread is precisely the
    /// failure that used to hang this module — so it simply rescans.
    fn line_of(&mut self, offset: usize) -> usize {
        if offset < self.offset {
            self.restart();
        }
        self.line += memchr::memchr_iter(b'\n', &self.content[self.offset..offset]).count();
        self.offset = offset;
        self.line
    }
}

/// Normalize extensions: strip leading dot if present.
fn normalize_extensions(extensions: &[String]) -> Arc<[String]> {
    extensions
        .iter()
        .map(|e| e.strip_prefix('.').unwrap_or(e).to_owned())
        .collect::<Vec<_>>()
        .into()
}

/// Check whether a directory-entry should be visited.
///
/// Returns `Skip` for excluded directories, `Continue` for non-matching
/// files, and `None` when the entry is a matching file whose `path` the
/// caller should process.
fn filter_entry(
    entry: &ignore::DirEntry,
    ext_set: &[String],
    exclude: &[String],
) -> Option<ignore::WalkState> {
    let path = entry.path();

    if entry.file_type().is_some_and(|ft| ft.is_dir()) {
        if let Some(name) = path.file_name().and_then(|n| n.to_str())
            && exclude.iter().any(|ex| ex.as_str() == name)
        {
            return Some(ignore::WalkState::Skip);
        }
        return Some(ignore::WalkState::Continue);
    }

    let ext = match path.extension().and_then(|e| e.to_str()) {
        Some(e) => e,
        None => return Some(ignore::WalkState::Continue),
    };
    if !ext_set.iter().any(|a| a.as_str() == ext) {
        return Some(ignore::WalkState::Continue);
    }

    None // entry is a matching file — caller should process it
}

/// Walk `roots` in parallel and hand every matching file's bytes to `per_file`.
///
/// The two public scanners differ only in what they do with one file's content,
/// so the walk, the extension/exclude filtering, the read, the GIL release and
/// the result accumulation live here once. `per_file` pushes into the `Vec` it
/// is given; the driver takes the results lock once per file that produced any,
/// never per hit.
///
/// Files that cannot be read (permissions, a symlink to nowhere, a race with a
/// delete) are skipped rather than failing the whole scan — a lint sweep over a
/// live checkout must not die on one unreadable path.
fn scan_files<T, F>(
    py: Python<'_>,
    roots: &[String],
    extensions: &[String],
    exclude_dirs: Vec<String>,
    per_file: F,
) -> Vec<T>
where
    T: Send + 'static,
    F: Fn(&Path, &[u8], &mut Vec<T>) + Send + Sync,
{
    if roots.is_empty() {
        return Vec::new();
    }

    let ext_set = normalize_extensions(extensions);
    let exclude: Arc<[String]> = exclude_dirs.into();
    let results: Arc<Mutex<Vec<T>>> = Arc::default();
    let per_file = &per_file;

    // Release the GIL for the duration of the scan.  Worker threads never
    // touch Python objects — all data is Rust-native.  Without this,
    // parallel I/O blocks all Python threads (request handlers, cron jobs)
    // for the entire scan duration.
    py.detach(|| {
        let mut builder = WalkBuilder::new(&roots[0]);
        for root in &roots[1..] {
            builder.add(root);
        }
        // Don't skip hidden files (Odoo has no meaningful dotfiles to skip),
        // and don't honour .gitignore (we want to scan everything).
        builder.hidden(false).git_ignore(false);

        builder.build_parallel().run(|| {
            let ext_set = Arc::clone(&ext_set);
            let exclude = Arc::clone(&exclude);
            let results = Arc::clone(&results);

            Box::new(move |entry| {
                let entry = match entry {
                    Ok(e) => e,
                    Err(_) => return ignore::WalkState::Continue,
                };

                if let Some(state) = filter_entry(&entry, &ext_set, &exclude) {
                    return state;
                }

                let path = entry.path();
                let content = match std::fs::read(path) {
                    Ok(c) => c,
                    Err(_) => return ignore::WalkState::Continue,
                };

                let mut hits = Vec::new();
                per_file(path, &content, &mut hits);

                if !hits.is_empty() {
                    // A worker that panicked while holding the lock would
                    // poison it; keep scanning on the data we still have
                    // rather than turning one bad file into a panic in every
                    // other thread.
                    if let Ok(mut acc) = results.lock() {
                        acc.append(&mut hits);
                    }
                }

                ignore::WalkState::Continue
            })
        });
    });

    // Every worker closure has been dropped by `run()`, so this is the only
    // remaining handle.
    match Arc::try_unwrap(results) {
        Ok(mutex) => mutex
            .into_inner()
            .unwrap_or_else(std::sync::PoisonError::into_inner),
        // Unreachable in practice; returning what we can beats panicking.
        Err(_) => Vec::new(),
    }
}

// ── Byte Pattern Scanner ─────────────────────────────────────────────

/// Scan files under *roots* for byte-literal patterns.
///
/// Returns a list of ``(file_path, line_number, pattern_index)`` — one entry per
/// *line* that contains the pattern, not per occurrence (see the module docs).
/// Line numbers are 1-based.
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

// ── Regex Pattern Scanner ────────────────────────────────────────────

/// Scan files under *roots* for regex patterns.
///
/// Returns a list of ``(file_path, line_number, pattern_index, matched_text)``
/// for every match — matches are distinguished by their text, so unlike
/// [`scan_byte_patterns`] this does not collapse a line (see the module docs).
/// Patterns are compiled once and reused across all files. Use ``(?s)``
/// inline flag for dot-matches-newline (DOTALL).
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

#[cfg(test)]
mod tests {
    //! Pure-Rust tests for the offset → line-number cursor. The scanners
    //! themselves take Python arguments and walk a real tree; they are covered
    //! by the Python-level tests in `odoo/libs/lint/tests`.
    use super::LineCursor;

    /// What the cursor replaced, kept as the oracle it has to agree with.
    fn naive(content: &[u8], offset: usize) -> usize {
        memchr::memchr_iter(b'\n', &content[..offset]).count() + 1
    }

    #[test]
    fn line_of_matches_a_naive_newline_count_at_every_offset() {
        let content = b"alpha\nbeta\n\ngamma";
        let mut cursor = LineCursor::new(content);
        for offset in 0..=content.len() {
            assert_eq!(
                cursor.line_of(offset),
                naive(content, offset),
                "offset {offset}"
            );
        }
    }

    #[test]
    fn line_of_first_byte_is_line_one() {
        assert_eq!(LineCursor::new(b"").line_of(0), 1);
        assert_eq!(LineCursor::new(b"x").line_of(0), 1);
    }

    #[test]
    fn line_of_byte_after_a_newline_is_the_next_line() {
        // "a\nb": offset 0 -> 1, offset 1 (the \n itself) -> 1, offset 2 -> 2
        let mut cursor = LineCursor::new(b"a\nb");
        assert_eq!(cursor.line_of(0), 1);
        assert_eq!(cursor.line_of(1), 1);
        assert_eq!(cursor.line_of(2), 2);
    }

    #[test]
    fn restart_rewinds_for_the_next_pattern() {
        let content = b"a\nb\nc";
        let mut cursor = LineCursor::new(content);
        assert_eq!(cursor.line_of(4), 3);
        cursor.restart();
        assert_eq!(cursor.line_of(0), 1);
        assert_eq!(cursor.line_of(2), 2);
    }

    #[test]
    fn a_descending_offset_rescans_instead_of_panicking() {
        // The range `&content[self.offset..offset]` would panic inverted, and a
        // panic in a walker thread is what used to hang the whole scan.
        let content = b"a\nb\nc\nd";
        let mut cursor = LineCursor::new(content);
        assert_eq!(cursor.line_of(6), 4);
        assert_eq!(
            cursor.line_of(2),
            2,
            "must rescan, not panic or under-count"
        );
        assert_eq!(cursor.line_of(0), 1);
    }

    #[test]
    fn every_offset_order_agrees_with_the_naive_count() {
        let content = b"one\ntwo\n\nthree\nfour\n";
        for &probes in &[
            [0usize, 4, 8, 9, 15].as_slice(),
            [15, 9, 8, 4, 0].as_slice(),    // fully descending
            [4, 0, 15, 8, 9, 4].as_slice(), // arbitrary
        ] {
            let mut cursor = LineCursor::new(content);
            for &offset in probes {
                assert_eq!(
                    cursor.line_of(offset),
                    naive(content, offset),
                    "offset {offset}"
                );
            }
        }
    }
}
