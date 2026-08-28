//! Byte offset to 1-based line number, without re-scanning the file.

/// Turns ascending byte offsets into 1-based line numbers without allocating.
///
/// The naive `memchr_iter(b'\n', &content[..offset]).count()` per match is
/// O(file) per hit and so O(file × hits) per file — quadratic in a file that
/// matches often. Measured on a synthetic file with one match per line,
/// quadrupling the matches quadrupled the *cost per match*: 8k matches took
/// 23 ms, 32k took 191 ms and 128k took 3.0 s.
///
/// Both scanners walk one pattern's matches in ascending offset order, so the
/// newlines between two consecutive matches can be counted once and never
/// re-counted: the whole file costs O(bytes) per pattern. A precomputed
/// `Vec` of every newline offset would also be linear, but it pays for the
/// index on *every* file, and the files these gates scan overwhelmingly
/// contain no match at all — measured over the four repos, indexing eagerly
/// cost +16% peak RSS and +13% wall clock for a scan that found nothing.
/// A cursor costs zero until the first match.
pub struct LineCursor<'a> {
    content: &'a [u8],
    /// Last offset resolved, and its line. `(0, 1)` before the first call.
    offset: usize,
    line: usize,
}

impl<'a> LineCursor<'a> {
    pub fn new(content: &'a [u8]) -> Self {
        Self {
            content,
            offset: 0,
            line: 1,
        }
    }

    /// Restart at the top of the buffer, for the next pattern's matches.
    pub fn restart(&mut self) {
        self.offset = 0;
        self.line = 1;
    }

    /// 1-based line number holding byte `offset`.
    ///
    /// Fast when `offset` is at or after the previous call's, which is how
    /// both callers use it. A lower offset is not a caller error to punish
    /// with a panic — `&content[self.offset..offset]` would panic on an
    /// inverted range, and a panic inside a walker thread is precisely the
    /// failure that used to hang this module — so it simply rescans.
    pub fn line_of(&mut self, offset: usize) -> usize {
        if offset < self.offset {
            self.restart();
        }
        self.line += memchr::memchr_iter(b'\n', &self.content[self.offset..offset]).count();
        self.offset = offset;
        self.line
    }
}

#[cfg(test)]
mod tests {
    //! The scanners themselves take Python arguments and walk a real tree;
    //! they are covered by the Python-level tests in `odoo/libs/lint/tests`.
    use super::LineCursor;

    /// What the cursor replaced, kept as the oracle it has to agree with.
    fn naive(content: &[u8], offset: usize) -> usize {
        memchr::memchr_iter(b'\n', &content[..offset]).count() + 1
    }

    #[test]
    fn line_of_matches_a_naive_newline_count_at_every_offset() {
        let content = b"alpha\nbeta\n\ngamma";
        let mut cursor = LineCursor::new(content);
        for offset in 0..=content.len() {
            assert_eq!(
                cursor.line_of(offset),
                naive(content, offset),
                "offset {offset}"
            );
        }
    }

    #[test]
    fn line_of_first_byte_is_line_one() {
        assert_eq!(LineCursor::new(b"").line_of(0), 1);
        assert_eq!(LineCursor::new(b"x").line_of(0), 1);
    }

    #[test]
    fn line_of_byte_after_a_newline_is_the_next_line() {
        // "a\nb": offset 0 -> 1, offset 1 (the \n itself) -> 1, offset 2 -> 2
        let mut cursor = LineCursor::new(b"a\nb");
        assert_eq!(cursor.line_of(0), 1);
        assert_eq!(cursor.line_of(1), 1);
        assert_eq!(cursor.line_of(2), 2);
    }

    #[test]
    fn restart_rewinds_for_the_next_pattern() {
        let content = b"a\nb\nc";
        let mut cursor = LineCursor::new(content);
        assert_eq!(cursor.line_of(4), 3);
        cursor.restart();
        assert_eq!(cursor.line_of(0), 1);
        assert_eq!(cursor.line_of(2), 2);
    }

    #[test]
    fn a_descending_offset_rescans_instead_of_panicking() {
        // The range `&content[self.offset..offset]` would panic inverted, and a
        // panic in a walker thread is what used to hang the whole scan.
        let content = b"a\nb\nc\nd";
        let mut cursor = LineCursor::new(content);
        assert_eq!(cursor.line_of(6), 4);
        assert_eq!(
            cursor.line_of(2),
            2,
            "must rescan, not panic or under-count"
        );
        assert_eq!(cursor.line_of(0), 1);
    }

    #[test]
    fn every_offset_order_agrees_with_the_naive_count() {
        let content = b"one\ntwo\n\nthree\nfour\n";
        for &probes in &[
            [0usize, 4, 8, 9, 15].as_slice(),
            [15, 9, 8, 4, 0].as_slice(),    // fully descending
            [4, 0, 15, 8, 9, 4].as_slice(), // arbitrary
        ] {
            let mut cursor = LineCursor::new(content);
            for &offset in probes {
                assert_eq!(
                    cursor.line_of(offset),
                    naive(content, offset),
                    "offset {offset}"
                );
            }
        }
    }
}
