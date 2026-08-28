"""Semantics of the parallel lint scanner.

`scan_byte_patterns` / `scan_regex_patterns` are the measurement behind four
ratcheted `test_lint` gates, so what they *count* is what those floors mean.
The suite had no Python-level coverage at all until these; the gates it feeds
all read zero today, which is exactly the state in which a miscount is
invisible.
"""

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from odoo.libs.lint import scan_byte_patterns, scan_regex_patterns

# Built, never spelled. This file lives inside the tree `test_lint`'s
# TestConflictMarkers scans, and a literal marker in a fixture is a finding
# against a gate whose floor is zero — the suite would fail the gate it exists
# to test. (It did: five findings, on the two lines that spelled them out.)
OPEN = b"<" * 7
CLOSE = b">" * 7


class _ScanCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, name: str, content: bytes | str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
        return path

    def bytes_scan(self, patterns, extensions=(".py",), exclude=()):
        return sorted(
            scan_byte_patterns(
                [str(self.root)], list(extensions), list(patterns), list(exclude)
            )
        )

    def regex_scan(self, patterns, extensions=(".js",), exclude=()):
        return sorted(
            scan_regex_patterns(
                [str(self.root)], list(extensions), list(patterns), list(exclude)
            )
        )


class TestByteScanReportingUnit(_ScanCase):
    """One finding per (file, line, pattern) — not per occurrence."""

    def test_repeated_pattern_on_one_line_is_one_finding(self):
        """`NUL = [b"\\x00"]` against a line of three NULs reported three.

        The callers count the findings against a ratchet floor and describe
        them as "source file line(s)", so a run of a repeated byte inflated the
        count by its own length.
        """
        path = self.write("a.py", b"clean\nx\x00y\x00z\x00\nclean\n")
        self.assertEqual(self.bytes_scan([b"\x00"]), [(str(path), 2, 0)])

    def test_overlapping_matches_are_not_distinct_findings(self):
        """A run of ten `<` matched `b"<" * 7` four times.

        The search restarted one byte past each match rather than past the
        match itself, so every shifted window counted again.
        """
        path = self.write("a.py", b"x\n" + b"<" * 10 + b"\n")
        self.assertEqual(self.bytes_scan([OPEN]), [(str(path), 2, 0)])

    def test_the_same_pattern_on_two_lines_is_two_findings(self):
        path = self.write(
            "a.py", OPEN + b" HEAD\nmid\n" + CLOSE + b" other\n" + OPEN + b" again\n"
        )
        self.assertEqual(
            self.bytes_scan([OPEN, CLOSE]),
            [(str(path), 1, 0), (str(path), 3, 1), (str(path), 4, 0)],
        )

    def test_two_different_patterns_on_one_line_are_two_findings(self):
        """Dedup is per pattern; a line can genuinely offend twice."""
        path = self.write("a.py", OPEN + b" and " + CLOSE + b" together\n")
        self.assertEqual(
            self.bytes_scan([OPEN, CLOSE]),
            [(str(path), 1, 0), (str(path), 1, 1)],
        )


class TestByteScanLineNumbers(_ScanCase):
    def test_line_numbers_are_one_based(self):
        path = self.write("a.py", b"hit\n")
        self.assertEqual(self.bytes_scan([b"hit"]), [(str(path), 1, 0)])

    def test_a_match_on_the_last_line_without_a_trailing_newline(self):
        path = self.write("a.py", b"one\ntwo\nhit")
        self.assertEqual(self.bytes_scan([b"hit"]), [(str(path), 3, 0)])

    def test_a_match_immediately_after_a_newline(self):
        path = self.write("a.py", b"\nhit\n")
        self.assertEqual(self.bytes_scan([b"hit"]), [(str(path), 2, 0)])

    def test_blank_lines_are_counted(self):
        path = self.write("a.py", b"\n\n\nhit\n")
        self.assertEqual(self.bytes_scan([b"hit"]), [(str(path), 4, 0)])


