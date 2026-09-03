pub struct LineCursor<'a> {
    content: &'a [u8],

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

    pub fn restart(&mut self) {
        self.offset = 0;
        self.line = 1;
    }

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

    use super::LineCursor;

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
            [15, 9, 8, 4, 0].as_slice(),
            [4, 0, 15, 8, 9, 4].as_slice(),
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
