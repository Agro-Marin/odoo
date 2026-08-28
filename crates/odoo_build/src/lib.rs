//! Stamps a fingerprint of a crate's sources into the extension it builds.
//!
//! A native extension that has fallen behind its sources does not degrade — it
//! misbehaves. A stale `.so` once cost an afternoon: `clone.rs` had grown a
//! recursion guard and `sort.rs` had learned to defer aware datetimes to
//! Python, but the installed wheel predated both, so the DB-free suite
//! *segfaulted* on a cyclic structure and silently mis-ordered a
//! timezone-aware column. Neither failure named the real cause, and CI could
//! not reproduce either: every CI lane builds fresh, so only long-lived
//! development virtualenvs are ever exposed.
//!
//! The Python side recomputes this value from the crate sources when they are
//! present — i.e. in a development checkout — and refuses to proceed on a
//! mismatch (`odoo/libs/native.py`, used by `odoo/init.py` for `odoo_rust` and
//! by `odoo/libs/lint/scan.py` for `odoo_lint`). That turns "stale build" from
//! a segfault into a sentence.
//!
//! This lives in its own crate because it is now used by two extensions. The
//! Python and Rust implementations must agree byte for byte; three copies of
//! that agreement would be two too many.
//!
//! The **profile** is stamped beside the fingerprint, and is a second axis the
//! CRC cannot see: a debug and a release build of identical sources fingerprint
//! identically. `maturin develop` -- the command five places in this repository
//! name -- defaults to the `dev` profile, and a debug `odoo_rust` is not merely
//! slow. Measured against the pure-Python references it replaces, four of its
//! exports are SLOWER than the code they exist to delete: `origin_ids` 4.08x,
//! `sort_ids_by_values` 3.84x, `to_prefetch_ids` 2.53x, `sort_ids_by_cache`
//! 2.41x. `test_native_acceleration_pays` catches that in 1.36s, but it reports
//! it as an algorithm that stopped paying for itself, which sends the reader
//! into `sort.rs` rather than into `maturin`.
//!
//! CRC32 is deliberate. The threat is an out-of-date file, not a forged one, so
//! a checksum is the right instrument; it also lets the Python side use
//! `zlib.crc32` from the standard library, which is ~500x faster than a
//! byte-at-a-time hash in pure Python and keeps the startup cost immeasurable.
//! The two implementations must agree exactly — this is CRC-32/ISO-HDLC, the
//! same parameters `zlib.crc32` uses.

use std::fs;
use std::path::{Path, PathBuf};

/// CRC-32/ISO-HDLC — reflected polynomial `0xEDB88320`, init and final xor
/// `0xFFFFFFFF`. Byte-for-byte identical to Python's `zlib.crc32`.
fn crc32(data: &[u8]) -> u32 {
    let mut table = [0u32; 256];
    for (i, entry) in table.iter_mut().enumerate() {
        let mut c = i as u32;
        for _ in 0..8 {
            c = if c & 1 != 0 {
                0xEDB8_8320 ^ (c >> 1)
            } else {
                c >> 1
            };
        }
        *entry = c;
    }

    let mut crc = 0xFFFF_FFFF_u32;
    for &byte in data {
        crc = table[((crc ^ u32::from(byte)) & 0xFF) as usize] ^ (crc >> 8);
    }
    crc ^ 0xFFFF_FFFF
}

/// Every `.rs` under `dir`, recursively.
fn collect_rust_sources(dir: &Path, found: &mut Vec<PathBuf>) {
    let entries = fs::read_dir(dir).unwrap_or_else(|e| panic!("read_dir {}: {e}", dir.display()));
    for entry in entries {
        let path = entry.expect("dir entry").path();
        if path.is_dir() {
            collect_rust_sources(&path, found);
        } else if path.extension().is_some_and(|ext| ext == "rs") {
            found.push(path);
        }
    }
}

