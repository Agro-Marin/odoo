import pytest

from addons.mail.tools.email_keys import dedupe_emails_by_key, email_comparison_key


class TestEmailComparisonKey:
    @pytest.mark.parametrize(
        ("spelling", "expected"),
        [
            ("bob@example.com", "bob@example.com"),
            ("BOB@EXAMPLE.COM", "bob@example.com"),
            ('"Bob" <bob@example.com>', "bob@example.com"),
            ("Bob Smith <BOB@Example.Com>", "bob@example.com"),
            ("  bob@example.com  ", "bob@example.com"),
            ("<bob@example.com>", "bob@example.com"),
        ],
    )
    def test_one_address_many_spellings(self, spelling, expected):
        assert email_comparison_key(spelling) == expected

    def test_the_key_is_idempotent(self):
        for spelling in ('"B" <b@x.com>', "B@X.COM", "not-an-email", "a@b.c.d"):
            once = email_comparison_key(spelling)
            assert email_comparison_key(once) == once

    def test_unparseable_text_compares_equal_to_itself(self):
        assert email_comparison_key("not-an-email") == "not-an-email"
        assert email_comparison_key("  not-an-email  ") == "not-an-email"
        assert email_comparison_key("") == ""

    def test_every_falsy_spelling_of_no_address_is_one_key(self):
        assert email_comparison_key(False) == ""
        assert email_comparison_key(None) == ""
        assert email_comparison_key("") == ""
        assert email_comparison_key("   ") == ""

    def test_several_addresses_yield_the_first(self):
        assert email_comparison_key("a@x.com, b@y.com") == "a@x.com"


class TestDedupeEmailsByKey:
    def test_distinct_addresses_keep_their_order(self):
        assert dedupe_emails_by_key(["a@x.com", "b@y.com"], set()) == [
            "a@x.com",
            "b@y.com",
        ]

    def test_one_input_may_carry_several_addresses(self):
        assert dedupe_emails_by_key(["a@x.com, b@y.com"], set()) == [
            "a@x.com",
            "b@y.com",
        ]

    def test_skip_keys_are_matched_by_key_not_by_spelling(self):
        assert dedupe_emails_by_key(['"Alias" <a@x.com>'], {"a@x.com"}) == []
        assert dedupe_emails_by_key(["A@X.COM"], {"a@x.com"}) == []

    def test_the_named_spelling_wins_however_it_arrives(self):
        named = '"Bob" <bob@x.com>'
        assert dedupe_emails_by_key([named, "bob@x.com"], set()) == [named]
        assert dedupe_emails_by_key(["bob@x.com", named], set()) == [named]

    def test_two_named_spellings_keep_the_first(self):
        first = '"Bob" <bob@x.com>'
        assert dedupe_emails_by_key([first, '"Robert" <bob@x.com>'], set()) == [first]

    def test_blank_and_unparseable_inputs(self):
        assert dedupe_emails_by_key(["", "   "], set()) == []
        assert dedupe_emails_by_key([], set()) == []
        assert dedupe_emails_by_key(["not-an-email"], set()) == [], (
            "text with no address in it is not a recipient"
        )

    def test_a_frozenset_of_skip_keys_is_accepted(self):
        assert dedupe_emails_by_key(["a@x.com"], frozenset({"a@x.com"})) == []

    def test_every_result_is_addressable(self):
        results = dedupe_emails_by_key(
            ['"Bob" <bob@x.com>', "carol@y.com", "bob@x.com", "a@x.com, b@y.com"],
            {"carol@y.com"},
        )
        keys = [email_comparison_key(email) for email in results]
        assert len(keys) == len(set(keys)), "no recipient appears twice"
        assert "carol@y.com" not in keys
        assert all("@" in key for key in keys)
