import babel
import pytest

from odoo.libs.locale.conversions import posix_to_ldml, py_to_js_locale


@pytest.fixture(scope="module")
def en_us():
    return babel.Locale.parse("en_US")


class TestPyToJsLocale:
    @pytest.mark.parametrize(
        ("py", "js"),
        [
            ("en_US", "en-US"),
            ("fr_FR", "fr-FR"),
            ("sr@latin", "sr-Latn"),
            ("en", "en"),
        ],
    )
    def test_mapping(self, py, js):
        assert py_to_js_locale(py) == js


class TestPosixToLdml:
    def test_basic_directives(self, en_us):
        assert posix_to_ldml("%m/%d/%Y", en_us) == "MM/dd/yyyy"

    def test_no_pad_flag_does_not_leak_into_next_directive(self, en_us):
        assert posix_to_ldml("%-d %B", en_us) == "d MMMM"
        assert posix_to_ldml("%-x%d", en_us) == "M/d/yydd"

    def test_unsupported_directive_raises_valueerror(self, en_us):
        with pytest.raises(ValueError, match="Unsupported strftime directive"):
            posix_to_ldml("%Q", en_us)
