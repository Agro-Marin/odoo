"""Bulgarian cardinals, which upstream ``num2words`` does not implement.

Kept here rather than in ``_monkeypatches`` because it is not a patch: it is a
language implementation that happens to have no home but a third-party
registry. ``_monkeypatches/num2words.py`` is the few lines that register it.

The interface is ``num2words``' own duck type -- ``str_to_number`` for string
input, ``to_cardinal`` for the conversion, and a ``to_*`` for every other form
the library can be asked for, raising ``NotImplementedError`` where Bulgarian
is not implemented. ``res_currency.amount_to_text`` catches exactly that and
falls back to English, so nothing here may raise anything else.

Two features of the language drive the shape of the code:

* **Gender.** Only 1 and 2 inflect, and the scale word decides which form:
  *един/два* милиона (masculine), *една/две* хиляди (feminine), *едно/две*
  standing alone (neuter). Hence :data:`UNITS`, keyed by gender.
* **The conjunction.** Bulgarian takes exactly one *и*, before the final
  component of the whole number -- "сто **и** единадесет", "хиляда **и** едно".
  It belongs to the number rather than to a group, so the least significant
  non-empty group is told it is final and places it. If that group already
  needs an internal *и* between its own hundreds and what follows, that one
  serves: 1101 is "хиляда сто и едно", never "хиляда и сто и едно".
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar, Final

MASCULINE: Final = 1
FEMININE: Final = -1
NEUTER: Final = 0

UNITS: Final[dict[int, tuple[str | None, ...]]] = {
    NEUTER: (
        None,
        "едно",
        "две",
        "три",
        "четири",
        "пет",
        "шест",
        "седем",
        "осем",
        "девет",
    ),
    MASCULINE: (
        None,
        "един",
        "два",
        "три",
        "четири",
        "пет",
        "шест",
        "седем",
        "осем",
        "девет",
    ),
    FEMININE: (
        None,
        "една",
        "две",
        "три",
        "четири",
        "пет",
        "шест",
        "седем",
        "осем",
        "девет",
    ),
}

TENS: Final[tuple[str | None, ...]] = (
    None,
    "десет",
    "двадесет",
    "тридесет",
    "четиридесет",
    "петдесет",
    "шестдесет",
    "седемдесет",
    "осемдесет",
    "деветдесет",
)

HUNDREDS: Final[tuple[str | None, ...]] = (
    None,
    "сто",
    "двеста",
    "триста",
    "четиристотин",
    "петстотин",
    "шестстотин",
    "седемстотин",
    "осемстотин",
    "деветстотин",
)

#: 11 is irregular; 12..19 are ``UNITS[MASCULINE][n] + "на" + "десет"``.
ELEVEN: Final = "единадесет"
TEEN_INFIX: Final = "на"

ZERO: Final = "нула"
MINUS: Final = "минус"
AND: Final = "и"
THOUSAND: Final = "хиляда"
THOUSANDS: Final = "хиляди"
#: Appended to a scale word for a count above one (dva milion-A).
SCALE_PLURAL: Final = "а"

#: Scale words by power of ten. The largest entry bounds what can be named.
SCALES: Final[dict[int, str]] = {
    6: "милион",
    9: "милиард",
    12: "трилион",
    15: "квадрилион",
    18: "квинтилион",
    21: "секстилион",
    24: "септилион",
    27: "октилион",
    30: "ноналион",
    33: "декалион",
    36: "ундекалион",
    39: "дуодекалион",
    42: "тредекалион",
    45: "кватордекалион",
    48: "квинтдекалион",
    51: "сексдекалион",
    54: "септдекалион",
    57: "октодекалион",
    60: "новемдекалион",
    63: "вигинтилион",
}

#: First magnitude with no name, so the first this module refuses.
BEYOND_NAMING: Final = 10 ** (max(SCALES) + 3)


def _teen(unit: int) -> str:
    """10..19. Only 10 and 11 are irregular; 12..19 are unit + "на" + "десет"."""
    if unit == 0:
        return TENS[1]
    if unit == 1:
        return ELEVEN
    return UNITS[MASCULINE][unit] + TEEN_INFIX + TENS[1]


def _spell_group(value: int, gender: int, is_final: bool) -> list[str]:
    """Spell one 3-digit group. ``value`` is 1..999; 0 never reaches here.

    ``is_final`` marks the group that carries the number's single conjunction.
    """
    hundreds, remainder = divmod(value, 100)
    tens, units = divmod(remainder, 10)

    words: list[str] = []
    if hundreds:
        words.append(HUNDREDS[hundreds])
    if tens == 1:
        words.append(_teen(units))
    else:
        if tens:
            words.append(TENS[tens])
        if units:
            words.append(UNITS[gender][units])

    joined_internally = len(words) > 1
    if joined_internally:
        words.insert(len(words) - 1, AND)
    if is_final and (not hundreds or not joined_internally):
        # An internal conjunction already reads as the number's one "и"; a
        # second, leading one would double it.
        words.insert(0, AND)
    return words


def _scale_words(power: int, count: int) -> list[str]:
    """The scale word for 10**``power``, agreeing with ``count`` groups."""
    if power == 3:
        return [THOUSAND] if count == 1 else [THOUSANDS]
    return [SCALES[power] + SCALE_PLURAL] if count > 1 else [SCALES[power]]


def _gender_for(power: int) -> int:
    if power == 3:
        return FEMININE
    return NEUTER if power == 0 else MASCULINE


def _split_groups(value: int) -> list[int]:
    """``value`` as 3-digit groups, most significant first."""
    groups = []
    while value:
        value, group = divmod(value, 1000)
        groups.append(group)
    return list(reversed(groups)) or [0]


class BulgarianNumerals:
    """A ``num2words`` converter for ``bg``."""

    _scales: ClassVar[dict[int, str]] = SCALES

    def str_to_number(self, value: str) -> int | float:
        number = Decimal(value)
        return int(number) if number == number.to_integral_value() else float(number)

    def to_cardinal(self, value: float | None) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            if not value.is_integer():
                msg = "Fractional cardinals are not implemented for Bulgarian"
                raise NotImplementedError(msg)
            value = int(value)
        if abs(value) >= BEYOND_NAMING:
            # Past вигинтилион there is no name to reach for. Refused as
            # NotImplementedError rather than escaping as the KeyError a scale
            # lookup would throw, so amount_to_text can fall back to English.
            msg = f"Bulgarian cardinals stop below 10^{max(SCALES) + 3}"
            raise NotImplementedError(msg)
        return self._spell(value)

    def to_ordinal(self, value: int) -> str:
        msg = "Ordinal not implemented for Bulgarian"
        raise NotImplementedError(msg)

    def to_ordinal_num(self, value: int) -> str:
        msg = "Ordinal num not implemented for Bulgarian"
        raise NotImplementedError(msg)

    def to_year(self, value: int) -> str:
        msg = "Year not implemented for Bulgarian"
        raise NotImplementedError(msg)

    def to_currency(self, value: float, **kwargs: object) -> str:
        msg = "Currency not implemented for Bulgarian"
        raise NotImplementedError(msg)

    def _spell(self, value: int) -> str:
        if value == 0:
            return ZERO

        groups = _split_groups(abs(value))
        words: list[str] = [MINUS] if value < 0 else []

        for index, group in enumerate(groups):
            if not group:
                continue
            power = (len(groups) - index - 1) * 3
            # The least significant non-empty group carries the conjunction --
            # unless it is the only one, which takes none at all.
            is_final = index > 0 and not any(groups[index + 1 :])

            if power == 3 and group == 1:
                # "хиляда", never "една хиляда".
                words.extend(_scale_words(power, group))
                continue
            if power >= 6 and group == 1:
                words.append(UNITS[MASCULINE][1])
                words.extend(_scale_words(power, group))
                continue

            words.extend(_spell_group(group, _gender_for(power), is_final))
            if power:
                words.extend(_scale_words(power, group))

        return " ".join(words)
