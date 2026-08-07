import re

_NOQA_RE = re.compile(
    r"""
    \#\s*noqa
    (?P<sep>:)?\s*
    (?P<codes>[A-Za-z][\w-]* (?:\s*,\s*[A-Za-z][\w-]*)*)?
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


def is_suppressed(source: str, lineno: int, rule: str) -> bool:
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
