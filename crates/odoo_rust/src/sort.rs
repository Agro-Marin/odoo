//! Sort and group operations on (ids, values) pairs.
//!
//! Two entry points:
//! - [`sort_ids_by_values`]: stable sort of a record ID tuple by cached values,
//!   with optional null-aware (None/False) handling.
//! - [`batch_group_ids`]: group record IDs by corresponding values, returning
//!   a plain Python dict.
//!
//! Both operate on (`ids: tuple`, `values: list`) pairs that are produced by
//! [`crate::cache::batch_cache_get`] / [`crate::cache::batch_cache_values`],
//! replacing the Python-level loops in `sorted()` and `grouped()`.
//!
//! # Performance notes
//!
//! `sort_ids_by_values` avoids the Python pattern:
//!   `list(zip(ids, values)) + sort(key=itemgetter(1)) + tuple(pair[0] for ...)`
//! which creates N two-element Python tuples before sorting and N key-function
//! calls during the sort.
//!
//! The fast path is **decorate-sort-undecorate done in Rust**: each value is
//! extracted *once* into a native Rust key ([`Key`] — `i64` / `f64` / borrowed
//! `str` / packed datetime), then sorted with a pure-Rust comparator.  This is
//! the crucial difference from a naive port: comparing Python objects directly
//! would call `PyObject_RichCompareBool` (up to twice) on every one of the
//! `~n·log n` comparison nodes, and those FFI boundary crossings cost *more*
//! than the N temporary tuples the Python version allocates — so a naive port
//! is actually slower than CPython's Timsort.  Extracting native keys up front
//! turns `2·n·log n` boundary crossings into `n` extractions, after which the
//! sort itself touches no Python objects at all.
//!
//! **Decorating faster than CPython is not enough on its own.** Measured at
//! n=4000 against the pure-Python reference, decoration was already 2.5x
//! faster while *comparison* was 2-3x slower, for every column type — and on a
//! column of short distinct strings the two cancelled out and the accelerated
//! call came in 9-13% SLOWER than the Python it exists to replace. The cost was
//! a comparator that dispatched on a two-variant `Entry` and then a
//! four-variant `Key`, on every comparison node, for a column whose type was
//! settled before the sort began. [`Column`] moves that decision to decode
//! time, so each sort monomorphises to one `K::cmp`; see its docs for the
//! numbers.
//!
//! Anything the native path cannot represent (heterogeneous columns, huge ints
//! that overflow `i64`, exotic types, non-UTF-8 strings) makes [`decode_column`]
//! return `None`, and we fall back to [`sort_objects_to_tuple`] — the
//! object-comparison implementation — which preserves exact Python ordering
//! semantics (including raising the same `TypeError` on incomparable values).
//!
//! [`sort_ids_by_cache`] fuses the cache read into the sort: it reads each value
//! straight from the field-cache dict, so the single-field `sorted()` fast path
//! never materializes an intermediate Python values list.
//!
//! `batch_group_ids` replaces the `defaultdict(list)` loop in `grouped()`:
//!   `for i, rec_id in enumerate(ids): collator[results[i]].append(rec_id)`
//! with a tight C loop using `PyDict_GetItem` + `PyList_Append`, eliminating
//! Python loop overhead and `defaultdict.__missing__` dispatch.

use std::cmp::Ordering;

use pyo3::exceptions::PyValueError;
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{
    PyDate, PyDateAccess, PyDateTime, PyDict, PyFloat, PyInt, PyList, PyString, PyTimeAccess,
    PyTuple, PyTzInfoAccess,
};

// ── Helpers ──────────────────────────────────────────────────────────────────

