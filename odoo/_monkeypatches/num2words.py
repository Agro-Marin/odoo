"""
Bulgarian number-to-words support for num2words.

Bulgarian is not available in upstream num2words, so we provide it here.
Derived from num2cyrillic (LGPL-3.0-only).

This patch can be removed when Bulgarian is added to upstream num2words.
"""

import logging
from decimal import Decimal

_logger = logging.getLogger(__name__)


class Num2Word_BG:
    """Bulgarian number to words converter.

    Derived from num2cyrillic licensed under LGPL-3.0-only
    Copyright 2018 ClaimCompass, Inc (authored by Velizar Shulev)
    Copyright 1997 The PHP Group (PEAR::Numbers_Words, authored by Kouber Saparev)
    """

    _misc_strings: dict[str, str] = {
        "deset": "десет",
        "edinadeset": "единадесет",
        "na": "на",
        "sto": "сто",
        "sta": "ста",
        "stotin": "стотин",
        "hiliadi": "хиляди",
    }
    _digits = {
        0: [
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
        ],
    }
    _digits[1] = [None, "един", "два"] + _digits[0][3:]
    _digits[-1] = [None, "една"] + _digits[0][2:]
    _zero = "нула"
    _and = "и"
    _sep = " "
    _minus = "минус"
    _plural = "а"
    _exponent = {
        0: "",
        3: "хиляда",
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

    def str_to_number(self, value: str) -> int | float:
        """Parse a string to a number (part of the num2words converter API).

        ``num2words(number, lang="bg")`` calls this for string inputs before
        dispatching to ``to_cardinal``/``to_ordinal``; without it a str argument
        raised AttributeError.
        """
        number = Decimal(value)
        return int(number) if number == number.to_integral_value() else float(number)

    def to_cardinal(self, value: int | float | None) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            # ``_split_number``/``_show_digits_group`` operate on integer digit
            # groups; a non-integer float would crash (``len(float)``). Bulgarian
            # fractional rendering is not implemented (as for ``to_currency``).
            if value.is_integer():
                value = int(value)
            else:
                raise NotImplementedError(
                    "Fractional cardinals are not implemented for Bulgarian"
                )
        return self._to_words(value).strip()

    def to_ordinal(self, value: int) -> str:
        msg = "Ordinal not implemented for Bulgarian"
        raise NotImplementedError(msg)

    def to_ordinal_num(self, value: int) -> str:
        msg = "Ordinal num not implemented for Bulgarian"
        raise NotImplementedError(msg)

    def to_year(self, value: int) -> str:
        msg = "Year not implemented for Bulgarian"
        raise NotImplementedError(msg)

    def to_currency(self, value: int | float, **kwargs: object) -> str:
        msg = "Currency not implemented for Bulgarian"
        raise NotImplementedError(msg)

    def _split_number(self, num: int | str) -> list[str]:
        if isinstance(num, int):
            num = str(num)
        first: list[str] = []
        if len(num) % 3 != 0:
            if len(num[1:]) % 3 == 0:
                first = [num[0:1]]
                num = num[1:]
            elif len(num[2:]) % 3 == 0:
                first = [num[0:2]]
                num = num[2:]
        return first + [num[i : i + 3] for i in range(0, len(num), 3)]

    def _discard_empties(self, ls: list[str | None]) -> list[str]:
        return [x for x in ls if x is not None]

    def _show_digits_group(
        self,
        num: int | str,
        gender: int = 0,
        last: bool | int = False,
        and_state: list[bool] | None = None,
    ) -> str:
        num = int(num)
        e = num % 10  # ones
        d = (num - e) % 100 // 10  # tens
        s = (num - d * 10 - e) % 1000 // 100  # hundreds
        ret = [None] * 6

        if s:
            if s == 1:
                ret[1] = self._misc_strings["sto"]
            elif s in (2, 3):
                ret[1] = self._digits[0][s] + self._misc_strings["sta"]
            else:
                ret[1] = self._digits[0][s] + self._misc_strings["stotin"]

        if d:
            if d == 1:
                if not e:
                    ret[3] = self._misc_strings["deset"]
                elif e == 1:
                    ret[3] = self._misc_strings["edinadeset"]
                else:
                    ret[3] = (
                        self._digits[1][e]
                        + self._misc_strings["na"]
                        + self._misc_strings["deset"]
                    )
                    e = 0
            else:
                ret[3] = self._digits[1][d] + self._misc_strings["deset"]

        if e:
            ret[5] = self._digits[gender][e]

        non_empty = self._discard_empties(ret)
        if len(non_empty) > 1:
            if e:
                ret[4] = self._and
            else:
                ret[2] = self._and

        if last:
            if not s or len(non_empty) == 1:
                ret[0] = self._and
            if and_state is not None:
                and_state[0] = True

        return self._sep.join(self._discard_empties(ret))

    def _to_words(self, num: int | float = 0) -> str:
        # Per-conversion state kept in a local holder (not on ``self``): the
        # converter instance is shared across threads via CONVERTER_CLASSES, so
        # instance state would race under the threaded server.
        and_state = [False]
        num_groups = self._split_number(abs(num) if num < 0 else num)
        sizeof_num_groups = len(num_groups)

        if num < 0:
            ret_minus = self._minus + self._sep
        elif num == 0:
            return self._zero
        else:
            ret_minus = ""

        ret = [None] * (sizeof_num_groups + 1)
        i = sizeof_num_groups - 1
        j = 1

        while i >= 0:
            if ret[j] is None:
                ret[j] = ""

            _pow = sizeof_num_groups - i

            if num_groups[i] != "000":
                if int(num_groups[i]) > 1:
                    if _pow == 1:
                        ret[j] += (
                            self._show_digits_group(
                                num_groups[i], 0, not and_state[0] and i, and_state
                            )
                            + self._sep
                        )
                        ret[j] += self._exponent[(_pow - 1) * 3]
                    elif _pow == 2:
                        ret[j] += (
                            self._show_digits_group(
                                num_groups[i], -1, not and_state[0] and i, and_state
                            )
                            + self._sep
                        )
                        ret[j] += self._misc_strings["hiliadi"] + self._sep
                    else:
                        ret[j] += (
                            self._show_digits_group(
                                num_groups[i], 1, not and_state[0] and i, and_state
                            )
                            + self._sep
                        )
                        ret[j] += (
                            self._exponent[(_pow - 1) * 3] + self._plural + self._sep
                        )
                elif _pow == 1:
                    ret[j] += (
                        self._show_digits_group(
                            num_groups[i], 0, not and_state[0] and i, and_state
                        )
                        + self._sep
                    )
                elif _pow == 2:
                    ret[j] += self._exponent[(_pow - 1) * 3] + self._sep
                else:
                    ret[j] += (
                        self._digits[1][1]
                        + self._sep
                        + self._exponent[(_pow - 1) * 3]
                        + self._sep
                    )

            i -= 1
            j += 1

        ret = self._discard_empties(ret)
        ret.reverse()
        return ret_minus + "".join(ret)


def patch_module() -> None:
    try:
        import num2words
    except ImportError:
        _logger.warning(
            "num2words is not available, Bulgarian number to words conversion will not work"
        )
        return

    num2words.CONVERTER_CLASSES["bg"] = Num2Word_BG()
