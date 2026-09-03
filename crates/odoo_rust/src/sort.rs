use std::cmp::Ordering;

use pyo3::exceptions::PyValueError;
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyDate, PyDateAccess, PyDateTime, PyDict, PyFloat, PyInt, PyList, PyString,
    PyTimeAccess, PyTuple, PyTzInfoAccess,
};

type Values<'a, 'py> = [Borrowed<'a, 'py, PyAny>];

#[pyfunction]
#[pyo3(signature = (ids, values, reverse, null_high = None))]
pub fn sort_ids_by_values<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    values: &Bound<'py, PyList>,
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Py<PyTuple>> {
    if values.len() != ids.len() {
        return Err(PyValueError::new_err(
            "sort_ids_by_values: `values` must have the same length as `ids`",
        ));
    }

    let n = ids.len();
    if n <= 1 {
        return Ok(ids.clone().unbind());
    }

    let holder: Vec<Borrowed<'_, 'py, PyAny>> = unsafe {
        let values_ptr = values.as_ptr();
        (0..n)
            .map(|i| Borrowed::from_ptr(py, ffi::PyList_GET_ITEM(values_ptr, i as ffi::Py_ssize_t)))
            .collect()
    };
    if let Some(order) = sort_native(&holder, reverse, null_high) {
        return build_sorted_tuple(py, ids, &order);
    }
    drop(holder);
    let strong: Vec<Bound<'py, PyAny>> = (0..n)
        .map(|i| values.get_item(i))
        .collect::<PyResult<_>>()?;
    sort_objects_to_tuple(py, ids, &strong, reverse, null_high)
}

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

    let holder: Vec<Borrowed<'_, 'py, PyAny>> = unsafe {
        let cache_ptr = field_cache.as_ptr();
        let ids_ptr = ids.as_ptr();
        let pending_ptr = pending.as_ptr();
        let mut holder = Vec::with_capacity(n);
        for i in 0..n {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i as ffi::Py_ssize_t);

            let Some(v) = crate::cache::cache_probe(cache_ptr, id_obj, pending_ptr) else {
                return Ok(None);
            };
            holder.push(Borrowed::from_ptr(py, v.as_ptr()));
        }
        holder
    };

    if n <= 1 {
        return Ok(Some(ids.clone().unbind()));
    }
    if let Some(order) = sort_native(&holder, reverse, null_high) {
        return build_sorted_tuple(py, ids, &order).map(Some);
    }
    drop(holder);

    let strong: Vec<Bound<'py, PyAny>> = unsafe {
        let cache_ptr = field_cache.as_ptr();
        let ids_ptr = ids.as_ptr();
        let pending_ptr = pending.as_ptr();
        let mut strong = Vec::with_capacity(n);
        for i in 0..n {
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i as ffi::Py_ssize_t);
            let Some(v) = crate::cache::cache_probe(cache_ptr, id_obj, pending_ptr) else {
                return Ok(None);
            };
            strong.push(Bound::from_borrowed_ptr(py, v.as_ptr()));
        }
        strong
    };
    sort_objects_to_tuple(py, ids, &strong, reverse, null_high).map(Some)
}

fn sort_native(
    holder: &Values<'_, '_>,
    reverse: bool,
    null_high: Option<bool>,
) -> Option<Vec<usize>> {
    let mut column = decode_column(holder, null_high.is_some())?;
    Some(sort_column(&mut column, reverse, null_high))
}

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

#[derive(Clone, Copy)]
struct StrKey<'a> {
    prefix: u64,
    text: &'a str,
}

impl<'a> StrKey<'a> {
    #[inline]
    fn new(text: &'a str) -> Self {
        let bytes = text.as_bytes();
        let taken = bytes.len().min(8);
        let mut buf = [0u8; 8];
        buf[..taken].copy_from_slice(&bytes[..taken]);
        Self {
            prefix: u64::from_be_bytes(buf),
            text,
        }
    }
}

impl Ord for StrKey<'_> {
    #[inline]
    fn cmp(&self, other: &Self) -> Ordering {
        match self.prefix.cmp(&other.prefix) {
            Ordering::Equal => {
                if self.text.len() <= 8 && other.text.len() <= 8 {
                    self.text.len().cmp(&other.text.len())
                } else {
                    self.text.cmp(other.text)
                }
            }
            ord => ord,
        }
    }
}

impl PartialOrd for StrKey<'_> {
    #[inline]
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl PartialEq for StrKey<'_> {
    #[inline]
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other) == Ordering::Equal
    }
}

