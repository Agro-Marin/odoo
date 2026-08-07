import pytest

from odoo.libs.email.parsing import (
    email_anonymize,
    email_domain_extract,
    email_normalize,
    email_normalize_all,
    email_split,
    email_split_tuples,
    formataddr,
)


class TestEmailNormalize:
    def test_lowercases_and_strips(self):
        assert email_normalize("  John.Doe@Example.COM ") == "john.doe@example.com"

    def test_invalid_returns_false(self):
        assert email_normalize("not-an-email") is False

    def test_normalize_all_dedup_preserving_order(self):
        assert email_normalize_all("A@B.com, c@d.com") == ["a@b.com", "c@d.com"]


class TestEmailSplit:
    def test_split_plain(self):
        assert email_split("a@b.com, c@d.com") == ["a@b.com", "c@d.com"]

    def test_split_tuples_with_name(self):
        assert email_split_tuples('"John" <a@b.com>, c@d.com') == [
            ("John", "a@b.com"),
            ("", "c@d.com"),
        ]


class TestEmailDomainExtract:
    def test_extracts_lowercased_domain(self):
        assert email_domain_extract("john@Example.com") == "example.com"

    def test_invalid_returns_false(self):
        assert email_domain_extract("nope") is False


class TestEmailAnonymize:
    def test_local_part_masked(self):
        assert email_anonymize("john.doe@example.com") == "j*****oe@example.com"

    def test_domain_masked_when_requested(self):
        assert (
            email_anonymize("john.doe@example.com", redact_domain=True)
            == "j*****oe@e******.com"
        )


class TestFormataddr:
    def test_ascii_name(self):
        assert formataddr(("John Doe", "j@x.com")) == '"John Doe" <j@x.com>'

    def test_empty_name_returns_bare_address(self):
        assert formataddr(("", "j@x.com")) == "j@x.com"

    def test_utf8_name_kept_literal(self):
        assert formataddr(("Jóhn Doe", "j@x.com")) == '"Jóhn Doe" <j@x.com>'

    def test_ascii_charset_base64_encodes_non_ascii_name(self):
        assert formataddr(("Jóhn", "j@x.com"), charset="ascii").startswith("=?utf-8?b?")

    @pytest.mark.parametrize(
        "name",
        ["Bad\nName", "Bad\r\nName", "Bad\rName", "Bad\x00Name"],
    )
    def test_control_chars_stripped_from_name(self, name):
        out = formataddr((name, "j@x.com"))
        assert "\n" not in out
        assert "\r" not in out
        assert "\x00" not in out
