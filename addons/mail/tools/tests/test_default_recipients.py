import pytest

from addons.mail.tools.default_recipients import choose_default_recipients

P1, P2 = 11, 12
MAIL_1 = '"One" <one@example.com>'
MAIL_2 = '"Two" <two@example.com>'
KEY_1 = "one@example.com"
KEY_2 = "two@example.com"


def choose(**overrides):
    kwargs = {
        "prioritize_email": False,
        "email_to_lst": [],
        "to_keys": [],
        "mailable_ids": [],
        "mailable_keys": set(),
        "kept_ids": [],
        "kept_emails": set(),
    }
    kwargs.update(overrides)
    return choose_default_recipients(**kwargs)


class TestPartnersPreferred:
    def test_mailable_partner_wins_over_an_address(self):
        assert choose(
            email_to_lst=[MAIL_1],
            to_keys=[KEY_1],
            mailable_ids=[P1],
            mailable_keys={KEY_1},
            kept_ids=[P1],
            kept_emails={KEY_1},
        ) == ([P1], "")

    def test_address_alone_is_sent_as_an_address(self):
        assert choose(email_to_lst=[MAIL_1], to_keys=[KEY_1]) == ([], MAIL_1)

    def test_several_addresses_are_joined(self):
        assert choose(email_to_lst=[MAIL_1, MAIL_2], to_keys=[KEY_1, KEY_2]) == (
            [],
            f"{MAIL_1},{MAIL_2}",
        )

    def test_nothing_at_all(self):
        assert choose() == ([], "")

    def test_partner_with_no_usable_address_is_still_named(self):
        assert choose(kept_ids=[P1], kept_emails={False}) == ([P1], "")

    def test_unparseable_address_matching_its_partner_prefers_the_partner(self):
        assert choose(
            email_to_lst=["not-an-email"],
            to_keys=["not-an-email"],
            kept_ids=[P1],
            kept_emails={"not-an-email"},
        ) == ([P1], "")

    def test_unparseable_address_not_matching_is_sent_as_text(self):
        assert choose(
            email_to_lst=["not-an-email"],
            to_keys=["not-an-email"],
            kept_ids=[P1],
            kept_emails={"other-nonsense"},
        ) == ([], "not-an-email")

    def test_an_address_suppresses_the_unmailable_partner_fallback(self):
        assert choose(
            email_to_lst=[MAIL_1],
            to_keys=[KEY_1],
            kept_ids=[P1],
            kept_emails={False},
        ) == ([], MAIL_1)


class TestEmailPrioritised:
    def test_address_wins_over_the_partner_carrying_it(self):
        assert choose(
            prioritize_email=True,
            email_to_lst=[MAIL_1],
            to_keys=[KEY_1],
            mailable_ids=[P2],
            mailable_keys={KEY_2},
            kept_ids=[P2],
            kept_emails={KEY_2},
        ) == ([], MAIL_1)

    def test_partners_win_when_they_are_exactly_the_same_addresses(self):
        assert choose(
            prioritize_email=True,
            email_to_lst=[MAIL_1],
            to_keys=[KEY_1],
            mailable_ids=[P1],
            mailable_keys={KEY_1},
            kept_ids=[P1],
            kept_emails={KEY_1},
        ) == ([P1], "")

    def test_a_superset_of_addresses_is_not_the_same_set(self):
        assert choose(
            prioritize_email=True,
            email_to_lst=[MAIL_1, MAIL_2],
            to_keys=[KEY_1, KEY_2],
            mailable_ids=[P1],
            mailable_keys={KEY_1},
            kept_ids=[P1],
            kept_emails={KEY_1},
        ) == ([], f"{MAIL_1},{MAIL_2}")

    def test_no_address_falls_back_to_the_default_posture(self):
        for kwargs in (
            {"mailable_ids": [P1], "mailable_keys": {KEY_1}, "kept_ids": [P1]},
            {"kept_ids": [P1], "kept_emails": {False}},
            {},
        ):
            assert choose(prioritize_email=True, **kwargs) == choose(**kwargs)

    def test_duplicate_addresses_compare_as_a_set(self):
        assert choose(
            prioritize_email=True,
            email_to_lst=[MAIL_1, "one@example.com"],
            to_keys=[KEY_1, KEY_1],
            mailable_ids=[P1],
            mailable_keys={KEY_1},
            kept_ids=[P1],
            kept_emails={KEY_1},
        ) == ([P1], "")


@pytest.mark.parametrize("prioritize_email", [False, True])
def test_result_is_never_both_or_neither(prioritize_email):
    for kwargs in (
        {},
        {"email_to_lst": [MAIL_1], "to_keys": [KEY_1]},
        {"mailable_ids": [P1], "mailable_keys": {KEY_1}, "kept_ids": [P1]},
        {"kept_ids": [P1], "kept_emails": {False}},
        {
            "email_to_lst": [MAIL_1],
            "to_keys": [KEY_1],
            "mailable_ids": [P1],
            "mailable_keys": {KEY_1},
            "kept_ids": [P1],
            "kept_emails": {KEY_1},
        },
    ):
        partner_ids, email_to = choose(prioritize_email=prioritize_email, **kwargs)
        assert not (partner_ids and email_to), (kwargs, partner_ids, email_to)
