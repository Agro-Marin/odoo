import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from odoo.libs.lint.scan import scan_byte_patterns, scan_regex_patterns

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
    def test_repeated_pattern_on_one_line_is_one_finding(self):
        path = self.write("a.py", b"clean\nx\x00y\x00z\x00\nclean\n")
        self.assertEqual(self.bytes_scan([b"\x00"]), [(str(path), 2, 0)])

    def test_overlapping_matches_are_not_distinct_findings(self):
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
        self.write("a.py", b"anything\n")
        with self.assertRaises(ValueError):
            self.bytes_scan([b""])

    def test_an_invalid_regex_is_rejected(self):
        with self.assertRaises(ValueError):
            self.regex_scan(["(unclosed"])


class TestScanRefusesToUndercount(_ScanCase):
    def test_a_missing_root_raises(self):
        with self.assertRaises(OSError):
            scan_byte_patterns([str(self.root / "absent")], [".py"], [b"hit"], [])

    @unittest.skipIf(os.geteuid() == 0, "root reads every file")
    def test_an_unreadable_file_raises_after_the_whole_scan(self):
        readable = self.write("a.py", b"hit\n")
        locked = self.write("b.py", b"hit\n")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o644)
        with self.assertRaises(OSError) as caught:
            self.bytes_scan([b"hit"])
        self.assertIn(str(locked), str(caught.exception))
        self.assertNotIn(str(readable), str(caught.exception))

    @unittest.skipIf(os.geteuid() == 0, "root reads every file")
    def test_an_unreadable_directory_raises(self):
        self.write("sub/a.py", b"hit\n")
        sub = self.root / "sub"
        sub.chmod(0)
        self.addCleanup(sub.chmod, 0o755)
        with self.assertRaises(OSError):
            self.regex_scan(["hit"], extensions=[".py"])


class TestRegexScan(_ScanCase):
    def test_two_matches_on_one_line_are_two_findings(self):
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
        path = self.write("a.js", b"one\n\xff\xfe bad bytes\nhit here\n")
        self.assertEqual(self.regex_scan(["hit"]), [(str(path), 3, 0, "hit")])


class TestScanScales(_ScanCase):
    def test_line_numbering_is_linear_in_the_number_of_matches(self):
        def measure(n: int) -> float:
            self.write("q.py", b"".join(b"\x00 line %d\n" % i for i in range(n)))
            start = time.perf_counter()
            hits = self.bytes_scan([b"\x00"])
            elapsed = time.perf_counter() - start
            self.assertEqual(len(hits), n)
            return elapsed

        small = measure(8_000)
        large = measure(64_000)
        self.assertLess(
            large,
            max(small, 0.005) * 24,
            f"8x the matches cost {large / max(small, 1e-9):.1f}x the time — "
            f"the per-match line lookup is not O(log lines)",
        )


if __name__ == "__main__":
    unittest.main()
