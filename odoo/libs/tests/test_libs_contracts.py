import inspect
import io
import logging
from collections import OrderedDict

import pytest

from odoo.libs._vendor.useragents import UserAgentParser
from odoo.libs.barcode import check_barcode_encoding
from odoo.libs.collections.frozen_dict import freehash
from odoo.libs.collections.ordered_set import LastOrderedSet, OrderedSet
from odoo.libs.colors.conversions import get_saturation, hex_to_rgb
from odoo.libs.datetime.tz import ZoneInfoNotFoundError, timezone
from odoo.libs.email.parsing import formataddr
from odoo.libs.filesystem.mimetypes import guess_mimetype
from odoo.libs.filesystem.osutil import zip_dir
from odoo.libs.hashing import CONTENT_DIGEST_LEN, content_hash
from odoo.libs.image.utils import (
    IMAGE_MAX_RESOLUTION,
    ImageProcess,
    ImageTooLargeError,
    NotWebpError,
    get_webp_size,
)
from odoo.libs.json.orjson_wrapper import dumps as orjson_dumps
from odoo.libs.logging import lower_logging, mute_logger
from odoo.libs.lru import LRU
from odoo.libs.numbers.float_utils import float_invert
from odoo.libs.sql.utils import reverse_order
from odoo.libs.text.address import street_split
from odoo.libs.text.html import html_sanitize


class TestGuessMimetypeDefault:
    def test_default_returned_for_unidentifiable_content(self):
        assert guess_mimetype(b"\0" * 32, default="image/png") == "image/png"

    def test_default_does_not_override_a_real_identification(self):
        assert guess_mimetype(b"%PDF-1.7\n", default="image/png") == "application/pdf"

    def test_default_defaults_to_octet_stream(self):
        assert guess_mimetype(b"\0" * 32) == "application/octet-stream"


class TestCheckBarcodeEncoding:
    @pytest.mark.parametrize("encoding", ["ean8", "ean13", "gtin14", "upca", "sscc"])
    def test_empty_barcode(self, encoding):
        assert check_barcode_encoding("", encoding) is False

    def test_known_good_values_still_pass(self):
        assert check_barcode_encoding("20220006", "ean8")
        assert check_barcode_encoding("2022071416014", "ean13")

    def test_ean13_leading_zero_still_rejected(self):
        assert check_barcode_encoding("0022071416014", "ean13") is False


class TestLowerLoggingReentrancy:
    def test_nested_reuse_restores_handlers(self):
        root = logging.getLogger()
        original = root.handlers[:]
        ll = lower_logging(logging.ERROR, logging.WARNING)
        try:
            with ll, ll:
                assert root.handlers == [ll]
            assert root.handlers == original
        finally:
            root.handlers = original

    def test_nested_reuse_does_not_recurse_on_emit(self):
        root = logging.getLogger()
        original = root.handlers[:]
        ll = lower_logging(logging.WARNING, logging.INFO)
        try:
            with ll, ll:
                logging.getLogger("odoo.test.reentrant").error("boom")
            assert ll.had_error_log
        finally:
            root.handlers = original

    def test_inner_block_does_not_erase_an_outer_error(self):
        root = logging.getLogger()
        original = root.handlers[:]
        ll = lower_logging(logging.WARNING, logging.INFO)
        try:
            with ll:
                logging.getLogger("odoo.test.reentrant").error("boom")
                with ll:
                    pass
                assert ll.had_error_log
        finally:
            root.handlers = original

    def test_matches_mute_logger_semantics(self):
        logger = logging.getLogger("odoo.test.mute")
        logger.handlers, logger.propagate = [], True
        with mute_logger("odoo.test.mute") as _outer:
            pass
        assert logger.propagate is True


