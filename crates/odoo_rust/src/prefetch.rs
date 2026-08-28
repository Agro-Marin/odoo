//! Prefetch ID selection for Field.__get__ cache misses.
//!
//! Replaces `Field._to_prefetch()` — the set-based filtering loop that selects
//! which record IDs to fetch in a single SQL query when a cache miss occurs.
//!
//! Called on *every* lazy field access (potentially 1000s of times per RPC),
//! this is one of the highest-frequency functions in the ORM.
//!
//! The Rust version is faster because:
//! - `PyDict_Contains` for O(1) cache membership testing (same as Python's
//!   `id_ not in field_cache`) without the O(n) cost of building a HashSet
//!   from all cache keys upfront.  The previous HashSet approach was slower
//!   than Python for warm caches (field_cache.len() > PREFETCH_MAX).
//! - A `HashSet<i64>` for the small "already added" tracking set (deduplicate
//!   prefetch_ids without re-adding IDs already in the result), under a
//!   multiply-shift hasher rather than std's SipHash — see [`IdHasher`].
//! - No Python `bool()` coercion dispatch per ID.
//! - No generator frame creation/suspension overhead.

use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use std::collections::HashSet;
use std::hash::{BuildHasherDefault, Hasher};

/// Multiply-shift hash for record ids.
///
/// `HashSet`'s default is SipHash-1-3, chosen to make collisions
/// unpredictable to an attacker who controls the keys. Nothing here is
/// attacker-controlled: the keys are database ids this function has already
/// proven are positive `i64`s, they never leave the call, and a collision
/// costs one extra comparison. Paying for HashDoS resistance on the hottest
/// loop in the ORM buys nothing.
///
/// One multiply by the 64-bit golden ratio scatters sequential ids across the
/// whole word, which is what hashbrown wants — it takes the top 7 bits for its
/// control byte and the low bits for the bucket. Measured on
/// `to_prefetch_ids` with a cold cache: **1000 ids 29.6 us -> 19.6 us (-34%)**,
/// 200 ids 4.7 -> 3.3 (-30%). A warm cache moves less (14.0 -> 13.1) because
/// fewer ids reach the set at all.
#[derive(Default)]
struct IdHasher(u64);

impl Hasher for IdHasher {
    /// Never reached for `i64` keys, which use `write_i64`. Present because
    /// `Hasher` requires it; FNV-1a keeps it correct rather than fast.
    fn write(&mut self, bytes: &[u8]) {
        for &byte in bytes {
            self.0 = (self.0 ^ u64::from(byte)).wrapping_mul(0x0100_0000_01b3);
        }
    }

    fn write_i64(&mut self, value: i64) {
        self.0 = (value as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    }

    fn write_u64(&mut self, value: u64) {
        self.0 = value.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    }

    fn finish(&self) -> u64 {
        self.0
    }
}

type IdBuild = BuildHasherDefault<IdHasher>;
type IdSet = HashSet<i64, IdBuild>;

/// Build the list of IDs to prefetch for a given record.
///
/// This is the computational core of `Field._to_prefetch()`:
/// 1. `result = [record_id]`
/// 2. For each id in prefetch_ids (up to `prefetch_max`):
///    - If id is a positive int not in `field_cache` and not already added:
///      append to result.
///    - Skip NewId objects (falsy) and already-seen/cached ids.
/// 3. Return result as a Python tuple (ready for `browse()`)
///
/// Returns `None` if `record_id` is not a positive integer (NewId case),
/// signaling the caller to use the Python fallback.
#[pyfunction]
pub fn to_prefetch_ids<'py>(
    py: Python<'py>,
    record_id: &Bound<'py, PyAny>,
    prefetch_ids: &Bound<'py, PyTuple>,
    field_cache: &Bound<'py, PyDict>,
    prefetch_max: isize,
) -> PyResult<Option<Py<PyTuple>>> {
    // Only handle real records (positive int IDs).
    // NewId objects fail extract::<i64>(), and id=0 is not a valid DB id.
    let rec_id: i64 = match record_id.extract() {
        Ok(id) if id > 0 => id,
        _ => return Ok(None), // Fall back to Python for NewId
    };

    // `seen` tracks only the IDs WE'VE added to result (to deduplicate).
    // Field cache membership is checked per-ID via PyDict_Contains — O(1)
    // per lookup, matching Python's `id_ not in field_cache`.  This avoids
    // the O(n) cost of iterating all cache keys to build a HashSet upfront,
    // which was slower than Python for warm caches (large n).
    // `isize`, not `usize`: the reference compares `len(result) >= prefetch_max`
    // and so returns `(record_id,)` for a zero or negative budget, while
    // extracting into `usize` raised `OverflowError: can't convert negative int
    // to unsigned` before the function ran at all. PREFETCH_MAX is a positive
    // constant, so this is the two implementations agreeing on an input neither
    // is given rather than a bug being fixed — but they now agree.
    let budget = prefetch_max.max(0) as usize;
    let mut seen: IdSet = IdSet::with_capacity_and_hasher(budget.min(32), IdBuild::default());
    seen.insert(rec_id);

    let n = prefetch_ids.len();
    let capacity = budget.min(n + 1);
    let mut result: Vec<Bound<'py, PyAny>> = Vec::with_capacity(capacity);
    result.push(record_id.clone());

    // SAFETY: cache_ptr is borrowed from a live Python dict with 'py lifetime.
    // PyDict_Contains: returns 1 (present), 0 (absent), -1 (error — key not
    // hashable).  i64 record IDs are always hashable so -1 won't occur, but
    // we check anyway for correctness.
    let cache_ptr = field_cache.as_ptr();

    for i in 0..n {
        if result.len() >= budget {
            break;
        }
        let id_obj = prefetch_ids.get_item(i)?;
        if let Ok(id_val) = id_obj.extract::<i64>()
            && id_val > 0
        {
            // O(1) dict lookup — mirrors Python's `id_ not in field_cache`
            let in_cache = unsafe { ffi::PyDict_Contains(cache_ptr, id_obj.as_ptr()) };
            if in_cache < 0 {
                return Err(PyErr::fetch(py));
            }
            // seen.insert() returns true if newly inserted (not a duplicate)
            if in_cache == 0 && seen.insert(id_val) {
                result.push(id_obj);
            }
        }
        // Non-int IDs (NewId): bool(NewId) == False → skip (kind == True path only)
    }

    // Return a tuple — browse() uses tuples directly without conversion.
    Ok(Some(PyTuple::new(py, &result)?.unbind()))
}
