import re
from collections.abc import Iterator
from dataclasses import dataclass

_NOQA_RE = re.compile(
    r"""
    \#                          # the comment marker
    \s*
    noqa
    (?:                         # optional code list — `F401`, or `sql-injection`
        :\s*
        (?P<codes>
            [A-Za-z][\w-]*
            (?:\s*,\s*[A-Za-z][\w-]*)*
        )
    )?
    (?P<rest>.*)$               # everything after the codes (may be empty)
    """,
    re.VERBOSE | re.IGNORECASE,
)
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


def find_violations(source: str) -> Iterator[Violation]:
    for lineno, line in enumerate(source.splitlines(), start=1):
        if "noqa" not in line.lower():
            continue
        match = _NOQA_RE.search(line)
        if not match:
            continue
        if _has_rationale(match.group("rest")):
            continue
        yield Violation(lineno=lineno, raw=line)