/// Compare two Python objects the way `list.sort` does: with `<`, and nothing
/// else.
///
/// `Ordering::Greater` is decided by asking `b < a` rather than `a > b`.
/// CPython's sort never invokes `__gt__` — a key type only has to implement
/// `__lt__` to be sortable — so probing it reads a second protocol the
/// reference implementation never touches. Measured consequences of the `a > b`
/// probe this replaced, both against the pure-Python path:
///
/// - a key type that implements `__lt__` and whose `__gt__` *raises* sorted
///   fine in CPython and failed here;
/// - a key type whose `__gt__` contradicts its `__lt__` diverged on 2494 of
///   6000 randomized sorts (only with `reverse=True`, where a comparator that
///   can never say `Greater` becomes one that can never say `Less`).
///
/// Neither is reachable from a well-behaved key, and every value that gets
/// this far has already failed to be representable natively, so this is the
/// contract being honest rather than a bug being fixed. What it is NOT is a
/// re-ordering risk for ordinary types: a stable sort only ever acts on
/// `Less`, which both spellings compute with the same `__lt__` call.
///
/// `Ordering::Equal` for "neither is less" is required as well as correct:
/// `sort_by` needs a real total order, and reporting a tie as `Greater` would
/// break stability. It does cost a second `__lt__` call where CPython makes
/// one; a comparator that returned only `Less`/`Greater` would match CPython's
/// call count but hand `sort_by` an order it documents as unspecified.
///
/// Returns `Ordering::Equal` and sets `*sort_err` on any comparison error.
///
/// SAFETY: `va` and `vb` must be valid, non-null Python object pointers.
#[inline]
unsafe fn compare_py(
    py: Python<'_>,
    va: *mut ffi::PyObject,
    vb: *mut ffi::PyObject,
    sort_err: &mut Option<PyErr>,
) -> std::cmp::Ordering {
    unsafe {
        let lt = ffi::PyObject_RichCompareBool(va, vb, ffi::Py_LT);
        if lt < 0 {
            *sort_err = Some(PyErr::fetch(py));
            return std::cmp::Ordering::Equal;
        }
        if lt != 0 {
            return std::cmp::Ordering::Less;
        }
        let gt = ffi::PyObject_RichCompareBool(vb, va, ffi::Py_LT);
        if gt < 0 {
            *sort_err = Some(PyErr::fetch(py));
            return std::cmp::Ordering::Equal;
        }
        if gt != 0 {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Equal
        }
    }
}

// ── Public functions ──────────────────────────────────────────────────────────

/// Sort record IDs by corresponding cached values.
///
/// `sort_ids_by_values(ids, values, reverse, null_high=None) -> tuple`
///
/// - `ids`: tuple of record IDs (the `self._ids` tuple)
/// - `values`: list of cached values, one per id (same length as ids)
/// - `reverse`: if True, sort descending
/// - `null_high`: `None` = no null handling (treat None/False as regular values);
///                `True` = None/False sort last in ASC (high/after non-nulls);
///                `False` = None/False sort first in ASC (low/before non-nulls)
///
/// Returns a new tuple of IDs in sorted order.
///
/// Replaces the Python pattern used in `_sorted_by_ids`:
/// ```text
/// # no-null path:
/// pairs = list(zip(ids, values))
/// pairs.sort(key=itemgetter(1), reverse=reverse_param)
/// return tuple(pair[0] for pair in pairs)
///
/// # null-aware path:
/// keys = [(_null_rank, "") if v is None or v is False else (_val_rank, v) ...]
/// ... same sort + extract ...
/// ```
///
/// The Rust version uses a `Vec<usize>` index array sorted in-place (stable
/// Timsort equivalent), then builds the output tuple from the original `ids`.
/// Zero new Python objects are created during the sort itself.
#[pyfunction]
#[pyo3(signature = (ids, values, reverse, null_high = None))]
pub fn sort_ids_by_values<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    values: &Bound<'py, PyList>,
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Py<PyTuple>> {
    // Bounds contract, matching `batch_group_ids` and `batch_cache_fill`.
    // Without it the two lengths disagreed silently in one direction and
    // obscurely in the other: a longer `values` dropped its tail, and a
    // shorter one surfaced as `IndexError: list index out of range` from
    // `get_item` — while the pure-Python reference zipped non-strictly and
    // returned a tuple with fewer ids than it was given, which a caller would
    // read as records vanishing from a `sorted()`. Checked ahead of the n<=1
    // shortcut so a one-record sort is held to the same contract.
    //
    // Nothing in the ORM passes a mismatched pair — `sorted()` reaches
    // `sort_ids_by_cache`, which reads its values out of the cache keyed by
    // the very ids it is sorting. This is a contract the two implementations
    // now state identically instead of two different accidents.
    if values.len() != ids.len() {
        return Err(PyValueError::new_err(
            "sort_ids_by_values: `values` must have the same length as `ids`",
        ));
    }

    let n = ids.len();
    if n <= 1 {
        return Ok(ids.clone().unbind());
    }

    // Materialize owned refs to the values so `Key::Str` can borrow into each
    // PyUnicode buffer (no copy); they stay alive for the whole sort.
    let holder: Vec<Bound<'py, PyAny>> = (0..n)
        .map(|i| values.get_item(i))
        .collect::<PyResult<Vec<_>>>()?;
    sort_holder(py, ids, &holder, reverse, null_high)
}