/// Stamp the calling crate's build identity: `{prefix}_SOURCE_CRC` and
/// `{prefix}_PROFILE`.
///
/// The fingerprint covers `../Cargo.lock`, `Cargo.toml` and `src/**/*.rs`.
///
/// Call from a build script; it reads `CARGO_MANIFEST_DIR` to find the crate.
///
/// # Panics
/// If the crate's `src/` is unreadable — a build script has no way to continue
/// usefully from that, and failing the build is the intended outcome.
pub fn stamp_build_identity(prefix: &str) {
    let root = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));

    // Cargo.toml is an input: a feature change alters the built artifact without
    // touching a line of Rust. It is not enough on its own, though, and saying
    // it was is what left a hole here: a manifest names a RANGE. These crates
    // ask for `pyo3 = "0.28.2"` and the lock has already resolved 0.28.3, so a
    // `cargo update` changes the artifact and leaves the fingerprint untouched
    // — exactly the silent staleness this file exists to make loud.
    //
    // The lock is the WORKSPACE's, so an `odoo_lint` dependency bump also
    // invalidates `odoo_rust`'s stamp. That is the safe direction: both are
    // built by one `cargo build`, every CI lane builds both fresh, and the cost
    // of the false positive is one rebuild nobody needed against a false
    // negative that reports wrong answers.
    let mut sources = vec![root.join("Cargo.toml")];
    if root.join("../Cargo.lock").is_file() {
        sources.push(root.join("../Cargo.lock"));
    }
    collect_rust_sources(&root.join("src"), &mut sources);

    // Sort by the *relative* path so the order cannot depend on where the
    // checkout lives — the Python side sorts the same way.
    let mut inputs: Vec<(String, PathBuf)> = sources
        .into_iter()
        .map(|path| {
            // `../Cargo.lock` is labelled literally rather than stripped: it is
            // the one input outside the crate, and the Python side spells the
            // same string.
            let rel = match path.strip_prefix(&root) {
                Ok(under) => under.to_string_lossy().replace('\\', "/"),
                Err(_) => "../Cargo.lock".to_owned(),
            };
            (rel, path)
        })
        .collect();
    inputs.sort_by(|a, b| a.0.cmp(&b.0));

    // Emitting any rerun-if-changed narrows cargo from "rerun when anything in
    // the package changed" to exactly this list, so watch the directory as well
    // as its current contents: *adding* or removing a source changes the
    // directory's mtime but no watched file, and without this the stamp would
    // survive a rebuild while the Python side already saw the new file — a
    // mismatch that rebuilding would not clear.
    println!("cargo:rerun-if-changed=src");
    println!("cargo:rerun-if-changed=../Cargo.lock");

    // Length-delimited so that renaming a file, or moving bytes across a file
    // boundary, cannot leave the concatenation unchanged.
    let mut blob: Vec<u8> = Vec::new();
    for (rel, path) in &inputs {
        blob.extend_from_slice(rel.as_bytes());
        blob.push(0);
        blob.extend_from_slice(&fs::read(path).unwrap_or_else(|e| panic!("read {rel}: {e}")));
        blob.push(0);
        println!("cargo:rerun-if-changed={}", path.display());
    }

    println!("cargo:rustc-env={prefix}_SOURCE_CRC={:08x}", crc32(&blob));

    // `PROFILE` is "debug" or "release"; cargo sets it for every build script.
    let profile = std::env::var("PROFILE").expect("PROFILE");
    println!("cargo:rustc-env={prefix}_PROFILE={profile}");
}

#[cfg(test)]
mod tests {
    use super::crc32;

    /// The values Python's `zlib.crc32` produces for the same inputs. If this
    /// drifts, every freshness check silently starts comparing two different
    /// hashes and reports a stale build forever.
    #[test]
    fn crc32_matches_zlib() {
        assert_eq!(crc32(b""), 0x0000_0000);
        assert_eq!(crc32(b"a"), 0xE8B7_BE43);
        assert_eq!(crc32(b"abc"), 0x3524_41C2);
        assert_eq!(
            crc32(b"The quick brown fox jumps over the lazy dog"),
            0x414F_A339
        );
        assert_eq!(crc32(b"\x00\xff\x00\xff"), 0xB2DE_047C);
    }
}
