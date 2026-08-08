"""A suppression has to say why.

Parses with `_suppression`, so the rule that demands a reason and the rule that
honours the waiver can never disagree about what the comment says -- they used
to be two regexes, and `# NOQA: E8501 <why>` satisfied one and not the other.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from ._suppression import _NOQA_RE

_RATIONALE_LEAD_RE = re.compile(r"^[\s\-—–:#>·•|]+")

_MIN_RATIONALE_CHARS = 4


@dataclass
class Violation:
    lineno: int
    raw: str

    def __str__(self) -> str:
        return f"line {self.lineno}: {self.raw.strip()}"


def _has_rationale(rest: str) -> bool:
    if not rest:
        return False
    cleaned = _RATIONALE_LEAD_RE.sub("", rest).strip()
    if len(cleaned) < _MIN_RATIONALE_CHARS:
        return False
    return any(ch.isalpha() for ch in cleaned)


def find_violations(comments: dict[int, str]) -> Iterator[Violation]:
    """``comments`` is `_suppression.comment_lines` output for one file."""
    for lineno, comment in sorted(comments.items()):
        match = _NOQA_RE.search(comment)
        if match is None:
            continue
        if _has_rationale(match.group("rest")):
            continue
        yield Violation(lineno=lineno, raw=comment)