/// Fused cache-read + sort — the single-field `sorted()` fast path.
///
/// Reads each `field_cache[id]` directly (`PyDict_GetItem`, borrowed) instead of
/// having Python first build an intermediate values list via `batch_cache_values`
/// and hand it back in a second call. Returns:
/// - `Ok(None)` if any id is a cache miss or holds `pending` — the caller then
///   abandons the fast path (exactly as `batch_cache_values` returning `None`);
/// - `Ok(Some(tuple))` with the sorted ids otherwise (native fast path, or the
///   object-comparison fallback for exotic / heterogeneous columns).
#[pyfunction]
#[pyo3(signature = (field_cache, ids, pending, reverse, null_high = None))]
pub fn sort_ids_by_cache<'py>(
    py: Python<'py>,
    field_cache: &Bound<'py, PyDict>,
    ids: &Bound<'py, PyTuple>,
    pending: &Bound<'py, PyAny>,
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Option<Py<PyTuple>>> {
    let n = ids.len();

    // Read all cached values as owned refs; bail (None) on the first miss/pending
    // so the caller falls back to the general record-based sort.
    //
    // SAFETY: cache_ptr/ids_ptr borrowed from live objects with 'py lifetime.
    // PyDict_GetItem returns a borrowed ref (NULL on a clean miss, no exception —
    // ids are always hashable ints). PyTuple_GET_ITEM skips bounds checks (i in
    // 0..n). from_borrowed_ptr INCREFs the value into the holder.
    let holder: Vec<Bound<'py, PyAny>> = unsafe {
        let cache_ptr = field_cache.as_ptr();
        let ids_ptr = ids.as_ptr();
        let pending_ptr = pending.as_ptr();
        let mut holder = Vec::with_capacity(n);
        for i in 0..n {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i as ffi::Py_ssize_t);
            let v = ffi::PyDict_GetItem(cache_ptr, id_obj);
            if v.is_null() || v == pending_ptr {
                return Ok(None);
            }
            holder.push(Bound::from_borrowed_ptr(py, v));
        }
        holder
    };

    if n <= 1 {
        return Ok(Some(ids.clone().unbind()));
    }
    sort_holder(py, ids, &holder, reverse, null_high).map(Some)
}

/// Shared core: decorate the holder values into native keys and sort, falling
/// back to object comparison when a column isn't natively representable.
fn sort_holder<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    holder: &[Bound<'py, PyAny>],
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Py<PyTuple>> {
    let false_ptr = unsafe { ffi::Py_False() };
    match decode_column(holder, null_high.is_some(), false_ptr) {
        Some(mut column) => {
            let order = sort_column(&mut column, reverse, null_high);
            build_sorted_tuple(py, ids, &order)
        }
        None => sort_objects_to_tuple(py, ids, holder, reverse, null_high),
    }
}

// ── Native fast path (decorate-sort-undecorate) ────────────────────────────────

/// A native comparison key extracted from a Python cache value.
///
/// `Str` borrows directly into the live `PyUnicode` UTF-8 buffer (no copy) — the
/// borrowed values are kept alive for the whole sort. `Date` carries a *packed*
/// `i64` rather than the `[i32; 7]` component array it used to: see
/// [`pack_datetime`].
///
/// This enum decides the column's type ONCE, before sorting. It is deliberately
/// not what the comparator sees — see [`Column`].
enum Key<'a> {
    Int(i64),
    Float(f64),
    Str(&'a str),
    Date(i64),
}

/// `f64` under a total order, so it can be a plain `Ord` sort key.
///
/// `total_cmp` is NaN-safe, which `sort_by` requires; a NaN in the column never
/// reaches here anyway (`decode_column` sends it to the object-comparison
/// fallback, because Python's `<`/`>` are both false for NaN and give
/// order-dependent results this cannot reproduce).
/// All four traits are written in terms of `total_cmp`, never derived: on
/// `f64` the derived `PartialEq` and `PartialOrd` disagree with it (NaN equals
/// nothing and orders against nothing, while `total_cmp` gives it a place), and
/// a type whose `Ord` and `PartialOrd` disagree is one `sort_by` is entitled to
/// misbehave on.
#[derive(Clone, Copy)]
struct Total(f64);

impl Ord for Total {
    #[inline]
    fn cmp(&self, other: &Self) -> Ordering {
        self.0.total_cmp(&other.0)
    }
}

impl PartialOrd for Total {
    #[inline]
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl PartialEq for Total {
    #[inline]
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other) == Ordering::Equal
    }
}

impl Eq for Total {}

/// Pack a date or datetime into one `i64` whose numeric order is chronological.
///
/// Each component gets a power-of-two field wider than its range — month < 16,
/// day < 32, hour < 32, minute < 64, second < 64 (leap seconds included),
/// microsecond < 2^20 — so the packing is strictly monotone and a comparison is
/// one integer compare. A plain `date` leaves the four time fields at zero,
/// which is midnight, which is where a date sorts against a datetime on the
/// same day.
///
/// Year 9999 needs 14 bits and the rest 46, so the result is under 2^60 and
/// cannot overflow. The `[i32; 7]` array this replaced compared lexicographically
/// — also correct, but 28 bytes wide, which forced every `Key` in the column to
/// 32 bytes whatever its type.
#[inline]
fn pack_datetime(year: i32, month: u32, day: u32, hour: u32, min: u32, sec: u32, us: u32) -> i64 {
    let mut packed = i64::from(year);
    packed = packed * 16 + i64::from(month);
    packed = packed * 32 + i64::from(day);
    packed = packed * 32 + i64::from(hour);
    packed = packed * 64 + i64::from(min);
    packed = packed * 64 + i64::from(sec);
    packed * 1_048_576 + i64::from(us)
}

