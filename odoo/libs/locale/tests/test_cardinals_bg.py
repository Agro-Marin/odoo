import itertools

import pytest

from odoo.libs.locale.cardinals_bg import BEYOND_NAMING, BulgarianNumerals

UNITS = {
    1: "едно",
    2: "две",
    3: "три",
    4: "четири",
    5: "пет",
    6: "шест",
    7: "седем",
    8: "осем",
    9: "девет",
}
TEENS = {
    10: "десет",
    11: "единадесет",
    12: "дванадесет",
    13: "тринадесет",
    14: "четиринадесет",
    15: "петнадесет",
    16: "шестнадесет",
    17: "седемнадесет",
    18: "осемнадесет",
    19: "деветнадесет",
}
TENS = {
    2: "двадесет",
    3: "тридесет",
    4: "четиридесет",
    5: "петдесет",
    6: "шестдесет",
    7: "седемдесет",
    8: "осемдесет",
    9: "деветдесет",
}
HUNDREDS = {
    1: "сто",
    2: "двеста",
    3: "триста",
    4: "четиристотин",
    5: "петстотин",
    6: "шестстотин",
    7: "седемстотин",
    8: "осемстотин",
    9: "деветстотин",
}


def compose(value):
    """The grammar, written independently of the implementation.

    Hundreds, then a teen or tens-and-units, joined by one ``и`` before the
    last component. This is the oracle: a value table of a dozen numbers cannot
    cover 999 morpheme joins, and the bug this was written for -- every number
    ending in 11 rendering as "eleven and one" -- is exactly the kind a value
    table misses.
    """
    hundreds, remainder = divmod(value, 100)
    tens, units = divmod(remainder, 10)
    parts = []
    if hundreds:
        parts.append(HUNDREDS[hundreds])
    if tens == 1:
        parts.append(TEENS[10 + units])
    else:
        if tens:
            parts.append(TENS[tens])
        if units:
            parts.append(UNITS[units])
    if len(parts) > 1:
        parts.insert(len(parts) - 1, "и")
    return " ".join(parts)


@pytest.fixture(scope="module")
def bg():
    return BulgarianNumerals()


class TestAgainstTheGrammar:
    def test_every_value_below_1000(self, bg):
        mismatches = [
            (value, bg.to_cardinal(value), compose(value))
            for value in range(1, 1000)
            if bg.to_cardinal(value) != compose(value)
        ]
        assert mismatches == []

    @pytest.mark.parametrize("value", [11, 111, 211, 911, 1011, 11011])
    def test_a_trailing_eleven_does_not_repeat_its_unit(self, bg, value):
        """`d == 1 and e == 1` forgot to clear the unit, so 11 was "eleven and one"."""
        assert bg.to_cardinal(value).endswith("единадесет")


class TestScaleAndGender:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, "нула"),
            (1000, "хиляда"),
            (1001, "хиляда и едно"),
            (1101, "хиляда сто и едно"),
            (2000, "две хиляди"),
            (21000, "двадесет и една хиляди"),
            (1000000, "един милион"),
            (2000000, "два милиона"),
            (1000000000, "един милиард"),
            (1000001, "един милион и едно"),
            (-21, "минус двадесет и едно"),
        ],
    )
    def test_known_values(self, bg, value, expected):
        assert bg.to_cardinal(value) == expected

    def test_only_one_and_per_number(self, bg):
        """1101 is "хиляда сто и едно", not "хиляда и сто и едно"."""
        assert bg.to_cardinal(1101).split().count("и") == 1
        assert bg.to_cardinal(111111).split().count("и") == 2  # one per group

    def test_gender_follows_the_scale_word(self, bg):
        assert "една хиляди" in bg.to_cardinal(21000)  # feminine before хиляди
        assert bg.to_cardinal(1000000).startswith("един ")  # masculine before милион
        assert bg.to_cardinal(1) == "едно"  # neuter alone


class TestStructuralInvariants:
    def test_nothing_dangles_over_the_first_100_000(self, bg):
        problems = []
        for value in range(100_000):
            words = bg.to_cardinal(value)
            tokens = words.split()
            if words != words.strip() or "  " in words:
                problems.append((value, words, "whitespace"))
            elif tokens[0] == "и" or tokens[-1] == "и":
                problems.append((value, words, "dangling conjunction"))
            elif any(a == b for a, b in itertools.pairwise(tokens)):
                problems.append((value, words, "repeated word"))
        assert problems == []


class TestTheContractResCurrencyRelies_On:
    """`res_currency.amount_to_text` catches NotImplementedError and only that."""

    def test_integral_floats_convert(self, bg):
        assert bg.to_cardinal(7.0) == "седем"

    def test_none_is_empty(self, bg):
        assert bg.to_cardinal(None) == ""

    @pytest.mark.parametrize(
        "call",
        [
            lambda c: c.to_cardinal(7.5),
            lambda c: c.to_ordinal(7),
            lambda c: c.to_ordinal_num(7),
            lambda c: c.to_year(2026),
            lambda c: c.to_currency(7.0),
        ],
    )
    def test_unimplemented_forms_raise_only_notimplementederror(self, bg, call):
        with pytest.raises(NotImplementedError):
            call(bg)

    def test_beyond_the_named_magnitudes_refuses_cleanly(self, bg):
        """A bare KeyError from the scale lookup would escape amount_to_text."""
        assert bg.to_cardinal(BEYOND_NAMING - 1).startswith("деветстотин")
        with pytest.raises(NotImplementedError):
            bg.to_cardinal(BEYOND_NAMING)

    def test_string_input_goes_through_str_to_number(self, bg):
        assert bg.str_to_number("42") == 42
        assert bg.str_to_number("42.5") == 42.5