class TestLastOrderedSet:
    def test_update_moves_existing_element_last(self):
        s = LastOrderedSet([1, 2, 3])
        s.update([1])
        assert list(s) == [2, 3, 1]

    def test_update_matches_add(self):
        by_add = LastOrderedSet([1, 2, 3])
        for elem in (1, 4, 2):
            by_add.add(elem)
        by_update = LastOrderedSet([1, 2, 3])
        by_update.update([1, 4, 2])
        assert list(by_add) == list(by_update) == [3, 1, 4, 2]


class TestHexToRgb:
    def test_missing_hash_is_parsed_not_misread(self):
        assert hex_to_rgb("FF0000") == (255, 0, 0)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("#FF0000", (255, 0, 0)),
            ("#f00", (255, 0, 0)),
            ("#ff0000ff", (255, 0, 0)),
            ("#f00f", (255, 0, 0)),
            ("#123456", (0x12, 0x34, 0x56)),
            ("#abc", (0xAA, 0xBB, 0xCC)),
        ],
    )
    def test_accepted_forms(self, value, expected):
        assert hex_to_rgb(value) == expected

    @pytest.mark.parametrize(
        "value", ["", "#", "#12345", "nope", "#gg0000", "#1234567"]
    )
    def test_rejected_forms(self, value):
        with pytest.raises(ValueError, match="not a hexadecimal color"):
            hex_to_rgb(value)


class TestFloatInvert:
    def test_zero_raises_a_named_error(self):
        with pytest.raises(ZeroDivisionError, match="cannot invert 0"):
            float_invert(0.0)

    def test_known_inversions(self):
        assert float_invert(0.01) == 100.0
        assert float_invert(0.05) == 20.0


class TestStreetSplit:
    def test_street_number2_is_stripped(self):
        assert street_split("Main Street 123 - Apt B  ") == {
            "street_name": "Main Street",
            "street_number": "123",
            "street_number2": "Apt B",
        }


class TestGetWebpSizeRobustness:
    @staticmethod
    def _webp(subtype: bytes, tail: bytes) -> bytes:
        return b"RIFF" + b"\x00\x00\x00\x00" + b"WEBPVP8" + subtype + tail

    @pytest.mark.parametrize(
        "buf",
        [
            b"RIFF\x00\x00\x00\x00WEBPVP8 ",
            b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 12,
            b"RIFF\x00\x00\x00\x00WEBPVP8X" + b"\x00" * 10,
            b"RIFF\x00\x00\x00\x00WEBPVP8L\x00\x00\x00\x00\x2f\x00\x00",
        ],
    )
    def test_truncated_returns_none(self, buf):
        assert get_webp_size(buf) is None

    @pytest.mark.parametrize("buf", [b"\x89PNG\r\n\x1a\n", b"RIFF\x00\x00\x00\x00WE"])
    def test_non_webp_raises(self, buf):
        with pytest.raises(NotWebpError):
            get_webp_size(buf)

    def test_valid_lossless_1x1_still_parsed(self):
        buf = (
            b"RIFF"
            + b"\x00" * 4
            + b"WEBPVP8L"
            + b"\x00" * 4
            + bytes([0x2F, 0x00, 0x00, 0x00, 0x00])
        )
        assert get_webp_size(buf) == (1, 1)


class TestUserAgentParseCache:
    UAS = [
        (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
        ),
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
        "curl/8.5.0",
        "",
    ]

    def test_cached_equals_uncached(self):
        parser = UserAgentParser()
        fresh = UserAgentParser()
        for ua in self.UAS:
            assert parser(ua) == fresh._parse(ua)

    def test_repeated_call_is_a_cache_hit(self):
        parser = UserAgentParser()
        ua = self.UAS[0]
        parser(ua)
        before = parser._parse_cached.cache_info().hits
        parser(ua)
        assert parser._parse_cached.cache_info().hits == before + 1


class TestOrjsonDumpsIntrospectable:
    def test_signature_is_introspectable(self):
        params = list(inspect.signature(orjson_dumps).parameters)
        assert params == ["obj", "default", "ensure_ascii", "option"]

    def test_ensure_ascii_true_is_rejected(self):
        with pytest.raises(ValueError, match="ASCII"):
            orjson_dumps({"a": 1}, ensure_ascii=True)