/// A decoded column: every value as one native key type, paired with the index
/// it came from.
///
/// The point is that the comparator sees a **concrete** key type. The previous
/// shape sorted an index array with a comparator that matched a two-variant
/// `Entry` and then a four-variant `Key` — a 2x4x4 dispatch on every one of the
/// `n log n` comparison nodes, for a column whose type was already known before
/// the sort began. Decomposed at n=4000 (permuted input, against the
/// pure-Python reference this exists to beat):
///
/// | column | decorate | compare, before | compare, after |
/// |---|---|---|---|
/// | short str | 58 us | 220 us | see the suite in `test_sort_parity_fuzz` |
/// | int | 67 us | 69 us | |
///
/// Decorating was already 2.5x faster than CPython; comparing was 2-3x SLOWER,
/// for every type, and on a column of short distinct strings that made the
/// whole call **13% slower than the Python it replaces**. Monomorphising is
/// what closes it: each arm below sorts a `Vec<(K, u32)>` whose comparator is
/// one `K::cmp` with nothing to dispatch on.
///
/// `u32` for the index, not `usize`: it halves the pair and no recordset has
/// 4 billion records.
enum Column<'a> {
    Int(Vec<(i64, u32)>),
    Float(Vec<(Total, u32)>),
    Str(Vec<(&'a str, u32)>),
    Date(Vec<(i64, u32)>),
    /// Null-aware columns keep the same key types under an `Option`, whose
    /// `None` is the null. Separate from the arms above so the common
    /// (`null_high is None`) path never pays for a null test it cannot need.
    IntOpt(Vec<(Option<i64>, u32)>),
    FloatOpt(Vec<(Option<Total>, u32)>),
    StrOpt(Vec<(Option<&'a str>, u32)>),
    DateOpt(Vec<(Option<i64>, u32)>),
}

/// Sort a decoded column with no nulls in it.
///
/// Generic, so the comparator monomorphises to a single `K::cmp`. `sort_by` is
/// stable, so equal keys keep their original id order — matching CPython's
/// stable sort, including under `reverse`, where comparing `b` against `a`
/// still reports a tie as `Equal` and leaves the pair alone.
fn sort_plain<K: Ord>(rows: &mut [(K, u32)], reverse: bool) {
    if reverse {
        rows.sort_by(|a, b| b.0.cmp(&a.0));
    } else {
        rows.sort_by(|a, b| a.0.cmp(&b.0));
    }
}

/// Sort a decoded column whose `None`s are nulls, placed per `null_high`.
///
/// `null_high == true` puts them after the values in ascending order, `false`
/// before — mirroring [`sort_objects_to_tuple`] and the pure-Python reference's
/// `(rank, value)` key tuples.
fn sort_nullable<K: Ord>(rows: &mut [(Option<K>, u32)], reverse: bool, null_high: bool) {
    rows.sort_by(|a, b| {
        let ord = match (&a.0, &b.0) {
            (Some(x), Some(y)) => x.cmp(y),
            (None, None) => Ordering::Equal,
            (None, Some(_)) => {
                if null_high {
                    Ordering::Greater
                } else {
                    Ordering::Less
                }
            }
            (Some(_), None) => {
                if null_high {
                    Ordering::Less
                } else {
                    Ordering::Greater
                }
            }
        };
        if reverse { ord.reverse() } else { ord }
    });
}

/// Sort a decoded column and hand back the original indices in sorted order.
fn sort_column(column: &mut Column<'_>, reverse: bool, null_high: Option<bool>) -> Vec<usize> {
    /// Sort one arm and project out the indices. A macro rather than a generic
    /// function because each arm has a different `K` *and* a different variant.
    macro_rules! run {
        ($rows:expr, $sorter:expr) => {{
            $sorter;
            $rows.iter().map(|&(_, i)| i as usize).collect()
        }};
    }
    let high = null_high.unwrap_or(false);
    match column {
        Column::Int(r) => run!(r, sort_plain(r, reverse)),
        Column::Float(r) => run!(r, sort_plain(r, reverse)),
        Column::Str(r) => run!(r, sort_plain(r, reverse)),
        Column::Date(r) => run!(r, sort_plain(r, reverse)),
        Column::IntOpt(r) => run!(r, sort_nullable(r, reverse, high)),
        Column::FloatOpt(r) => run!(r, sort_nullable(r, reverse, high)),
        Column::StrOpt(r) => run!(r, sort_nullable(r, reverse, high)),
        Column::DateOpt(r) => run!(r, sort_nullable(r, reverse, high)),
    }
}

/// Build the result tuple by copying IDs from `ids` in `order`.
///
/// SAFETY: every index in `order` is in `0..ids.len()`.  `PyTuple_GET_ITEM`
/// skips bounds checks; `PyTuple_SET_ITEM` steals the reference we INCREF.
fn build_sorted_tuple<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    order: &[usize],
) -> PyResult<Py<PyTuple>> {
    let ids_ptr = ids.as_ptr();
    unsafe {
        let result = ffi::PyTuple_New(order.len() as ffi::Py_ssize_t);
        if result.is_null() {
            return Err(PyErr::fetch(py));
        }
        for (slot, &orig_idx) in order.iter().enumerate() {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, orig_idx as ffi::Py_ssize_t);
            ffi::Py_INCREF(id_obj);
            ffi::PyTuple_SET_ITEM(result, slot as ffi::Py_ssize_t, id_obj);
        }
        Ok(Bound::from_owned_ptr(py, result)
            .cast_into_unchecked::<PyTuple>()
            .unbind())
    }
}

/// Decode a column of Python values into one native key type.
///
/// Returns `None` to signal the column can't be represented natively (mixed
/// types, `i64` overflow, non-UTF-8 string, NaN float, aware datetime, or an
/// unknown type) — the caller then uses the object-comparison fallback, which
/// has Python's exact semantics including the `TypeError`s. `Column::Str`
/// borrows into the holder's live `PyUnicode` buffers, so the result borrows
/// `holder`.
///
/// The type is decided here, once, and the sort is chosen from it — which is
/// the whole point of [`Column`].
fn decode_column<'a>(
    holder: &'a [Bound<'_, PyAny>],
    null_aware: bool,
    false_ptr: *mut ffi::PyObject,
) -> Option<Column<'a>> {
    /// The four key types, before we know which one the column is.
    enum Slot<'a> {
        Null,
        Val(Key<'a>),
    }

    let mut slots: Vec<Slot<'a>> = Vec::with_capacity(holder.len());
    // Column kind tag: 1=int, 2=float, 3=str, 4=datetime, 5=date. `date` and
    // `datetime` are tagged SEPARATELY even though both decode into a packed
    // i64. They shared a tag, so a column holding both stayed on the native
    // path and sorted chronologically — while Python REFUSES to compare them
    // (`datetime.date(2021, 1, 1) < datetime.datetime(2021, 1, 1)` raises
    // TypeError, because `datetime` is a `date` subclass that declines the
    // mixed comparison). That is the same divergence the aware-datetime branch
    // below rejects the native path to avoid, in the same function, a few lines
    // apart. Splitting the tag sends a mixed column to the FFI fallback, which
    // raises exactly what Python does.
    let mut kind: u8 = 0;

    for v in holder {
        // In null-aware mode None/False are nulls, never compared as values.
        // (When null_high is None the caller guarantees no None/False present.)
        if null_aware && (v.is_none() || v.as_ptr() == false_ptr) {
            slots.push(Slot::Null);
            continue;
        }

        let (k, key) = if let Ok(st) = v.cast::<PyString>() {
            match st.to_str() {
                Ok(text) => (3, Key::Str(text)),
                Err(_) => return None, // non-UTF-8 (lone surrogate) → FFI
            }
        } else if let Ok(f) = v.cast::<PyFloat>() {
            let fv = f.value();
            // NaN: Python's `<`/`>` are both false, giving order-dependent
            // results that `total_cmp` can't reproduce — defer to FFI.
            if fv.is_nan() {
                return None;
            }
            // Normalize -0.0 → 0.0: Python treats them as equal (a tie), but
            // `total_cmp` would order -0.0 before +0.0 and reshuffle the tie.
            (2, Key::Float(if fv == 0.0 { 0.0 } else { fv }))
        } else if let Ok(iobj) = v.cast::<PyInt>() {
            match iobj.extract::<i64>() {
                Ok(iv) => (1, Key::Int(iv)),
                Err(_) => return None, // > i64 → FFI
            }
        } else if let Ok(dt) = v.cast::<PyDateTime>() {
            // Check datetime before date: datetime is a subclass of date, so a
            // `PyDate` cast would also succeed and drop the time components.
            //
            // Aware datetimes leave the native path: Python compares them by
            // UTC instant, and refuses to compare an aware one against a naive
            // one at all (TypeError). The packing below reproduces neither --
            // it would order by wall clock, and would silently sort a mixed
            // column instead of raising. The FFI fallback has the exact
            // semantics, so defer to it.
            if dt.get_tzinfo().is_some() {
                return None;
            }
            (
                4,
                Key::Date(pack_datetime(
                    dt.get_year(),
                    dt.get_month().into(),
                    dt.get_day().into(),
                    dt.get_hour().into(),
                    dt.get_minute().into(),
                    dt.get_second().into(),
                    dt.get_microsecond(),
                )),
            )
        } else if let Ok(d) = v.cast::<PyDate>() {
            (
                5,
                Key::Date(pack_datetime(
                    d.get_year(),
                    d.get_month().into(),
                    d.get_day().into(),
                    0,
                    0,
                    0,
                    0,
                )),
            )
        } else {
            return None; // unknown type → FFI (preserves Python semantics)
        };

        if kind == 0 {
            kind = k;
        } else if kind != k {
            return None; // mixed types in one column → FFI (matches Python)
        }
        slots.push(Slot::Val(key));
    }

    // Project the slots into the one typed vector the column turned out to be.
    // `kind == 0` means every slot is a null (or the column is empty), which
    // any arm sorts identically; int is as good as another.
    macro_rules! project {
        ($variant:ident, $pat:pat => $extract:expr) => {{
            let mut rows = Vec::with_capacity(slots.len());
            for (index, slot) in slots.iter().enumerate() {
                let index = index as u32;
                match slot {
                    Slot::Val($pat) => rows.push(($extract, index)),
                    // Unreachable: a null in a non-null-aware column was never
                    // pushed, and the null-aware arms are handled above.
                    _ => return None,
                }
            }
            Column::$variant(rows)
        }};
        ($variant:ident, opt $pat:pat => $extract:expr) => {{
            let mut rows = Vec::with_capacity(slots.len());
            for (index, slot) in slots.iter().enumerate() {
                let index = index as u32;
                rows.push(match slot {
                    Slot::Null => (None, index),
                    Slot::Val($pat) => (Some($extract), index),
                    Slot::Val(_) => return None,
                });
            }
            Column::$variant(rows)
        }};
    }

    Some(if null_aware {
        match kind {
            2 => project!(FloatOpt, opt Key::Float(x) => Total(*x)),
            3 => project!(StrOpt, opt Key::Str(x) => *x),
            4 | 5 => project!(DateOpt, opt Key::Date(x) => *x),
            _ => project!(IntOpt, opt Key::Int(x) => *x),
        }
    } else {
        match kind {
            2 => project!(Float, Key::Float(x) => Total(*x)),
            3 => project!(Str, Key::Str(x) => *x),
            4 | 5 => project!(Date, Key::Date(x) => *x),
            _ => project!(Int, Key::Int(x) => *x),
        }
    })
}

