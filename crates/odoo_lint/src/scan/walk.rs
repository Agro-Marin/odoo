//! The parallel walk shared by both scanners: root pruning, filtering, reading.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use ignore::WalkBuilder;
use pyo3::prelude::*;

/// Drop every root another root already contains, so one file yields one hit.
///
/// [`ignore::WalkBuilder`] does not deduplicate across the roots it is given: a
/// file reachable from two of them is walked, read and reported once per root.
/// That is not a hypothetical. `test_markers` passes `core_module_roots()` --
/// 654 module directories -- **plus `odoo.__path__`**, which is the parent of
/// the 26 module roots under `odoo/odoo/addons`. Measured with one NUL byte
/// planted in `odoo/odoo/addons/base` and the real gate run against it:
///
/// ```text
/// AssertionError: 2 source file line(s) holding a raw NUL byte ..., floor is 0
///   .../odoo/addons/base/_dup_probe.py:1
///   .../odoo/addons/base/_dup_probe.py:1
/// ```
///
/// `assert_ratchet` compares `len(findings)` in exact mode, so those 26 modules
/// moved the `lint_nul_byte` and `lint_conflict_marker` floors in units of two
/// while the rest of the tree moved them in units of one.
///
/// Pruning belongs here rather than in the caller: one file yielding one hit set
/// however the caller spelled its roots is the scanner's contract, and fixing it
/// at one call site would leave the other three gates holding the same trap.
///
/// Paths are canonicalized first, so two roots reaching one tree through a
/// symlink also collapse; a root that cannot be canonicalized (it does not
/// exist) keeps its literal path and is handed to the walker to fail on as
/// before. Containment is `Path::starts_with`, which compares whole components
/// -- a string prefix would read `/a/bc` as living under `/a/b`.
fn prune_nested_roots(roots: &[String]) -> Vec<PathBuf> {
    let mut canonical: Vec<PathBuf> = roots
        .iter()
        .map(|root| {
            let path = Path::new(root);
            path.canonicalize().unwrap_or_else(|_| path.to_path_buf())
        })
        .collect();
    // Sorted, so a parent always precedes everything it contains and one
    // backward look is enough.
    canonical.sort();

    let mut kept: Vec<PathBuf> = Vec::with_capacity(canonical.len());
    for root in canonical {
        // `starts_with` is reflexive, so an exact duplicate is dropped here too.
        if !kept.last().is_some_and(|last| root.starts_with(last)) {
            kept.push(root);
        }
    }
    kept
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
/// so the walk, the root pruning, the extension/exclude filtering, the read, the
/// GIL release and the result accumulation live here once. `per_file` pushes
/// into the `Vec` it is given; the driver takes the results lock once per file
/// that produced any, never per hit.
///
/// Files that cannot be read (permissions, a symlink to nowhere, a race with a
/// delete) are skipped rather than failing the whole scan — a lint sweep over a
/// live checkout must not die on one unreadable path.
///
/// The hit order is **not** specified: `WalkParallel` visits files across
/// threads and each file's hits are appended when that file finishes. Callers
/// that render findings sort them (`test_markers`) or count them
/// (`assert_ratchet`); nothing may depend on the order they arrive in.
pub fn scan_files<T, F>(
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
    let roots = prune_nested_roots(roots);
    // `prune_nested_roots` never empties a non-empty input, so `roots[0]` below
    // is always there.
    debug_assert!(!roots.is_empty());

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

#[cfg(test)]
mod tests {
    use super::{normalize_extensions, prune_nested_roots};
    use std::path::PathBuf;

    fn prune(roots: &[&str]) -> Vec<PathBuf> {
        prune_nested_roots(&roots.iter().map(|r| (*r).to_owned()).collect::<Vec<_>>())
    }

    #[test]
    fn a_root_inside_another_is_dropped() {
        // The `test_markers` shape: a tree plus the modules inside it.
        assert_eq!(prune(&["/x/a", "/x/a/b"]), [PathBuf::from("/x/a")]);
        assert_eq!(prune(&["/x/a/b", "/x/a"]), [PathBuf::from("/x/a")]);
        assert_eq!(
            prune(&["/x/a", "/x/a/b", "/x/a/b/c", "/x/a/d"]),
            [PathBuf::from("/x/a")]
        );
    }

    #[test]
    fn an_exact_duplicate_is_dropped() {
        assert_eq!(prune(&["/x/a", "/x/a"]), [PathBuf::from("/x/a")]);
    }

    #[test]
    fn a_sibling_sharing_a_name_prefix_is_kept() {
        // The reason containment is `starts_with` on a Path and not on a str:
        // "/x/ab" begins with the characters of "/x/a" and is not inside it.
        assert_eq!(
            prune(&["/x/a", "/x/ab"]),
            [PathBuf::from("/x/a"), PathBuf::from("/x/ab")]
        );
    }

    #[test]
    fn unrelated_roots_all_survive() {
        assert_eq!(
            prune(&["/x/b", "/x/a", "/y"]),
            [
                PathBuf::from("/x/a"),
                PathBuf::from("/x/b"),
                PathBuf::from("/y")
            ]
        );
    }

    #[test]
    fn a_non_empty_input_never_prunes_to_nothing() {
        // `scan_files` indexes `roots[0]` after pruning.
        for roots in [
            vec!["/x/a"],
            vec!["/x/a", "/x/a"],
            vec!["/x/a", "/x/a/b", "/x/a/b/c"],
        ] {
            assert!(!prune(&roots).is_empty(), "{roots:?} pruned to nothing");
        }
    }

    #[test]
    fn extensions_are_accepted_with_or_without_the_dot() {
        let normalized = normalize_extensions(&[".py".to_owned(), "js".to_owned()]);
        assert_eq!(&*normalized, ["py".to_owned(), "js".to_owned()]);
    }
}