class TestFloatSplitSign:
    def test_str_form_keeps_sign_for_subunit_negative(self):
        from odoo.libs.numbers.float_utils import float_split_str

        assert float_split_str(-0.05, 2) == ("-0", "05")
        assert float_split_str(-2.675, 2) == ("-2", "68")

    def test_int_form_loses_subunit_sign_but_keeps_it_from_minus_one(self):
        from odoo.libs.numbers.float_utils import float_split

        assert float_split(-0.05, 2) == (0, 5)
        assert float_split(-2.675, 2) == (-2, 68)
        assert float_split(-0.001, 2) == (0, 0)


class TestImageProcessWebpResolution:
    @staticmethod
    def _webp_vp8x(width: int, height: int) -> bytes:
        def u24(n: int) -> bytes:
            return (n).to_bytes(4, "little")[:3]

        body = (
            b"VP8X"
            + (10).to_bytes(4, "little")
            + b"\x00"
            + b"\x00\x00\x00"
            + u24(width - 1)
            + u24(height - 1)
        )
        return b"RIFF" + (len(body) + 4).to_bytes(4, "little") + b"WEBP" + body

    def test_oversized_webp_is_rejected(self):
        side = int(IMAGE_MAX_RESOLUTION**0.5) + 100
        src = self._webp_vp8x(side, side)
        assert get_webp_size(src) == (side, side)
        with pytest.raises(ImageTooLargeError):
            ImageProcess(src, verify_resolution=True)

    def test_reasonable_webp_still_accepted(self):
        src = self._webp_vp8x(64, 64)
        assert ImageProcess(src, verify_resolution=True).image is False

    def test_oversized_webp_accepted_when_not_verifying(self):
        side = int(IMAGE_MAX_RESOLUTION**0.5) + 100
        src = self._webp_vp8x(side, side)
        assert ImageProcess(src, verify_resolution=False).image is False


class TestLruCountSetter:
    def test_shrink_evicts_down_to_new_count(self):
        lru = LRU(10, [(i, i) for i in range(10)])
        lru.count = 3
        assert len(lru) == 3
        assert set(lru) == {7, 8, 9}

    def test_shrink_keeps_the_most_recently_used(self):
        lru = LRU(10, [(i, i) for i in range(10)])
        lru[0]
        lru[1]
        lru.count = 3
        assert list(lru) == [9, 0, 1]

    def test_setter_holds_no_python_iterator_over_the_map(self):
        """The eviction loop must not iterate the map in Python.

        This replaces a test that asserted the *workaround*: it injected a
        ``__iter__`` raising RuntimeError into ``lru._ordering`` and checked the
        setter swallowed it.  That guard existed because the unlocked read path
        mutated a second dict while the setter walked it -- ``next(iter(...))``
        raises under concurrent readers, measured at 25 in 17.2M.  With one map
        and ``popitem``, there is no Python-level iterator left to interrupt, so
        the property to pin is its absence.
        """
        seen = []

        class WatchfulMap(OrderedDict):
            def __iter__(self):
                seen.append("iter")
                return super().__iter__()

        lru = LRU(10, [(i, i) for i in range(10)])
        lru._map = WatchfulMap(lru._map)
        lru.count = 3
        assert len(lru) == 3
        assert seen == [], "count setter still walks the map in Python"

    def test_rejects_a_non_positive_count(self):
        lru = LRU(4, [(1, "a")])
        for bad in (0, -1):
            with pytest.raises(ValueError, match="must be positive"):
                lru.count = bad
        assert len(lru) == 1