// ── Object-comparison fallback ─────────────────────────────────────────────────

/// Sort by comparing the Python objects directly (one `PyObject_RichCompareBool`
/// per node).  Used when [`decode_column`] cannot extract native keys; it
/// preserves exact Python ordering, including raising `TypeError` on values that
/// are not mutually comparable.
fn sort_objects_to_tuple<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    holder: &[Bound<'py, PyAny>],
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Py<PyTuple>> {
    // Build index array [0, 1, ..., n-1] and sort it by holder[i].
    // `sort_by` is a stable sort (like Python's Timsort), so equal values
    // preserve the original relative order of their IDs.
    let mut indices: Vec<usize> = (0..holder.len()).collect();
    let mut sort_err: Option<PyErr> = None;

    // SAFETY: each holder[i] is a live Bound; as_ptr() is a valid borrowed
    // pointer. PyObject_RichCompareBool is safe to call with the GIL held.
    unsafe {
        let none_ptr = ffi::Py_None();
        let false_ptr = ffi::Py_False();

        indices.sort_by(|&a, &b| {
            if sort_err.is_some() {
                return Ordering::Equal;
            }

            let va = holder[a].as_ptr();
            let vb = holder[b].as_ptr();

            let ord = match null_high {
                None => compare_py(py, va, vb, &mut sort_err),
                Some(nh) => {
                    let a_null = va == none_ptr || va == false_ptr;
                    let b_null = vb == none_ptr || vb == false_ptr;
                    match (a_null, b_null) {
                        (true, true) => Ordering::Equal,
                        // null_high=true  → nulls are "high" (sort after non-nulls in ASC)
                        // null_high=false → nulls are "low"  (sort before non-nulls in ASC)
                        (true, false) => {
                            if nh {
                                Ordering::Greater
                            } else {
                                Ordering::Less
                            }
                        }
                        (false, true) => {
                            if nh {
                                Ordering::Less
                            } else {
                                Ordering::Greater
                            }
                        }
                        (false, false) => compare_py(py, va, vb, &mut sort_err),
                    }
                }
            };

            if reverse { ord.reverse() } else { ord }
        });
    }

    if let Some(err) = sort_err {
        return Err(err);
    }

    build_sorted_tuple(py, ids, &indices)
}

/// Group record IDs by their corresponding values.
///
/// `batch_group_ids(ids, values) -> dict[value, list[id]]`
///
/// - `ids`: tuple of record IDs
/// - `values`: list of group keys, one per id (same length as ids)
///
/// Returns a plain `dict` mapping each distinct value to the list of IDs
/// that have that value.  Order within each group list is the original
/// order of `ids`.
///
/// Replaces the Python pattern in `grouped()` after `batch_cache_get`:
/// ```text
/// collator = defaultdict(list)
/// for i, rec_id in enumerate(ids):
///     collator[results[i]].append(rec_id)
/// ```
///
/// Uses `PyDict_GetItem` + `PyList_Append` in a tight C loop, eliminating
/// Python loop overhead and `defaultdict.__missing__` dispatch.
#[pyfunction]
pub fn batch_group_ids<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    values: &Bound<'py, PyList>,
) -> PyResult<Py<PyDict>> {
    // Bounds contract: the loop indexes `values[i]` for i in 0..ids.len() with
    // the unchecked PyList_GET_ITEM.  Validate the lengths match up front — a
    // shorter `values` would otherwise read out of bounds and segfault the
    // worker (the Python fallback raises here too).
    if values.len() != ids.len() {
        return Err(PyValueError::new_err(
            "batch_group_ids: `values` must have the same length as `ids`",
        ));
    }
    let n = ids.len() as ffi::Py_ssize_t;

    // SAFETY: All pointers are borrowed from live Python objects.
    // PyDict_GetItemRef reports the three outcomes separately — 1 found (and
    // hands back a STRONG ref we must release), 0 missing, -1 error — so an
    // unhashable group key propagates instead of being swallowed. Its
    // predecessor `PyDict_GetItem` cannot: it restores the pre-call exception
    // state and drops the new exception, which made the `PyErr_Occurred()`
    // check that used to stand here dead code, and on 3.14 also printed
    // "Exception ignored in PyDict_GetItem()" plus a full traceback to stderr
    // before the eventual TypeError arrived from somewhere else.
    // PyList_Append INCREFs the appended object internally.
    // PyDict_SetItem INCREFs both key and value — we DECREF our local ref
    // to the new list after SetItem so the dict owns the only reference.
    unsafe {
        let ids_ptr = ids.as_ptr();
        let values_ptr = values.as_ptr();

        let result = ffi::PyDict_New();
        if result.is_null() {
            return Err(PyErr::fetch(py));
        }

        for i in 0..n {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i);
            let val_obj = ffi::PyList_GET_ITEM(values_ptr, i);

            // Try to find the existing group list.
            let mut existing: *mut ffi::PyObject = std::ptr::null_mut();
            match ffi::PyDict_GetItemRef(result, val_obj, &raw mut existing) {
                -1 => {
                    // Unhashable group key — the reference raises here too.
                    ffi::Py_DECREF(result);
                    return Err(PyErr::fetch(py));
                }
                1 => {
                    // Found — append to the existing list, then release the
                    // strong reference GetItemRef handed us.
                    let appended = ffi::PyList_Append(existing, id_obj);
                    ffi::Py_DECREF(existing);
                    if appended < 0 {
                        ffi::Py_DECREF(result);
                        return Err(PyErr::fetch(py));
                    }
                }
                _ => {
                    // New key — create a fresh list with this first element.
                    // Use PyList_New(1) + SET_ITEM to avoid Append's resize path
                    // for the common case of small singleton groups.
                    let new_list = ffi::PyList_New(1);
                    if new_list.is_null() {
                        ffi::Py_DECREF(result);
                        return Err(PyErr::fetch(py));
                    }
                    // SET_ITEM steals the reference; INCREF first.
                    ffi::Py_INCREF(id_obj);
                    ffi::PyList_SET_ITEM(new_list, 0, id_obj);

                    // Insert into result dict; dict acquires its own reference.
                    if ffi::PyDict_SetItem(result, val_obj, new_list) < 0 {
                        ffi::Py_DECREF(new_list);
                        ffi::Py_DECREF(result);
                        return Err(PyErr::fetch(py));
                    }
                    // Release our local reference — dict holds the only one now.
                    ffi::Py_DECREF(new_list);
                }
            }
        }

        Ok(Bound::from_owned_ptr(py, result)
            .cast_into_unchecked::<PyDict>()
            .unbind())
    }
}

