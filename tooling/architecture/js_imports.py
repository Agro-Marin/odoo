"""The one JavaScript import parser the architecture gates share.

Every gate in this directory needs the same fact — *which modules does this
file import* — and for a while each one answered it separately. Measured
against ``es-module-lexer`` over the 3225 real import sites in
``addons/web/static/src``, the three hand-rolled answers disagreed:

===================== ======== ======== ============ =============
parser                  truth    found       missed      spurious
===================== ======== ======== ============ =============
``js_layer_check``       3225     3225            0             0
``js_layer_cohesion``    3225     3217            8             0
``js_public_surface``    2423     2425            0             2
===================== ======== ======== ============ =============

The misses and the false hits are not random; each regex encodes a different
wrong belief about the language:

* ``js_layer_cohesion`` matched ``import\\s``, which cannot match ``import(``.
  It lost every dynamic import — including ``@web/components/emoji_picker/
  emoji_data``, an internal edge, so a real cohesion input was missing.
* ``js_public_surface`` matched any string literal starting with ``@web/``.
  ``core/l10n/translation.js`` names the bus event ``@web/core/l10n/
  translationLoaded``, and ``core/registry.js`` names itself in a message;
  neither is an import, and both were counted as surface.

This is the same class of error four times over in this project's history: a
regex over import *statements* is not an import *graph*. Writing the lesson
down did not stop the fourth. Deleting the alternatives does — a gate cannot
hand-roll a parser it does not have to write.

What makes the surviving parser exact is ``strip_comments``: a state machine
that tracks string and template-literal context, so ``"https://x"`` is not a
comment and ``/* @import ... */`` is not an edge. A `re.sub` cannot do that,
which is why both replacements it replaces were wrong in opposite directions.

Type-only references are deliberately not edges. A JSDoc ``@import`` names a
module without depending on it at runtime: it cannot cause a cycle, cannot
violate a layer, and moving its target breaks the *type*, which the typecheck
locks already own.
"""

import re
import string
from bisect import bisect_right

# Runtime ESM import forms (after comments are stripped):
#   import X from "spec";  import {a} from "spec";  import * as n from "spec";
#   export {a} from "spec";  export * from "spec";          -> _FROM_RE
#   import "spec";                                           -> _SIDE_EFFECT_RE
#   import("spec")                                           -> _DYNAMIC_RE
# The specifier class excludes newlines: a module specifier is a single-line
# string literal, so allowing one let these patterns run across unrelated string
# and template-literal content and invent specifiers hundreds of characters long
# (a Python snippet in `api_doc`, a `console.error` block in `point_of_sale`).
_FROM_RE = re.compile(r"""\bfrom\s*['"]([^'"\n]+)['"]""")
_SIDE_EFFECT_RE = re.compile(r"""\bimport\s*['"]([^'"\n]+)['"]""")
_DYNAMIC_RE = re.compile(r"""\bimport\s*\(\s*['"]([^'"\n]+)['"]""")


#: Identifier characters, for deciding whether a ``/`` follows a value.
_IDENT_CHARS = frozenset(string.ascii_letters + string.digits + "_$")

#: A ``/`` right after one of these ends a VALUE, so it is division, not a
#: regex. Everything else (operators, ``(``, ``,``, ``=``, ``{``, ``;``, ...)
#: puts the scanner in expression position, where ``/`` opens a regex literal.
_VALUE_END_CHARS = frozenset(")]\"'`")

#: ...except after these keywords, which are followed by an expression.
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
    """Whether a ``/`` seen after ``tail`` opens a regex literal."""
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
    """Index just past the closing ``/`` of the regex literal at ``start``.

    ``None`` when it does not close on the same line — a regex literal cannot
    span a newline, so that means ``/`` was division after all.

    That bound caps a misread at one line, which is NOT the same as harmless:
    a module specifier contains slashes, so a misread that starts before a
    same-line ``import("@web/x")`` or ``export {y} from "@web/x"`` closes on
    the slash inside the specifier and blanks the import. What keeps that from
    happening is :func:`_starts_regex` being fed real source, not the blanked
    output — see ``strip_comments``.
    """
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


#: Characters that can start a construct the scanner must resolve. Everything
#: between two of them is ordinary code and is copied in one slice, which is
#: what makes this a ~7x faster scan than stepping character by character.
_INTERESTING_RE = re.compile(r"""[/'"`]""")