impl Eq for StrKey<'_> {}

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

enum Column<'a> {
    Int(Vec<(i64, u32)>),
    Float(Vec<(Total, u32)>),
    Str(Vec<(StrKey<'a>, u32)>),
    Date(Vec<(i64, u32)>),
    IntOpt(Vec<(Option<i64>, u32)>),
    FloatOpt(Vec<(Option<Total>, u32)>),
    StrOpt(Vec<(Option<StrKey<'a>>, u32)>),
    DateOpt(Vec<(Option<i64>, u32)>),
}

fn sort_plain<K: Ord>(rows: &mut [(K, u32)], reverse: bool) {
    if reverse {
        rows.sort_by(|a, b| b.0.cmp(&a.0));
    } else {
        rows.sort_by(|a, b| a.0.cmp(&b.0));
    }
}

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

fn sort_column(column: &mut Column<'_>, reverse: bool, null_high: Option<bool>) -> Vec<usize> {
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

#[derive(Clone, Copy)]
enum Kind {
    Int,
    Float,
    Str,
    DateTime,
    Date,
}

impl Kind {
    fn of(value: &Bound<'_, PyAny>) -> Option<Self> {
        if value.is_exact_instance_of::<PyString>() {
            Some(Self::Str)
        } else if value.is_exact_instance_of::<PyFloat>() {
            Some(Self::Float)
        } else if value.is_exact_instance_of::<PyInt>() || value.is_exact_instance_of::<PyBool>() {
            Some(Self::Int)
        } else if value.is_exact_instance_of::<PyDateTime>() {
            Some(Self::DateTime)
        } else if value.is_exact_instance_of::<PyDate>() {
            Some(Self::Date)
        } else {
            None
        }
    }
}

#[inline]
fn int_key(value: &Bound<'_, PyAny>) -> Option<i64> {
    if value.is_exact_instance_of::<PyInt>() {
        let mut overflow = 0;

        let int = unsafe { ffi::PyLong_AsLongLongAndOverflow(value.as_ptr(), &raw mut overflow) };
        (overflow == 0).then_some(int)
    } else if let Ok(flag) = value.cast_exact::<PyBool>() {
        Some(i64::from(flag.is_true()))
    } else {
        None
    }
}

#[inline]
fn float_key(value: &Bound<'_, PyAny>) -> Option<Total> {
    let float = value.cast_exact::<PyFloat>().ok()?.value();
    if float.is_nan() {
        return None;
    }
    Some(Total(if float == 0.0 { 0.0 } else { float }))
}

#[inline]
fn str_key<'a>(value: &'a Bound<'_, PyAny>) -> Option<StrKey<'a>> {
    Some(StrKey::new(
        value.cast_exact::<PyString>().ok()?.to_str().ok()?,
    ))
}

#[inline]
fn datetime_key(value: &Bound<'_, PyAny>) -> Option<i64> {
    let dt = value.cast_exact::<PyDateTime>().ok()?;
    if dt.get_tzinfo().is_some() {
        return None;
    }
    Some(pack_datetime(
        dt.get_year(),
        dt.get_month().into(),
        dt.get_day().into(),
        dt.get_hour().into(),
        dt.get_minute().into(),
        dt.get_second().into(),
        dt.get_microsecond(),
    ))
}

#[inline]
fn date_key(value: &Bound<'_, PyAny>) -> Option<i64> {
    let date = value.cast_exact::<PyDate>().ok()?;
    Some(pack_datetime(
        date.get_year(),
        date.get_month().into(),
        date.get_day().into(),
        0,
        0,
        0,
        0,
    ))
}

fn decode<'a, 'py, K>(
    holder: &'a Values<'a, 'py>,
    key: impl Fn(&'a Bound<'py, PyAny>) -> Option<K>,
) -> Option<Vec<(K, u32)>> {
    let mut rows = Vec::with_capacity(holder.len());
    for (index, value) in holder.iter().enumerate() {
        rows.push((key(value)?, index as u32));
    }
    Some(rows)
}

fn decode_nullable<'a, 'py, K>(
    holder: &'a Values<'a, 'py>,
    is_null: impl Fn(&Bound<'py, PyAny>) -> bool,
    key: impl Fn(&'a Bound<'py, PyAny>) -> Option<K>,
) -> Option<Vec<(Option<K>, u32)>> {
    let mut rows = Vec::with_capacity(holder.len());
    for (index, value) in holder.iter().enumerate() {
        let index = index as u32;
        if is_null(value) {
            rows.push((None, index));
        } else {
            rows.push((Some(key(value)?), index));
        }
    }
    Some(rows)
}

fn decode_column<'a, 'py>(holder: &'a Values<'a, 'py>, null_aware: bool) -> Option<Column<'a>> {
    let false_ptr = unsafe { ffi::Py_False() };
    let is_null =
        |value: &Bound<'py, PyAny>| null_aware && (value.is_none() || value.as_ptr() == false_ptr);

    let kind = match holder.iter().find(|value| !is_null(value)) {
        Some(first) => Kind::of(first)?,
        None => Kind::Int,
    };
    Some(match (kind, null_aware) {
        (Kind::Int, false) => Column::Int(decode(holder, int_key)?),
        (Kind::Float, false) => Column::Float(decode(holder, float_key)?),
        (Kind::Str, false) => Column::Str(decode(holder, str_key)?),
        (Kind::DateTime, false) => Column::Date(decode(holder, datetime_key)?),
        (Kind::Date, false) => Column::Date(decode(holder, date_key)?),
        (Kind::Int, true) => Column::IntOpt(decode_nullable(holder, is_null, int_key)?),
        (Kind::Float, true) => Column::FloatOpt(decode_nullable(holder, is_null, float_key)?),
        (Kind::Str, true) => Column::StrOpt(decode_nullable(holder, is_null, str_key)?),
        (Kind::DateTime, true) => Column::DateOpt(decode_nullable(holder, is_null, datetime_key)?),
        (Kind::Date, true) => Column::DateOpt(decode_nullable(holder, is_null, date_key)?),
    })
}

fn sort_objects_to_tuple<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    holder: &[Bound<'py, PyAny>],
    reverse: bool,
    null_high: Option<bool>,
) -> PyResult<Py<PyTuple>> {
    let keys = match null_high {
        None => PyList::new(py, holder)?,
        Some(high) => {
            let (null_rank, val_rank): (u8, u8) = if high { (1, 0) } else { (0, 1) };
            let false_ptr = unsafe { ffi::Py_False() };
            let empty = PyString::new(py, "").into_any();
            PyList::new(
                py,
                holder.iter().map(|value| {
                    if value.is_none() || value.as_ptr() == false_ptr {
                        (null_rank, &empty)
                    } else {
                        (val_rank, value)
                    }
                }),
            )?
        }
    };
    let order = PyList::new(py, 0..holder.len())?;
    let kwargs = PyDict::new(py);
    kwargs.set_item(
        pyo3::intern!(py, "key"),
        keys.getattr(pyo3::intern!(py, "__getitem__"))?,
    )?;
    kwargs.set_item(pyo3::intern!(py, "reverse"), reverse)?;
    order.call_method(pyo3::intern!(py, "sort"), (), Some(&kwargs))?;
    build_sorted_tuple(py, ids, &order.extract::<Vec<usize>>()?)
}

#[pyfunction]
pub fn batch_group_ids<'py>(
    py: Python<'py>,
    ids: &Bound<'py, PyTuple>,
    values: &Bound<'py, PyList>,
) -> PyResult<Py<PyDict>> {
    if values.len() != ids.len() {
        return Err(PyValueError::new_err(
            "batch_group_ids: `values` must have the same length as `ids`",
        ));
    }
    let n = ids.len() as ffi::Py_ssize_t;

    unsafe {
        let ids_ptr = ids.as_ptr();
        let values_ptr = values.as_ptr();

        let result = ffi::PyDict_New();
        if result.is_null() {
            return Err(PyErr::fetch(py));
        }

        for i in 0..n {
            if ffi::PyList_GET_SIZE(values_ptr) != n {
                ffi::Py_DECREF(result);
                return Err(PyValueError::new_err(
                    "batch_group_ids: `values` changed length during the grouping",
                ));
            }
            let id_obj = ffi::PyTuple_GET_ITEM(ids_ptr, i);
            let val_obj = ffi::PyList_GET_ITEM(values_ptr, i);
            let val_guard = Bound::from_borrowed_ptr(py, val_obj);
            let val_obj = val_guard.as_ptr();

            let mut existing: *mut ffi::PyObject = std::ptr::null_mut();
            match ffi::PyDict_GetItemRef(result, val_obj, &raw mut existing) {
                -1 => {
                    ffi::Py_DECREF(result);
                    return Err(PyErr::fetch(py));
                }
                1 => {
                    let appended = ffi::PyList_Append(existing, id_obj);
                    ffi::Py_DECREF(existing);
                    if appended < 0 {
                        ffi::Py_DECREF(result);
                        return Err(PyErr::fetch(py));
                    }
                }
                _ => {
                    let new_list = ffi::PyList_New(1);
                    if new_list.is_null() {
                        ffi::Py_DECREF(result);
                        return Err(PyErr::fetch(py));
                    }
                    ffi::Py_INCREF(id_obj);
                    ffi::PyList_SET_ITEM(new_list, 0, id_obj);

                    if ffi::PyDict_SetItem(result, val_obj, new_list) < 0 {
                        ffi::Py_DECREF(new_list);
                        ffi::Py_DECREF(result);
                        return Err(PyErr::fetch(py));
                    }
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
    use super::{StrKey, Total, pack_datetime, sort_nullable, sort_plain};
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
        let keys = [7i64; 5];
        assert_eq!(order(&keys, false), [0, 1, 2, 3, 4]);
        assert_eq!(order(&keys, true), [0, 1, 2, 3, 4]);
        assert_eq!(order(&[1i64, 0, 1, 0], false), [1, 3, 0, 2]);
        assert_eq!(order(&[1i64, 0, 1, 0], true), [0, 2, 1, 3]);
    }

    #[test]
    fn total_is_nan_safe_and_treats_signed_zero_as_equal() {
        let _ = order(&[Total(f64::NAN), Total(1.0)], false);
        assert_eq!(Total(0.0).cmp(&Total(0.0)), Ordering::Equal);
        assert_eq!(Total(1.0).cmp(&Total(1.0)), Ordering::Equal);
    }

    #[test]
    fn sort_nullable_places_nulls_per_null_high() {
        let keys = [Some(5i64), None, Some(1)];

        assert_eq!(order_opt(&keys, false, true), [2, 0, 1]);

        assert_eq!(order_opt(&keys, false, false), [1, 2, 0]);

        assert_eq!(order_opt(&keys, true, true), [1, 0, 2]);
    }

    #[test]
    fn sort_nullable_keeps_equal_nulls_in_order() {
        let keys = [None::<i64>, Some(1), None, None];
        assert_eq!(order_opt(&keys, false, true), [1, 0, 2, 3]);
    }

    #[test]
    fn strkey_orders_exactly_like_str() {
        let corpus = [
            "",
            "a",
            "ab",
            "abc",
            "abcdefg",
            "abcdefgh",
            "abcdefghi",
            "abcdefghZ",
            "abcdefgh\u{0}",
            "abc\u{0}",
            "abc\u{0}\u{0}",
            "\u{0}",
            "\u{0}\u{0}",
            "a\u{0}b",
            "a\u{0}b\u{0}",
            "zzzzzzzzzzzz",
            "\u{e9}",
            "\u{1f600}",
        ];
        for a in corpus {
            for b in corpus {
                assert_eq!(
                    StrKey::new(a).cmp(&StrKey::new(b)),
                    a.cmp(b),
                    "StrKey disagrees with str on {a:?} vs {b:?}"
                );
            }
        }
    }

    #[test]
    fn strkey_sorts_a_column_like_python_would() {
        let column = ["abc\u{0}", "abc", "ab", "abcdefghi", "abcdefgh"];
        let keys: Vec<StrKey<'_>> = column.iter().map(|s| StrKey::new(s)).collect();
        let mut expected: Vec<&str> = column.to_vec();
        expected.sort_unstable();
        assert_eq!(
            order(&keys, false)
                .into_iter()
                .map(|i| column[i as usize])
                .collect::<Vec<_>>(),
            expected
        );
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
        assert_eq!(
            pack_datetime(2026, 8, 28, 0, 0, 0, 0),
            pack_datetime(2026, 8, 28, 0, 0, 0, 0)
        );
        assert!(pack_datetime(2026, 8, 28, 0, 0, 0, 0) < pack_datetime(2026, 8, 28, 0, 0, 0, 1));
    }

    #[test]
    fn pack_datetime_cannot_overflow_at_the_extremes() {
        let widest = pack_datetime(9999, 12, 31, 23, 59, 60, 999_999);
        assert!(widest > 0, "packing wrapped: {widest}");
        assert!(widest < 1 << 60, "packing is wider than expected: {widest}");
        assert!(pack_datetime(1, 1, 1, 0, 0, 0, 0) < widest);
    }
}