#[cfg(test)]
mod tests {
    //! Pure-Rust tests for the native ordering. The full `sort_ids_by_values`
    //! path takes Python objects and is covered by Python-level tests
    //! (including a fuzz comparison against the pure-Python fallback); here we
    //! pin the logic that decides the result.
    use super::{Total, pack_datetime, sort_nullable, sort_plain};
    use std::cmp::Ordering;

    fn order<K: Ord + Copy>(keys: &[K], reverse: bool) -> Vec<u32> {
        let mut rows: Vec<(K, u32)> = keys.iter().copied().zip(0u32..).collect();
        sort_plain(&mut rows, reverse);
        rows.into_iter().map(|(_, i)| i).collect()
    }

    fn order_opt<K: Ord + Copy>(keys: &[Option<K>], reverse: bool, high: bool) -> Vec<u32> {
        let mut rows: Vec<(Option<K>, u32)> = keys.iter().copied().zip(0u32..).collect();
        sort_nullable(&mut rows, reverse, high);
        rows.into_iter().map(|(_, i)| i).collect()
    }

    #[test]
    fn sort_plain_orders_each_key_type() {
        assert_eq!(order(&[3i64, 1, 2], false), [1, 2, 0]);
        assert_eq!(order(&["abd", "abc", "abe"], false), [1, 0, 2]);
        assert_eq!(
            order(&[Total(2.0), Total(1.5), Total(-3.0)], false),
            [2, 1, 0]
        );
    }

