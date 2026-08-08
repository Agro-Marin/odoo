"""The one place that decides what a suppression comment says.

Two independent parsers used to answer that: `is_suppressed` here, and the
rationale checker's own regex. Both scanned raw lines, which cost this module
three things it no longer pays for:

* a string literal containing the text of a directive silenced a real rule --
  ``cr.execute("select # noqa from t")`` suppressed `sql-injection`, and a
  snippet in a test file was reported as an unexplained `noqa`;
* `_NOQA_SELF`, a file-wide blanket over five files, existed only to hide the
  second half of that;
* `noqa` had no word boundary, so ``# noqawhatever`` and ``# NOQA is a linter
  directive`` waived every rule on the line.

Comments now come from `tokenize`, so a directive is only a directive where
Python says there is a comment, and both consumers parse it with the same
function.
"""

import io
import re
import tokenize

# `noqa` has to end where a directive ends: at the end of the comment, at
# whitespace, or at the `:` that introduces the codes. Without this, any word
# merely starting with `noqa` read as a bare suppression of every rule.
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
}


NOQA_RATIONALE_RULE = "noqa-rationale"


def comment_lines(source: str) -> dict[int, str]:
    """``{lineno: comment text}`` for every real comment in ``source``.

    A file that does not tokenise has no comments as far as this module is
    concerned. That is the safe direction: `_py_scan` only reaches here for a
    file it has already parsed, so an untokenisable one is not being linted
    either, and answering "no suppression" can only ever over-report.
    """
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
    """Does this comment waive ``rule``?"""
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
    """The suppression comments of one file, tokenised once.

    `is_suppressed` used to re-split the whole source on every finding. One
    scan per file is both cheaper and the only way to know that a `#` is a
    comment rather than the inside of a string.
    """

    __slots__ = ("comments",)

    def __init__(self, source: str) -> None:
        self.comments = comment_lines(source)

    @classmethod
    def from_comments(cls, comments: dict[int, str]) -> Suppressions:
        """Reuse a map `comment_lines` already produced, rather than re-tokenise."""
        instance = cls.__new__(cls)
        instance.comments = comments
        return instance

    def suppresses(self, lineno: int, rule: str) -> bool:
        if rule == NOQA_RATIONALE_RULE:
            return False
        comment = self.comments.get(lineno)
        return comment is not None and comment_suppresses(comment, rule)


def is_suppressed(source: str, lineno: int, rule: str) -> bool:
    """Convenience for a single check; prefer `Suppressions` per file."""
    return Suppressions(source).suppresses(lineno, rule)
