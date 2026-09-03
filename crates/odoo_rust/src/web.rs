use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyList, PyString};

use crate::pyutil::is_none_or_false;

#[pyfunction]
pub fn csv_export(headers: &Bound<'_, PyList>, rows: &Bound<'_, PyList>) -> PyResult<Vec<u8>> {
    let n_rows = rows.len();
    let n_cols = headers.len();

    let mut buf = String::with_capacity(n_cols.max(1) * 16);

    for i in 0..n_cols {
        if i > 0 {
            buf.push(',');
        }
        let header = headers.get_item(i)?;
        if header.is_none() {
            write_quoted(&mut buf, "");
        } else if let Ok(text) = header.cast::<PyString>() {
            write_quoted(&mut buf, text.to_str()?);
        } else {
            write_quoted(&mut buf, header.str()?.to_str()?);
        }
    }
    buf.push_str("\r\n");

    for row_idx in 0..n_rows {
        let row = rows.get_item(row_idx)?;
        let row_start = buf.len();
        if let Ok(row_list) = row.cast::<PyList>() {
            for col_idx in 0..row_list.len() {
                if col_idx > 0 {
                    buf.push(',');
                }
                write_cell(&mut buf, &row_list.get_item(col_idx)?)?;
            }
        } else {
            for (col_idx, cell) in row.try_iter()?.enumerate() {
                if col_idx > 0 {
                    buf.push(',');
                }
                write_cell(&mut buf, &cell?)?;
            }
        }
        buf.push_str("\r\n");

        if row_idx == 0 {
            let per_row = buf.len() - row_start;
            buf.reserve(per_row.saturating_mul(n_rows - 1) / 8 * 9);
        }
    }

    Ok(buf.into_bytes())
}

fn write_cell(buf: &mut String, cell: &Bound<'_, PyAny>) -> PyResult<()> {
    if is_none_or_false(cell) {
        buf.push_str("\"\"");
        return Ok(());
    }

    if let Ok(s) = cell.cast::<PyString>() {
        let val = s.to_str()?;
        write_string_cell(buf, val);
        return Ok(());
    }

    if let Ok(b) = cell.cast::<PyBytes>() {
        let raw = b.as_bytes();
        let val = match std::str::from_utf8(raw) {
            Ok(val) => val,
            Err(e) => {
                return Err(
                    pyo3::exceptions::PyUnicodeDecodeError::new_utf8(cell.py(), raw, e)?.into(),
                );
            }
        };
        write_string_cell(buf, val);
        return Ok(());
    }

    let s = cell.str()?;
    write_quoted(buf, s.to_str()?);
    Ok(())
}

#[inline]
fn write_string_cell(buf: &mut String, val: &str) {
    if !val.is_empty() && matches!(val.as_bytes()[0], b'=' | b'-' | b'+' | b'@' | b'\t' | b'\r') {
        buf.push('"');
        buf.push('\'');
        write_escaped(buf, val);
        buf.push('"');
    } else {
        write_quoted(buf, val);
    }
}

#[inline]
fn write_quoted(buf: &mut String, s: &str) {
    buf.push('"');
    write_escaped(buf, s);
    buf.push('"');
}

#[inline]
fn write_escaped(buf: &mut String, s: &str) {
    if s.contains('"') {
        buf.push_str(&s.replace('"', "\"\""));
    } else {
        buf.push_str(s);
    }
}

#[cfg(test)]
mod tests {
    use super::{write_escaped, write_quoted, write_string_cell};

    fn quoted(s: &str) -> String {
        let mut buf = String::new();
        write_quoted(&mut buf, s);
        buf
    }

    fn string_cell(s: &str) -> String {
        let mut buf = String::new();
        write_string_cell(&mut buf, s);
        buf
    }

    #[test]
    fn escaped_plain_is_verbatim() {
        let mut buf = String::new();
        write_escaped(&mut buf, "hello");
        assert_eq!(buf, "hello");
    }

    #[test]
    fn escaped_doubles_embedded_quotes() {
        let mut buf = String::new();
        write_escaped(&mut buf, r#"a"b"c"#);
        assert_eq!(buf, r#"a""b""c"#);
    }

    #[test]
    fn quoted_wraps_and_escapes() {
        assert_eq!(quoted("plain"), r#""plain""#);
        assert_eq!(quoted(r#"a"b"#), r#""a""b""#);
        assert_eq!(quoted(""), r#""""#);
    }

    #[test]
    fn string_cell_plain_is_quoted_only() {
        assert_eq!(string_cell("safe"), r#""safe""#);

        assert_eq!(string_cell("a=b"), r#""a=b""#);
    }

    #[test]
    fn string_cell_guards_every_leading_formula_char() {
        for prefix in ["=", "-", "+", "@", "\t", "\r"] {
            let out = string_cell(&format!("{prefix}cmd"));
            assert_eq!(out, format!("\"'{prefix}cmd\""), "prefix {prefix:?}");
        }
    }

    #[test]
    fn string_cell_empty_is_not_guarded() {
        assert_eq!(string_cell(""), r#""""#);
    }

    #[test]
    fn string_cell_combines_guard_and_quote_escaping() {
        assert_eq!(string_cell(r#"=a"b"#), r#""'=a""b""#);
    }
}
