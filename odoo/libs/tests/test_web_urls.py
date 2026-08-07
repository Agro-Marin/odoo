import pytest

from odoo.libs.web.urls import _segment_core, urljoin

BASE = "https://api.example.com/v1/"


class TestUrljoinTraversalBlocked:
    @pytest.mark.parametrize(
        "extra",
        [
            "../etc/passwd",
            "./x",
            "a/../../x",
            "a/./b/../c",
            "%2e%2e/x",
            "%252e%252e/x",
            "..%2f..%2fetc",
            "..\\..\\x",
            "a\\..\\..\\etc",
            "..;/x",
            "a/..;/x",
            "%2e%2e;/x",
            "..%00/x",
            "..%00;junk/x",
            "..%01/x",
            "%252e%252e%3bx/y",
        ],
    )
    def test_blocked(self, extra):
        with pytest.raises(ValueError):
            urljoin(BASE, extra)


class TestUrljoinNoFalsePositives:
    @pytest.mark.parametrize(
        ("extra", "expected"),
        [
            ("c", "https://api.example.com/v1/c"),
            ("sub/path", "https://api.example.com/v1/sub/path"),
            ("..foo/bar", "https://api.example.com/v1/..foo/bar"),
            ("....//x", "https://api.example.com/v1/..../x"),
            (".hidden", "https://api.example.com/v1/.hidden"),
            ("file;v=1", "https://api.example.com/v1/file;v=1"),
            (
                "a;jsessionid=xyz/b",
                "https://api.example.com/v1/a;jsessionid=xyz/b",
            ),
            ("normal-file_2.json", "https://api.example.com/v1/normal-file_2.json"),
        ],
    )
    def test_legit_join_passes(self, extra, expected):
        assert urljoin(BASE, extra) == expected


class TestUrljoinHostSchemeOverride:
    @pytest.mark.parametrize(
        "extra",
        [
            "http://evil.com/",
            "https://evil.com/x",
            "//evil.com/x",
            "https://api.example.com/other",
            "https:evil",
            "javascript:alert(1)",
        ],
    )
    def test_foreign_absolute_rejected(self, extra):
        with pytest.raises(ValueError):
            urljoin(BASE, extra)

    def test_matching_absolute_allowed(self):
        assert (
            urljoin(BASE, "https://api.example.com/v1/ok")
            == "https://api.example.com/v1/ok"
        )

    def test_backslash_host_is_neutralized_to_subpath(self):
        assert (
            urljoin(BASE, "\\\\evil.com/x") == "https://api.example.com/v1/evil.com/x"
        )


class TestUrljoinQueryFragment:
    def test_query_and_fragment_taken_from_extra_only(self):
        assert urljoin("https://h/p/?base#bf", "sub?x=1#f2") == "https://h/p/sub?x=1#f2"

    def test_query_only_extra(self):
        assert urljoin("https://api.example.com/data/", "?lang=fr") == (
            "https://api.example.com/data/?lang=fr"
        )


class TestUrljoinTypeErrors:
    @pytest.mark.parametrize(
        ("base", "extra"), [(None, "x"), ("http://h", None), (b"x", "y")]
    )
    def test_non_str_raises_typeerror(self, base, extra):
        with pytest.raises(TypeError):
            urljoin(base, extra)


class TestSegmentCore:
    @pytest.mark.parametrize(
        ("segment", "core"),
        [
            ("..", ".."),
            ("..;foo", ".."),
            ("..\x00x", ".."),
            ("..\x7f", ".."),
            ("..\x01y", ".."),
            ("v1.2;beta", "v1.2"),
            ("..foo", "..foo"),
            ("file", "file"),
        ],
    )
    def test_core(self, segment, core):
        assert _segment_core(segment) == core
