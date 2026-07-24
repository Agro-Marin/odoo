"""Security-contract tests for :func:`odoo.libs.web.urls.urljoin`.

This fork ships its own ``urljoin`` (instead of stdlib) specifically to keep a
trusted base URL from being redirected elsewhere: no path traversal, no
host/scheme override.  These are DB-free unit tests pinning that contract,
including the traversal-bypass classes (``;`` path-parameter and NUL/control
truncation) that a raw ``seg == ".."`` check misses.
"""

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
            "%2e%2e/x",  # single-encoded
            "%252e%252e/x",  # double-encoded (proxy decodes twice)
            "..%2f..%2fetc",
            "..\\..\\x",  # backslash separators
            "a\\..\\..\\etc",
            "..;/x",  # ';' path-parameter bypass (Tomcat/Spring)
            "a/..;/x",
            "%2e%2e;/x",
            "..%00/x",  # NUL-truncation bypass
            "..%00;junk/x",
            "..%01/x",  # other control byte
            "%252e%252e%3bx/y",  # double-encoded '..' + ';' param
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
            ("..foo/bar", "https://api.example.com/v1/..foo/bar"),  # literal '..foo'
            ("....//x", "https://api.example.com/v1/..../x"),  # literal '....'
            (".hidden", "https://api.example.com/v1/.hidden"),
            ("file;v=1", "https://api.example.com/v1/file;v=1"),  # real path-param
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
            "//evil.com/x",  # protocol-relative host override
            "https://api.example.com/other",  # right host, wrong base path
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
        # ``\\evil.com/x`` is NOT a host override: urlsplit keeps it in the path,
        # and the leading-backslash strip turns it into an ordinary sub-path
        # under the trusted base (never ``//evil.com``).
        assert (
            urljoin(BASE, "\\\\evil.com/x") == "https://api.example.com/v1/evil.com/x"
        )


class TestUrljoinQueryFragment:
    def test_query_and_fragment_taken_from_extra_only(self):
        # base query/fragment are dropped; extra's are kept
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
            ("..;foo", ".."),  # path-parameter stripped
            ("..\x00x", ".."),  # NUL-truncated
            ("..\x7f", ".."),  # DEL-truncated
            ("..\x01y", ".."),  # control-truncated
            ("v1.2;beta", "v1.2"),  # real param on a non-dot segment
            ("..foo", "..foo"),  # not a traversal
            ("file", "file"),
        ],
    )
    def test_core(self, segment, core):
        assert _segment_core(segment) == core