class TestScanSelection(_ScanCase):
    def test_extensions_match_with_or_without_the_leading_dot(self):
        path = self.write("a.py", b"hit\n")
        self.assertEqual(
            self.bytes_scan([b"hit"], extensions=["py"]), [(str(path), 1, 0)]
        )
        self.assertEqual(
            self.bytes_scan([b"hit"], extensions=[".py"]), [(str(path), 1, 0)]
        )

    def test_other_extensions_are_not_read(self):
        self.write("a.txt", b"hit\n")
        self.assertEqual(self.bytes_scan([b"hit"]), [])

    def test_excluded_directories_are_not_descended(self):
        self.write("node_modules/a.py", b"hit\n")
        kept = self.write("src/a.py", b"hit\n")
        self.assertEqual(
            self.bytes_scan([b"hit"], exclude=["node_modules"]), [(str(kept), 1, 0)]
        )

    def test_no_roots_scans_nothing(self):
        self.assertEqual(scan_byte_patterns([], [".py"], [b"hit"], []), [])
        self.assertEqual(scan_regex_patterns([], [".js"], ["hit"], []), [])

    def test_an_empty_pattern_is_rejected(self):
        """An empty needle used to HANG the interpreter, not just misbehave.

        It matches at every offset, so the search walked `start` one byte past
        the end of the buffer and `&content[start..]` panicked with `range
        start index 10 out of range for slice of length 9`. The panic was
        inside an `ignore` worker thread, which re-panicked unwrapping it, and
        `WalkParallel::run` never returned — with the GIL released, so the
        Python call blocked forever with no exception and nothing to interrupt.
        A `test_lint` gate handed an empty pattern would hang CI rather than
        fail it. Rejecting the input up front is the only place this can be
        caught: advancing by the pattern's own length, which is what fixed the
        overlap above, is a zero-length advance here.
        """
        self.write("a.py", b"anything\n")
        with self.assertRaises(ValueError):
            self.bytes_scan([b""])

    def test_an_invalid_regex_is_rejected(self):
        with self.assertRaises(ValueError):
            self.regex_scan(["(unclosed"])


class TestRegexScan(_ScanCase):
    def test_two_matches_on_one_line_are_two_findings(self):
        """Unlike the byte scanner, a regex hit carries its matched text.

        Two matches on a line are two distinguishable findings, and
        `test_jstranslate` prints that text — collapsing them would drop an
        offending string from the report to fix an inflation bug that only the
        byte scanner ever had.
        """
        path = self.write("a.js", "_('a'); _('b')\nplain\n_('c')\n")
        self.assertEqual(
            self.regex_scan([r"\b_\(\s*'"]),
            [
                (str(path), 1, 0, "_('"),
                (str(path), 1, 0, "_('"),
                (str(path), 3, 0, "_('"),
            ],
        )

    def test_each_match_reports_its_own_text(self):
        path = self.write("a.js", "_t(`one`); _t(`two`)\n")
        self.assertEqual(
            self.regex_scan([r"_t\(`[^`]*`\)"]),
            [(str(path), 1, 0, "_t(`one`)"), (str(path), 1, 0, "_t(`two`)")],
        )

    def test_the_matched_text_is_returned(self):
        path = self.write("a.js", "const x = _t(`hello`);\n")
        self.assertEqual(
            self.regex_scan([r"(?s)_t\(\s*`.*?`\s*\)"]),
            [(str(path), 1, 0, "_t(`hello`)")],
        )

    def test_a_dotall_match_is_reported_at_its_starting_line(self):
        path = self.write("a.js", "one\n_t(`start\nend`)\nlast\n")
        [(_, line, _, _)] = self.regex_scan([r"(?s)_t\(\s*`.*?`\s*\)"])
        self.assertEqual((str(path), line), (str(path), 2))

    def test_a_file_with_invalid_utf8_still_reports_real_line_numbers(self):
        """Lossy decoding replaces bytes but never adds or removes a newline."""
        path = self.write("a.js", b"one\n\xff\xfe bad bytes\nhit here\n")
        self.assertEqual(self.regex_scan(["hit"]), [(str(path), 3, 0, "hit")])


class TestScanScales(_ScanCase):
    def test_line_numbering_is_linear_in_the_number_of_matches(self):
        """Counting newlines from the start of the file for every match made
        one file O(size x matches).

        Measured before the fix on one match per line: 8k matches 23 ms, 32k
        191 ms, 128k 3.0 s — 16x the cost for 4x the input, twice in a row. The
        assertion is deliberately loose (it is a wall-clock test on a shared
        box); quadratic growth exceeds it by more than an order of magnitude.
        """

        def measure(n: int) -> float:
            self.write("q.py", b"".join(b"\x00 line %d\n" % i for i in range(n)))
            start = time.perf_counter()
            hits = self.bytes_scan([b"\x00"])
            elapsed = time.perf_counter() - start
            self.assertEqual(len(hits), n)
            return elapsed

        small = measure(8_000)
        large = measure(64_000)
        # 8x the matches. Linear predicts ~8x, quadratic ~64x.
        self.assertLess(
            large,
            max(small, 0.005) * 24,
            f"8x the matches cost {large / max(small, 1e-9):.1f}x the time — "
            f"the per-match line lookup is not O(log lines)",
        )


if __name__ == "__main__":
    unittest.main()
