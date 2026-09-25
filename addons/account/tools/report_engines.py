import re
from collections.abc import Iterable
from typing import NamedTuple

from odoo.tools import LazyTranslate

_lt = LazyTranslate(__name__)

ACCOUNT_CODES_ENGINE_SPLIT_REGEX = re.compile(r"(?=[+-])")
ACCOUNT_CODES_ENGINE_TERM_REGEX = re.compile(
    r"^(?P<sign>[+-]?)"
    r"(?P<prefix>([A-Za-z\d.]*|tag\([\w.]+\))((?=\\)|(?<=[^CD])))"
    r"(\\\((?P<excluded_prefixes>([A-Za-z\d.]+,)*[A-Za-z\d.]*)\))?"
    r"(?P<balance_character>[DC]?)$"
)
ACCOUNT_CODES_ENGINE_TAG_ID_PREFIX_REGEX = re.compile(
    r"tag\(((?P<id>\d+)|(?P<ref>\w+\.\w+))\)"
)

LEDGER_ENGINES = frozenset({"tax_tags", "account_codes"})


class AccountCodesFormulaError(ValueError):
    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


class AccountCodesTerm(NamedTuple):
    sign: int
    prefix: str
    excluded_prefixes: tuple[str, ...]
    balance_character: str
    tag_ref: str | None
    tag_id: int | None

    @property
    def is_tag(self) -> bool:
        return bool(self.tag_ref or self.tag_id)

    def matches_account(
        self, code: str, tag_ids: Iterable[int], tag_id: int | None
    ) -> bool:
        if self.excluded_prefixes and code.startswith(self.excluded_prefixes):
            return False
        if self.is_tag:
            return tag_id in tag_ids
        return code.startswith(self.prefix)


def parse_account_codes_formula(formula: str) -> list[AccountCodesTerm]:
    terms = []
    for token in filter(
        None, ACCOUNT_CODES_ENGINE_SPLIT_REGEX.split(formula.replace(" ", ""))
    ):
        match = ACCOUNT_CODES_ENGINE_TERM_REGEX.match(token)
        if not match or not match["prefix"]:
            raise AccountCodesFormulaError(token)
        tag = ACCOUNT_CODES_ENGINE_TAG_ID_PREFIX_REGEX.match(match["prefix"])
        terms.append(
            AccountCodesTerm(
                sign=-1 if match["sign"] == "-" else 1,
                prefix=match["prefix"],
                excluded_prefixes=tuple(match["excluded_prefixes"].split(","))
                if match["excluded_prefixes"]
                else (),
                balance_character=match["balance_character"],
                tag_ref=tag["ref"] if tag else None,
                tag_id=int(tag["id"]) if tag and tag["id"] else None,
            )
        )
    return terms


UNDISTR_LINE_NAME = _lt("Result Brought Forward")