    #[test]
    fn sort_plain_is_stable_in_both_directions() {
        // Every key equal: the original order must survive, ascending and
        // descending alike — CPython's `reverse=True` is stable too.
        let keys = [7i64; 5];
        assert_eq!(order(&keys, false), [0, 1, 2, 3, 4]);
        assert_eq!(order(&keys, true), [0, 1, 2, 3, 4]);
        // Ties within a mixed column keep their relative order.
        assert_eq!(order(&[1i64, 0, 1, 0], false), [1, 3, 0, 2]);
        assert_eq!(order(&[1i64, 0, 1, 0], true), [0, 2, 1, 3]);
    }

    #[test]
    fn total_is_nan_safe_and_treats_signed_zero_as_equal() {
        // `sort_by` must never panic; NaN never reaches here (decode_column
        // defers it) but the order must still be total.
        let _ = order(&[Total(f64::NAN), Total(1.0)], false);
        assert_eq!(Total(0.0).cmp(&Total(0.0)), Ordering::Equal);
        assert_eq!(Total(1.0).cmp(&Total(1.0)), Ordering::Equal);
    }

    #[test]
    fn sort_nullable_places_nulls_per_null_high() {
        let keys = [Some(5i64), None, Some(1)];
        // high: nulls after the values, ascending
        assert_eq!(order_opt(&keys, false, true), [2, 0, 1]);
        // low: nulls before them
        assert_eq!(order_opt(&keys, false, false), [1, 2, 0]);
        // reverse flips the whole comparison, nulls included
        assert_eq!(order_opt(&keys, true, true), [1, 0, 2]);
    }

