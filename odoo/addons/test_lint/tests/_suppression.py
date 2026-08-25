"""Reading `# noqa` / `# pylint: disable=` directives out of Python source.

Mechanism only. Which rules exist, what their short codes are and which of them
refuse to be silenced is policy, and lives in `_rules`; every entry point here
takes that policy as an argument rather than holding a second copy of it.
"""

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
    """The file's comments could not be read.

    Raised rather than swallowed: an empty comment map silently disarms every
    `# noqa` in the file and makes `noqa-rationale` report nothing, which reads
    exactly like a clean file.
    """


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
    """Does `comment` silence a rule spelled by any of `aliases`?"""
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
    """The directives in one file, answered per (line, rule)."""

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
        """Is the rule waived for a finding anchored at `lineno`?

        `lines` is every line a directive may be written on for this finding --
        see `_rules.directive_lines`. It covers the statement the finding sits
        in, so a directive written where a developer naturally puts one counts:

            self.env.cr.execute(
                f"SELECT {t}"
            )  # noqa: E8501  the table name comes from _table

        Ruff anchors on the first line only, and so did this, which made the
        placement a developer reaches for first do nothing at all -- silently,
        since an ignored directive looks exactly like an absent one. Nothing in
        the tree relied on the old behaviour: measured across all 570 findings,
        none carried a directive inside its span that was being ignored.
        """
        if rule in self.unsuppressable:
            return False
        aliases = self.aliases.get(rule, frozenset({rule}))
        for line in sorted(lines or {lineno}):
            comment = self.comments.get(line)
            if comment is not None and comment_suppresses(comment, aliases):
                return True
        return False
