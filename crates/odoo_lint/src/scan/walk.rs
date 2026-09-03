use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};

use pyo3::exceptions::PyOSError;

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

pub struct WalkOutcome<T> {
    pub hits: Vec<T>,
    pub failures: Vec<String>,
}

pub fn walk_tree<T, F>(
    roots: &[String],
    extensions: &[String],
    exclude_dirs: &[String],
    per_file: F,
) -> WalkOutcome<T>
where
    T: Send,
    F: Fn(&Path, &[u8], &mut Vec<T>) + Send + Sync,
{
    if roots.is_empty() {
        return WalkOutcome {
            hits: Vec::new(),
            failures: Vec::new(),
        };
    }
    let roots = prune_nested_roots(roots);

    debug_assert!(!roots.is_empty());

    let ext_set = normalize_extensions(extensions);
    let exclude: Arc<[String]> = exclude_dirs.into();
    let results: Arc<Mutex<Vec<T>>> = Arc::default();
    let failures: Arc<Mutex<Vec<String>>> = Arc::default();
    let per_file = &per_file;

    let mut builder = WalkBuilder::new(&roots[0]);
    for root in &roots[1..] {
        builder.add(root);
    }

    builder.standard_filters(false);

    builder.build_parallel().run(|| {
        let ext_set = Arc::clone(&ext_set);
        let exclude = Arc::clone(&exclude);
        let results = Arc::clone(&results);
        let failures = Arc::clone(&failures);
        let fail = move |message: String| {
            failures
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .push(message);
            ignore::WalkState::Continue
        };

        Box::new(move |entry| {
            let entry = match entry {
                Ok(e) => e,
                Err(e) => return fail(e.to_string()),
            };

            if let Some(state) = filter_entry(&entry, &ext_set, &exclude) {
                return state;
            }

            let path = entry.path();
            let content = match std::fs::read(path) {
                Ok(c) => c,
                Err(e) => return fail(format!("{}: {e}", path.display())),
            };

            let mut hits = Vec::new();
            per_file(path, &content, &mut hits);

            if !hits.is_empty() {
                results
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner)
                    .append(&mut hits);
            }

            ignore::WalkState::Continue
        })
    });

    let mut failures = unwrap_shared(failures);
    failures.sort();
    WalkOutcome {
        hits: unwrap_shared(results),
        failures,
    }
}

pub fn scan_files<T, F>(
    py: Python<'_>,
    roots: &[String],
    extensions: &[String],
    exclude_dirs: Vec<String>,
    per_file: F,
) -> PyResult<Vec<T>>
where
    T: Send + 'static,
    F: Fn(&Path, &[u8], &mut Vec<T>) + Send + Sync,
{
    let outcome = py.detach(|| walk_tree(roots, extensions, &exclude_dirs, per_file));
    if !outcome.failures.is_empty() {
        return Err(PyOSError::new_err(format!(
            "scan could not read {} path(s), so its findings are not a count of the tree:\n  {}",
            outcome.failures.len(),
            outcome.failures.join("\n  ")
        )));
    }
    Ok(outcome.hits)
}

fn unwrap_shared<T>(shared: Arc<Mutex<Vec<T>>>) -> Vec<T> {
    match Arc::try_unwrap(shared) {
        Ok(mutex) => mutex.into_inner().unwrap_or_else(PoisonError::into_inner),
        Err(arc) => std::mem::take(&mut *arc.lock().unwrap_or_else(PoisonError::into_inner)),
    }
}

#[cfg(test)]
mod tests {
    use super::{normalize_extensions, prune_nested_roots, walk_tree};
    use std::fs;
    use std::path::{Path, PathBuf};

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

    struct Tree(PathBuf);

    impl Tree {
        fn new(name: &str) -> Self {
            let dir = std::env::temp_dir().join(format!(
                "odoo_lint-{name}-{}-{}",
                std::process::id(),
                std::thread::current()
                    .name()
                    .unwrap_or("t")
                    .replace("::", "-")
            ));
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }

        fn write(&self, rel: &str, content: &str) {
            let path = self.0.join(rel);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, content).unwrap();
        }

        fn root(&self) -> String {
            self.0.to_string_lossy().into_owned()
        }
    }

    impl Drop for Tree {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn scanned_names(tree: &Tree, extensions: &[&str], exclude: &[&str]) -> Vec<String> {
        let root = tree.root();
        let outcome = walk_tree(
            std::slice::from_ref(&root),
            &extensions
                .iter()
                .map(|e| (*e).to_owned())
                .collect::<Vec<_>>(),
            &exclude.iter().map(|e| (*e).to_owned()).collect::<Vec<_>>(),
            |path: &Path, _content: &[u8], hits: &mut Vec<String>| {
                hits.push(
                    path.strip_prefix(&root)
                        .unwrap()
                        .to_string_lossy()
                        .replace('\\', "/"),
                );
            },
        );
        assert!(outcome.failures.is_empty(), "{:?}", outcome.failures);
        let mut names = outcome.hits;
        names.sort();
        names
    }

    #[test]
    fn ignore_files_and_git_excludes_do_not_shrink_the_scan() {
        let tree = Tree::new("filters");
        tree.write("a.py", "x");
        tree.write("sub/b.py", "x");
        tree.write("sub/.ignore", "b.py\n");
        tree.write(".gitignore", "a.py\n");
        tree.write(".git/HEAD", "ref: refs/heads/main\n");
        tree.write(".git/info/exclude", "sub/\n");
        tree.write(".hidden/c.py", "x");
        assert_eq!(
            scanned_names(&tree, &["py"], &[]),
            [".hidden/c.py", "a.py", "sub/b.py"]
        );
    }

    #[test]
    fn an_excluded_directory_name_is_skipped_at_any_depth() {
        let tree = Tree::new("exclude");
        tree.write("keep.py", "x");
        tree.write("node_modules/drop.py", "x");
        tree.write("deep/node_modules/drop.py", "x");
        tree.write("deep/keep.py", "x");
        assert_eq!(
            scanned_names(&tree, &["py"], &["node_modules"]),
            ["deep/keep.py", "keep.py"]
        );
    }

    #[test]
    fn only_the_requested_extensions_are_read() {
        let tree = Tree::new("extensions");
        tree.write("a.py", "x");
        tree.write("b.js", "x");
        tree.write("c.txt", "x");
        tree.write("noext", "x");
        assert_eq!(scanned_names(&tree, &[".py", "js"], &[]), ["a.py", "b.js"]);
    }

    #[test]
    fn a_missing_root_is_a_failure_not_an_empty_count() {
        let missing =
            std::env::temp_dir().join(format!("odoo_lint-missing-{}", std::process::id()));
        let outcome = walk_tree(
            &[missing.to_string_lossy().into_owned()],
            &["py".to_owned()],
            &[],
            |_: &Path, _: &[u8], _: &mut Vec<()>| {},
        );
        assert!(outcome.hits.is_empty());
        assert_eq!(outcome.failures.len(), 1, "{:?}", outcome.failures);
    }
}