class TestHtmlSanitizeRecovery:
    def test_crash_input_does_not_yield_placeholder(self):
        out = str(html_sanitize("<select><style>x</style></select>"))
        assert "Unknown error when sanitizing" not in out

    def test_surrounding_content_is_preserved(self):
        out = str(
            html_sanitize("<p>keep this line</p><select><style>x</style></select>")
        )
        assert "keep this line" in out
        assert "Unknown error when sanitizing" not in out

    def test_kill_tags_still_removed_on_recovery(self):
        out = str(html_sanitize("<p>hi</p><select><style>body{x:1}</style></select>"))
        assert "<style" not in out.lower()
        assert "body{x:1}" not in out

    def test_normal_sanitization_unaffected(self):
        assert str(html_sanitize("<script>alert(1)</script>hi")) == "hi"
        assert "onerror" not in str(html_sanitize("<img src=x onerror=alert(1)>"))

    def test_silent_false_still_raises(self):
        with pytest.raises(AssertionError):
            html_sanitize("<select><style>x</style></select>", silent=False)


class TestTimezoneContract:
    @pytest.mark.parametrize("name", ["", "../etc/passwd", "Foo/Bar", "not a tz"])
    def test_bad_names_raise_zoneinfonotfound(self, name):
        with pytest.raises(ZoneInfoNotFoundError):
            timezone(name)

    def test_bad_name_is_catchable_as_keyerror(self):
        with pytest.raises(KeyError):
            timezone("")

    def test_valid_names_still_resolve(self):
        assert timezone("Europe/Paris") is not None
        assert timezone("UTC") is not None


class TestFormataddrHeaderInjection:
    def test_newline_is_stripped_from_name(self):
        out = formataddr(("Bad\r\nBcc: victim@x.com", "user@example.com"))
        assert "\n" not in out
        assert "\r" not in out
        assert out == '"BadBcc: victim@x.com" <user@example.com>'

    def test_control_only_name_collapses_to_bare_address(self):
        assert formataddr(("\r\n\t", "user@example.com")) == "user@example.com"

    def test_ordinary_name_unchanged(self):
        assert (
            formataddr(("John Doe", "john@example.com"))
            == '"John Doe" <john@example.com>'
        )


class TestReverseOrderCommas:
    def test_function_call_arglist_not_split(self):
        assert reverse_order("coalesce(a, b) desc") == "coalesce(a, b) asc"

    def test_mixed_items(self):
        assert (
            reverse_order("coalesce(a, b) desc, name asc")
            == "coalesce(a, b) asc, name desc"
        )

    def test_quoted_identifier_with_comma(self):
        assert reverse_order('"a,b" asc') == '"a,b" desc'

    def test_simple_cases_unchanged(self):
        assert reverse_order("name asc, date desc") == "name desc, date asc"
        assert reverse_order("id") == "id desc"
        assert reverse_order("name desc nulls last") == "name asc nulls first"


class TestZipDirRelativePath:
    def _tree(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "a.txt").write_text("a")
        (tmp_path / "pkg" / "sub").mkdir()
        (tmp_path / "pkg" / "sub" / "b.txt").write_text("b")

    def test_relative_bare_name_keeps_full_member_names(self, tmp_path, monkeypatch):
        import zipfile

        self._tree(tmp_path)
        monkeypatch.chdir(tmp_path)
        buf = io.BytesIO()
        zip_dir("pkg", buf, include_dir=True)
        names = sorted(zipfile.ZipFile(io.BytesIO(buf.getvalue())).namelist())
        assert names == ["pkg/a.txt", "pkg/sub/b.txt"]

    def test_absolute_path_still_correct(self, tmp_path):
        import zipfile

        self._tree(tmp_path)
        buf = io.BytesIO()
        zip_dir(str(tmp_path / "pkg"), buf, include_dir=True)
        names = sorted(zipfile.ZipFile(io.BytesIO(buf.getvalue())).namelist())
        assert names == ["pkg/a.txt", "pkg/sub/b.txt"]


