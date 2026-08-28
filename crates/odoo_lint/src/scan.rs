//! Parallel file scanner for lint tests.
//!
//! Two entry points, one shared walk:
//! - [`scan_byte_patterns`]: SIMD-accelerated byte-literal search (conflict markers, etc.)
//! - [`scan_regex_patterns`]: Multi-pattern regex search (JS/XML pattern detection)
//!
//! | module | holds |
//! |---|---|
//! | [`walk`] | root pruning, extension/exclude filtering, the parallel walk, the GIL release |
//! | [`lines`] | [`lines::LineCursor`] — byte offset to line number in one pass per pattern |
//! | [`bytes`] | [`scan_byte_patterns`] |
//! | [`regexes`] | [`scan_regex_patterns`] |
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
//! **One file yields one hit set, however the caller spelled its roots.** That
//! is [`walk::scan_files`]'s job and not the caller's; see the pruning it does
//! and the gate that was reporting double before it did.

mod bytes;
mod lines;
mod regexes;
mod walk;

pub use bytes::scan_byte_patterns;
pub use regexes::scan_regex_patterns;
