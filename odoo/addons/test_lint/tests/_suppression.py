"""In-line suppression of lint findings: ``# noqa`` and ``# pylint: disable=``.

**The bug this module exists to fix.** The previous implementation stripped the
text after ``# noqa`` and then tested it with ``startswith("  ")`` -- a
condition ``strip()`` had just made unreachable. The effect was that a bare
``# noqa`` suppressed, and ``# noqa  because the column is a legacy alias`` did
not:

    'x  # noqa'                  -> suppressed
    'x  # noqa  because legacy'  -> NOT suppressed
    'x  # noqa: F401  re-export' -> NOT suppressed

which put it in direct contradiction with ``TestPythonLint.test_noqa_rationale``,
whose whole point is that every suppression must carry a reason. Writing the
rationale that one test demands silently switched the checker back on. The two
gates cancelled each other out.

A suppression is now read the way every other tool reads one: the codes decide
what is silenced, and the prose after them is documentation.
"""

import re

_NOQA_RE = re.compile(
    r"""
    \#\s*noqa
    (?P<sep>:)?\s*
    (?P<codes>[A-Za-z][\w-]* (?:\s*,\s*[A-Za-z][\w-]*)*)?
    """,
    re.VERBOSE,
)

_PYLINT_DISABLE_RE = re.compile(r"#\s*pylint:\s*disable=([^\n#]+)")

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


def is_suppressed(source: str, lineno: int, rule: str) -> bool:
    """Whether line *lineno* of *source* silences *rule*.

    A bare ``# noqa`` silences everything on the line; ``# noqa: <codes>``
    silences only the named rules, by code (``E8501``) or by name
    (``sql-injection``). ``# pylint: disable=<rules>`` is honoured the same way,
    since that is how these rules were written before the plugins were replaced
    -- and it is still how every suppression in the tree is actually spelled.
    Trailing prose never changes the outcome.

    A ``# noqa:`` whose code list does not parse silences **nothing**. Reading
    it as a bare ``noqa`` -- which is what happened before -- turns a typo into
    a blanket waiver, and does it most readily on the line of someone who was
    trying to be specific.
    """
    if rule == NOQA_RATIONALE_RULE:
        return False

    lines = source.split("\n")
    if lineno < 1 or lineno > len(lines):
        return False
    line = lines[lineno - 1]
    aliases = {alias.lower() for alias in RULE_ALIASES.get(rule, frozenset({rule}))}

    if match := _PYLINT_DISABLE_RE.search(line):
        if {token.strip().lower() for token in match.group(1).split(",")} & aliases:
            return True

    if match := _NOQA_RE.search(line):
        if not match.group("sep"):
            return True
        codes = match.group("codes")
        if not codes:
            return False
        return bool({code.strip().lower() for code in codes.split(",")} & aliases)

    return False