#: How much preceding source :func:`_starts_regex` needs. Only the last token
#: matters, and no JS keyword is longer than ``instanceof``.
_TAIL_KEEP = 16


def strip_comments(src: str) -> str:
    """Blank ``//`` line comments, ``/* */`` block comments and regex literals,
    preserving every newline (so line numbers stay exact) and respecting string
    / template literals. Blanked characters become spaces; the text length and
    all newline positions are preserved.

    Regex literals are recognised, not just tolerated, because the scanner has
    no other way to know that the ``/*`` in ``name.replace(/^\\/*/, "")`` is not
    a comment. Without it the scanner desynchronises at the first such literal
    and everything after it is read in the wrong state — which is how a JSDoc
    ``import("@web/env")`` at ``public/public_boot.js:110`` became a runtime
    edge in the cycle graph, and how a real ``@web/webclient`` import placed
    after ``const re = /^\\/*/;`` became invisible to the layering gate.

    Their bodies are blanked rather than kept: no import, export or module
    specifier can live inside a regex, so blanking them costs nothing and
    removes the only remaining way a literal can be mistaken for one.

    Regex-vs-division is decided from ``tail``, the last significant characters
    of the SOURCE. It used to be decided from the last 32 entries of the OUTPUT
    buffer, which is a different thing the moment a comment precedes the ``/``:
    a comment blanks to spaces, so a block comment of 32 characters or more
    emptied the window, ``_starts_regex`` read that as expression position, and
    a plain division was consumed as a regex — closing on the next ``/`` in the
    line, which for ``let r = a /* explain the units here */ / b;
    import("@web/x")`` is the slash inside the specifier. The import vanished
    and the gate passed. Comments do not contribute to ``tail``, so the
    decision no longer depends on what happens to be nearby.
    """
    out: list[str] = []
    tail = ""  # last significant source chars; comments never enter it
    after_value = False  # last construct was a string/regex literal (a value)
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
                    # A regex literal is a value: the next `/` divides it. The
                    # fail-safe reading anyway — division blanks nothing.
                    after_value = True
                    i = end
                    continue
            out.append("/")
            tail = (tail + "/")[-_TAIL_KEEP:]
            after_value = False
            i = j + 1
            continue

        # String or template literal: copied verbatim, escapes honoured.
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
    """Return ``[(specifier, lineno), ...]`` of runtime imports in ``src``."""
    cleaned = strip_comments(src)
    # Precompute line-start offsets for O(log n) line lookups.
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
    """The distinct modules ``src`` imports, when line numbers do not matter."""
    return {spec for spec, _lineno in collect_imports(src)}


def collect_type_imports(src: str) -> list[tuple[str, int]]:
    """Return ``[(specifier, lineno), ...]`` of ``import("…")`` occurrences that
    live INSIDE a comment — JSDoc type references such as
    ``@param {import("@web/core/tree/condition_tree").Tree}``.

    **This is the exact complement of :func:`collect_imports`, and it must never
    be used to build a runtime graph.** A type reference is erased before the
    module runs: it creates no load-order edge, no cycle and no layering edge.
    Every existing caller in this package wants the runtime graph and should keep
    calling :func:`collect_imports`. The one question this answers is a different
    one — *does a consumer name a file it was told not to name* — which matters
    for renaming, not for loading.

    Comment regions are located by complement rather than by a second parser:
    :func:`strip_comments` blanks comments while preserving length and every
    newline position, so a character is inside a comment exactly when it differs
    from the character at the same offset in the cleaned text. That inherits the
    regex-literal and string-literal hardening documented on ``strip_comments``
    instead of re-deriving it, weaker, here.

    Known and accepted imprecision: ``strip_comments`` also blanks regex
    literals, so an ``import("…")`` written inside a regex would be reported as
    a type reference. No such construct exists in this codebase, and the failure
    direction is a visible false positive rather than a silent miss.
    """
    cleaned = strip_comments(src)
    line_starts = [0]
    line_starts.extend(m.end() for m in re.finditer(r"\n", src))

    found: list[tuple[str, int]] = []
    for m in _DYNAMIC_RE.finditer(src):
        start = m.start(1)
        # Inside a comment iff the scanner blanked it. Comparing the slice (not
        # a single char) keeps this correct when a specifier abuts the boundary.
        if src[start : m.end(1)] == cleaned[start : m.end(1)]:
            continue  # survived stripping -> real code, already a runtime import
        found.append((m.group(1), bisect_right(line_starts, start)))
    return found