class TestOrderedSetIntersectionAliasing:
    def test_no_args_returns_copy(self):
        s = OrderedSet([1, 2, 3])
        result = s.intersection()
        assert result == s
        assert result is not s
        result.add(4)
        assert 4 not in s

    def test_with_args_still_works(self):
        s = OrderedSet([1, 2, 3])
        assert list(s.intersection([2, 3, 4])) == [2, 3]


class TestGetSaturationType:
    def test_gray_returns_float_zero(self):
        result = get_saturation((128, 128, 128))
        assert result == 0.0
        assert isinstance(result, float)

    def test_pure_color_still_one(self):
        assert get_saturation((255, 0, 0)) == 1.0


class TestFreehashOnlyCatchesUnhashability:
    """A bug inside ``__hash__`` must not become a cache key.

    ``except Exception`` turned any failure into ``id(arg)``: a key that is
    structurally meaningless, never equal to the same value computed again, and
    silent.  Only ``TypeError`` -- the unhashable signal -- may fall through to
    the structural fallbacks.
    """

    def test_unhashable_still_falls_back(self):
        class Unhashable:
            # the documented way to make a class unhashable
            __hash__ = None  # type: ignore[assignment]

        obj = Unhashable()
        assert freehash(obj) == id(obj)

    def test_a_broken_hash_propagates(self):
        class Broken:
            def __hash__(self):
                raise RuntimeError("bug in __hash__")

        with pytest.raises(RuntimeError, match="bug in __hash__"):
            freehash(Broken())

    def test_mapping_and_iterable_fallbacks_still_work(self):
        assert freehash({"a": [1, 2]}) == freehash({"a": [1, 2]})
        assert freehash([1, 2, 3]) == freehash([1, 2, 3])


class TestOrderedSetIntersectionFollowsItsOwnOrder:
    """An ordered set's intersection must be ordered by the set, not the argument.

    ``MutableSet.__and__`` builds its result by iterating *other*, so the one
    type in the package whose entire purpose is remembering insertion order
    handed that order over to whatever was passed in.
    """

    def test_order_comes_from_self_not_the_argument(self):
        s = OrderedSet([1, 2, 3, 4])
        assert list(s & [4, 3]) == [3, 4]
        assert list(s.intersection([4, 3])) == [3, 4]

    def test_reversed_operand_agrees(self):
        s = OrderedSet([1, 2, 3, 4])
        assert list([4, 3] & s) == [3, 4]

    def test_argument_order_is_irrelevant(self):
        s = OrderedSet(["c", "a", "b"])
        assert list(s & ["a", "b", "c"]) == list(s & ["c", "b", "a"]) == ["c", "a", "b"]

    def test_membership_is_unchanged(self):
        s = OrderedSet([1, 2, 3, 4])
        assert set(s & [4, 3]) == {3, 4}
        assert list(s.intersection()) == [1, 2, 3, 4]
        assert list(s.intersection([2, 3, 4], [3, 4, 5])) == [3, 4]

    def test_result_is_still_an_ordered_set(self):
        assert isinstance(OrderedSet([1, 2]) & [2], OrderedSet)
        assert isinstance(LastOrderedSet([1, 2]) & [2], LastOrderedSet)


class TestContentHashToleranceDoesNotDependOnBlake3:
    """The falsy-input guard lived on one of the two branches.

    ``data or b""`` was written on the sha1 path only, so whether
    ``content_hash(None)`` returned the empty digest or raised TypeError
    depended on whether an optional dependency happened to be installed.
    """

    def test_empty_and_falsy_inputs_agree(self):
        assert content_hash(b"") == content_hash(None)  # type: ignore[arg-type]

    def test_it_is_the_digest_of_the_empty_input(self):
        assert content_hash(None) == content_hash(b"")  # type: ignore[arg-type]
        assert len(content_hash(b"")) == CONTENT_DIGEST_LEN

    def test_real_content_is_unaffected(self):
        assert content_hash(b"x") != content_hash(b"")
