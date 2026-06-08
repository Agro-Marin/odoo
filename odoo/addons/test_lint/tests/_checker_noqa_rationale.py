"""``# noqa`` rationale checker.

Flags ``# noqa: <code>`` (or bare ``# noqa``) suppressions that lack a
human-readable justification.  Reading code is a lot easier when every
suppressed rule answers the question *"why was this allowed here?"*

Accepted shapes (anything goes after the codes as long as it carries some
explanatory text):

    x = 1 / 0  # noqa: B018 — keep for div-by-zero crash test
    import x   # noqa: F401  # re-exported by package __init__
    fn()       # noqa: E501 reason: legacy URL pinned by spec

Rejected shapes (will produce a violation):

    x = 1 / 0  # noqa
    import x   # noqa: F401
    fn()       # noqa: E501,B007

The rationale must be at least 4 non-space characters and contain at
least one alphabetic character (so ``-- !!!`` does not pass).
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

# A noqa marker — captures optional codes and any trailing text on the line.
# We deliberately accept ``# noqa`` (bare), ``# noqa: CODE``,
# ``# noqa: CODE,CODE`` and the type-comment companion ``# type: ignore``-
# adjacent forms.
_NOQA_RE = re.compile(
    r"""
    \#                          # the comment marker
    \s*
    noqa
    (?:                         # optional code list — codes are e.g. F401, B007
        :\s*
        (?P<codes>
            [A-Z]+\d+
            (?:\s*,\s*[A-Z]+\d+)*
        )
    )?
    (?P<rest>.*)$               # everything after the codes (may be empty)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Strip leading punctuation/dashes/extra ``#`` so we evaluate the actual prose.
_RATIONALE_LEAD_RE = re.compile(r"^[\s\-—–:#>·•|]+")

# A "real" rationale must contain at least one letter and four non-space chars.
_MIN_RATIONALE_CHARS = 4


@dataclass
class Violation:
    """A single ``# noqa`` suppression missing a rationale."""

    lineno: int
    raw: str

    def __str__(self) -> str:
        return f"line {self.lineno}: {self.raw.strip()}"


def _has_rationale(rest: str) -> bool:
    """Return True if *rest* (text after the code list) carries explanatory prose."""
    if not rest:
        return False
    cleaned = _RATIONALE_LEAD_RE.sub("", rest).strip()
    if len(cleaned) < _MIN_RATIONALE_CHARS:
        return False
    return any(ch.isalpha() for ch in cleaned)


def find_violations(source: str) -> Iterator[Violation]:
    """Yield ``Violation`` for every ``# noqa`` line lacking a rationale.

    Operates line-by-line on the raw source — no AST needed, since noqa is
    a comment-level construct.  Skips lines inside string literals only by
    way of ignoring sequences without a literal ``#`` followed by ``noqa``;
    in practice the rare false positive is harmless and easy to silence
    with an explanatory rationale (which is the whole point).
    """
    for lineno, line in enumerate(source.splitlines(), start=1):
        if "noqa" not in line.lower():
            continue
        match = _NOQA_RE.search(line)
        if not match:
            continue
        if _has_rationale(match.group("rest")):
            continue
        yield Violation(lineno=lineno, raw=line)
