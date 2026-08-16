import re
import string
from bisect import bisect_right

_FROM_RE = re.compile(r"""\bfrom\s*['"]([^'"\n]+)['"]""")
_SIDE_EFFECT_RE = re.compile(r"""\bimport\s*['"]([^'"\n]+)['"]""")
_DYNAMIC_RE = re.compile(r"""\bimport\s*\(\s*['"]([^'"\n]+)['"]""")


_IDENT_CHARS = frozenset(string.ascii_letters + string.digits + "_$")

_VALUE_END_CHARS = frozenset(")]\"'`")

_REGEX_PRECEDING_KEYWORDS = frozenset(
    {
        "return",
        "typeof",
        "instanceof",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "case",
        "do",
        "else",
        "yield",
        "await",
    }
)


def _starts_regex(tail: str) -> bool:
    stripped = tail.rstrip()
    if not stripped:
        return True
    last = stripped[-1]
    if last in _IDENT_CHARS:
        end = len(stripped)
        while end and stripped[end - 1] in _IDENT_CHARS:
            end -= 1
        return stripped[end:] in _REGEX_PRECEDING_KEYWORDS
    return last not in _VALUE_END_CHARS


def _regex_literal_end(src: str, start: int) -> int | None:

    i, n = start + 1, len(src)
    in_class = False
    while i < n:
        c = src[i]
        if c == "\n":
            return None
        if c == "\\":
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            return i + 1
        i += 1
    return None


_INTERESTING_RE = re.compile(r"""[/'"`]""")

_TAIL_KEEP = 16


def strip_comments(src: str) -> str:

    out: list[str] = []
    tail = ""
    after_value = False
    i, n = 0, len(src)
    while i < n:
        match = _INTERESTING_RE.search(src, i)
        if match is None:
            out.append(src[i:])
            break
        j = match.start()
        if j > i:
            chunk = src[i:j]
            out.append(chunk)
            if stripped := chunk.strip():
                tail = (tail + stripped)[-_TAIL_KEEP:]
                after_value = False
        char = src[j]
        nxt = src[j + 1] if j + 1 < n else ""

        if char == "/" and nxt == "/":
            end = src.find("\n", j)
            end = n if end == -1 else end
            out.append(" " * (end - j))
            i = end
            continue

        if char == "/" and nxt == "*":
            end = src.find("*/", j + 2)
            end = n if end == -1 else end + 2
            out.append("".join("\n" if c == "\n" else " " for c in src[j:end]))
            i = end
            continue

        if char == "/":
            if not after_value and _starts_regex(tail):
                end = _regex_literal_end(src, j)
                if end is not None:
                    out.append(" " * (end - j))
                    after_value = True
                    i = end
                    continue
            out.append("/")
            tail = (tail + "/")[-_TAIL_KEEP:]
            after_value = False
            i = j + 1
            continue

        end = j + 1
        while end < n:
            c = src[end]
            if c == "\\":
                end += 2
                continue
            end += 1
            if c == char:
                break
        out.append(src[j:end])
        tail = (tail + char)[-_TAIL_KEEP:]
        after_value = True
        i = end
    return "".join(out)


def collect_imports(src: str) -> list[tuple[str, int]]:
    cleaned = strip_comments(src)
    line_starts = [0]
    line_starts.extend(m.end() for m in re.finditer(r"\n", cleaned))

    def lineno_at(pos: int) -> int:
        return bisect_right(line_starts, pos)

    found: list[tuple[str, int]] = []
    for regex in (_FROM_RE, _SIDE_EFFECT_RE, _DYNAMIC_RE):
        found.extend(
            (m.group(1), lineno_at(m.start(1))) for m in regex.finditer(cleaned)
        )
    return found


def imported_specifiers(src: str) -> set[str]:
    return {spec for spec, _lineno in collect_imports(src)}


def collect_type_imports(src: str) -> list[tuple[str, int]]:

    cleaned = strip_comments(src)
    line_starts = [0]
    line_starts.extend(m.end() for m in re.finditer(r"\n", src))

    found: list[tuple[str, int]] = []
    for m in _DYNAMIC_RE.finditer(src):
        start = m.start(1)
        if src[start : m.end(1)] == cleaned[start : m.end(1)]:
            continue
        found.append((m.group(1), bisect_right(line_starts, start)))
    return found