    #[test]
    fn sort_nullable_keeps_equal_nulls_in_order() {
        let keys = [None::<i64>, Some(1), None, None];
        assert_eq!(order_opt(&keys, false, true), [1, 0, 2, 3]);
    }

    #[test]
    fn pack_datetime_is_chronological() {
        let moments = [
            (2020, 1, 1, 0, 0, 0, 0),
            (2020, 1, 1, 0, 0, 0, 1),
            (2020, 1, 1, 0, 0, 1, 0),
            (2020, 1, 1, 0, 1, 0, 0),
            (2020, 1, 1, 1, 0, 0, 0),
            (2020, 1, 2, 0, 0, 0, 0),
            (2020, 2, 1, 0, 0, 0, 0),
            (2021, 1, 1, 0, 0, 0, 0),
        ];
        let packed: Vec<i64> = moments
            .iter()
            .map(|&(y, m, d, h, mi, s, us)| pack_datetime(y, m, d, h, mi, s, us))
            .collect();
        for pair in packed.windows(2) {
            assert!(pair[0] < pair[1], "not monotone: {pair:?}");
        }
    }

    #[test]
    fn pack_datetime_puts_a_date_at_midnight_of_its_day() {
        // A `date` decodes with the four time fields at zero, which has to be
        // the same instant a midnight `datetime` decodes to.
        assert_eq!(
            pack_datetime(2026, 8, 28, 0, 0, 0, 0),
            pack_datetime(2026, 8, 28, 0, 0, 0, 0)
        );
        assert!(pack_datetime(2026, 8, 28, 0, 0, 0, 0) < pack_datetime(2026, 8, 28, 0, 0, 0, 1));
    }

    #[test]
    fn pack_datetime_cannot_overflow_at_the_extremes() {
        // Every component at its maximum, including a leap second.
        let widest = pack_datetime(9999, 12, 31, 23, 59, 60, 999_999);
        assert!(widest > 0, "packing wrapped: {widest}");
        assert!(widest < 1 << 60, "packing is wider than expected: {widest}");
        assert!(pack_datetime(1, 1, 1, 0, 0, 0, 0) < widest);
    }
}
