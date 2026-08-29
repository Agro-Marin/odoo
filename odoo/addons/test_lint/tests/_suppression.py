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


class Untokenisable(Exception):
    pass


def comment_lines(source: str) -> dict[int, str]:
    comments: dict[int, str] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments[token.start[0]] = token.string
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError) as exc:
        raise Untokenisable(f"{type(exc).__name__}: {exc}") from exc
    return comments


def _split_codes(codes: str) -> set[str]:
    return {code.strip().lower() for code in codes.split(",") if code.strip()}


def comment_suppresses(comment: str, aliases: frozenset[str]) -> bool:
    lowered = {alias.lower() for alias in aliases}

    if match := _PYLINT_DISABLE_RE.search(comment):
        if _split_codes(match.group(1)) & lowered:
            return True

    if match := _NOQA_RE.search(comment):
        if not match.group("sep"):
            return True
        codes = match.group("codes")
        if not codes:
            return False
        return bool(_split_codes(codes) & lowered)

    return False


class Suppressions:
    __slots__ = ("aliases", "comments", "unsuppressable")

    def __init__(
        self,
        comments: dict[int, str],
        aliases: dict[str, frozenset[str]],
        unsuppressable: frozenset[str] = frozenset(),
    ) -> None:
        self.comments = comments
        self.aliases = aliases
        self.unsuppressable = unsuppressable

    @classmethod
    def of(
        cls,
        source: str,
        aliases: dict[str, frozenset[str]],
        unsuppressable: frozenset[str] = frozenset(),
    ) -> Suppressions:
        return cls(comment_lines(source), aliases, unsuppressable)

    def suppresses(self, lineno: int, rule: str, lines: set[int] | None = None) -> bool:
        if rule in self.unsuppressable:
            return False
        aliases = self.aliases.get(rule, frozenset({rule}))
        for line in sorted(lines or {lineno}):
            comment = self.comments.get(line)
            if comment is not None and comment_suppresses(comment, aliases):
                return True
        return False
