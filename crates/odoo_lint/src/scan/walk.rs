use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use ignore::WalkBuilder;
use pyo3::prelude::*;

fn prune_nested_roots(roots: &[String]) -> Vec<PathBuf> {
    let mut canonical: Vec<PathBuf> = roots
        .iter()
        .map(|root| {
            let path = Path::new(root);
            path.canonicalize().unwrap_or_else(|_| path.to_path_buf())
        })
        .collect();

    canonical.sort();

    let mut kept: Vec<PathBuf> = Vec::with_capacity(canonical.len());
    for root in canonical {
        if !kept.last().is_some_and(|last| root.starts_with(last)) {
            kept.push(root);
        }
    }
    kept
}

fn normalize_extensions(extensions: &[String]) -> Arc<[String]> {
    extensions
        .iter()
        .map(|e| e.strip_prefix('.').unwrap_or(e).to_owned())
        .collect::<Vec<_>>()
        .into()
}

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

    None
}

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

    debug_assert!(!roots.is_empty());

    let ext_set = normalize_extensions(extensions);
    let exclude: Arc<[String]> = exclude_dirs.into();
    let results: Arc<Mutex<Vec<T>>> = Arc::default();
    let per_file = &per_file;

    py.detach(|| {
        let mut builder = WalkBuilder::new(&roots[0]);
        for root in &roots[1..] {
            builder.add(root);
        }

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

                if !hits.is_empty()
                    && let Ok(mut acc) = results.lock()
                {
                    acc.append(&mut hits);
                }

                ignore::WalkState::Continue
            })
        });
    });

    match Arc::try_unwrap(results) {
        Ok(mutex) => mutex
            .into_inner()
            .unwrap_or_else(std::sync::PoisonError::into_inner),

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
