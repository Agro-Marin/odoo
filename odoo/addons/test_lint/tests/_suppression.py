import io
import re
import tokenize

_NOQA_RE = re.compile(
    r"""
    \#\s*
    noqa (?=$|[\s:])
    (?P<sep>:)?\s*
    (?P<codes>[A-Za-z][\w-]* (?:\s*,\s*[A-Za-z][\w-]*)*)?
    (?P<rest>.*)$
    """,
    re.VERBOSE | re.IGNORECASE,
)
_PYLINT_DISABLE_RE = re.compile(r"#\s*pylint:\s*disable=([^\n#]+)", re.IGNORECASE)

RULE_ALIASES: dict[str, frozenset[str]] = {
    "sql-injection": frozenset({"sql-injection", "E8501"}),
    "gettext-variable": frozenset({"gettext-variable", "E8502"}),
    "gettext-placeholders": frozenset({"gettext-placeholders", "E8503"}),
    "gettext-repr": frozenset({"gettext-repr", "E8504"}),
    "missing-gettext": frozenset({"missing-gettext", "E8505"}),
    "raise-unlink-override": frozenset({"raise-unlink-override", "E8506"}),
    "n-plus-one-query": frozenset({"n-plus-one-query", "E8507"}),
    "orm-import": frozenset({"orm-import", "E8508"}),
    "onchange-domain": frozenset({"onchange-domain", "E8509"}),
    "config-chainmap-patch": frozenset({"config-chainmap-patch", "E8510"}),
}


NOQA_RATIONALE_RULE = "noqa-rationale"


def comment_lines(source: str) -> dict[int, str]:
    comments: dict[int, str] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments[token.start[0]] = token.string
    except tokenize.TokenError, IndentationError, SyntaxError, ValueError:
        return {}
    return comments


def _aliases(rule: str) -> set[str]:
    return {alias.lower() for alias in RULE_ALIASES.get(rule, frozenset({rule}))}


def _split_codes(codes: str) -> set[str]:
    return {code.strip().lower() for code in codes.split(",") if code.strip()}


def comment_suppresses(comment: str, rule: str) -> bool:
    if match := _PYLINT_DISABLE_RE.search(comment):
        if _split_codes(match.group(1)) & _aliases(rule):
            return True

    if match := _NOQA_RE.search(comment):
        if not match.group("sep"):
            return True
        codes = match.group("codes")
        if not codes:
            return False
        return bool(_split_codes(codes) & _aliases(rule))

    return False


class Suppressions:
    __slots__ = ("comments",)

    def __init__(self, source: str) -> None:
        self.comments = comment_lines(source)

    @classmethod
    def from_comments(cls, comments: dict[int, str]) -> Suppressions:
        instance = cls.__new__(cls)
        instance.comments = comments
        return instance

    def suppresses(self, lineno: int, rule: str) -> bool:
        if rule == NOQA_RATIONALE_RULE:
            return False
        comment = self.comments.get(lineno)
        return comment is not None and comment_suppresses(comment, rule)


def is_suppressed(source: str, lineno: int, rule: str) -> bool:
    return Suppressions(source).suppresses(lineno, rule)
