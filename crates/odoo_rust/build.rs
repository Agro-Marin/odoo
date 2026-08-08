//! Stamps a fingerprint of this crate's sources into the compiled extension.
//!
//! The extension is a hard dependency with no runtime fallback, so a build that
//! has fallen behind its sources does not degrade — it misbehaves. A stale
//! `.so` once cost an afternoon: `clone.rs` had grown a recursion guard and
//! `sort.rs` had learned to defer aware datetimes to Python, but the installed
//! wheel predated both, so the DB-free suite *segfaulted* on a cyclic structure
//! and silently mis-ordered a timezone-aware column. Neither failure named the
//! real cause, and CI could not reproduce either: every CI lane builds the
//! extension fresh, so only long-lived development virtualenvs are ever exposed.
//!
//! `odoo/init.py` recomputes this value from the crate sources when they are
//! present — i.e. in a development checkout — and refuses to start on a
//! mismatch. That turns "stale build" from a segfault into a sentence.
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

/// Every `.rs` under `src/`, recursively.
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

fn main() {
    let root = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));

    // Cargo.toml is an input: a dependency or feature change alters the built
    // artifact without touching a single line of Rust.
    let mut sources = vec![root.join("Cargo.toml")];
    collect_rust_sources(&root.join("src"), &mut sources);

    // Sort by the *relative* path so the order cannot depend on where the
    // checkout lives — the Python side sorts the same way.
    let mut inputs: Vec<(String, PathBuf)> = sources
        .into_iter()
        .map(|path| {
            let rel = path
                .strip_prefix(&root)
                .expect("source under crate root")
                .to_string_lossy()
                .replace('\\', "/");
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

    println!("cargo:rustc-env=ODOO_RUST_SOURCE_CRC={:08x}", crc32(&blob));
}
