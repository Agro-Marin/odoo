"""Streaming safety scanner for ``psql -f`` restore input.

Extracted from ``odoo.service.db`` (which re-exports these names, so external
callers and the test-suite keep importing them from ``odoo.service.db``) to keep
that file focused on RPC entry points and let this self-contained security
component live and be tested on its own.

The scanner matches ``psql``'s own lexical contexts so a legitimate pg_dump — full
of PL/pgSQL bodies, escape strings, comments and COPY data — never false-positives,
while still rejecting every backslash meta-command a ``psql -f`` restore of an
attacker-supplied dump would execute (``\\!`` shell, ``\\i``/``\\copy`` file access,
``\\gexec``, ``\\connect``).

Depends only on the stdlib (``re``, ``pathlib``) — no import cycle with ``db``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


# psql meta-commands pg_dump legitimately emits in a plain-SQL dump.  Everything
# else — ``\!`` (shell), ``\i``/``\ir``/``\include`` (read files), ``\o``/``\g
# file``/``\copy`` (read/write files), ``\gexec`` (run query output as SQL),
# ``\connect`` (switch DB/host/user, incl. a remote host) — is rejected: on a
# ``psql -f`` restore they run with the OS/DB privileges of the Odoo service
# account, turning an uploaded backup into arbitrary command/file access.
_ALLOWED_PSQL_META_COMMANDS = frozenset({"\\.", "\\restrict", "\\unrestrict"})
_COPY_FROM_STDIN_RE = re.compile(r"\s*COPY\b.*\bFROM\s+stdin\b", re.IGNORECASE)
# A dollar-quote tag: ``$$`` or ``$ident$`` (the tag follows identifier rules and
# cannot contain a ``$``), so ``$1`` (a positional param) is not a tag.
_DOLLAR_TAG_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


class _PsqlSqlScanner:
    """Incremental scanner for psql meta-commands that ``psql -f`` would run.

    Matches ``psql``'s own lexical contexts so a legitimate dump — full of
    PL/pgSQL bodies, escape strings and comments — never false-positives: a
    backslash is a meta-command ONLY outside string literals, dollar-quoted
    bodies, comments and ``COPY ... FROM stdin`` data.  Inside those, ``psql``
    treats it as data/text, so the scanner must too.

    Fed ONE physical line at a time (:meth:`feed`) rather than the whole file,
    so a multi-GB ``dump.sql`` costs O(longest line) memory instead of O(file)
    — the previous whole-file ``read()`` peaked at ~2x the dump size inside the
    HTTP worker doing the restore, which is exactly the process under a memory
    soft limit.  A line is always a safe cut point: every token this scanner
    keys on (``--``, ``/*``, ``*/``, ``$tag$``, ``'``, ``"``, ``\\cmd``, the
    ``\\.`` COPY terminator) is newline-free, so only the multi-line CONTEXTS
    have to survive a boundary and those live in the instance state below.
    """

    __slots__ = (
        "at_stmt_start",
        "comment_depth",
        "dollar_tag",
        "in_copy_data",
        "in_double_quote",
        "in_single_quote",
        "lineno",
        "single_quote_escaped",
    )

    def __init__(self) -> None:
        self.lineno = 1
        self.at_stmt_start = True  # start-of-file / just after a ';' or newline
        # Carried lexical contexts — the only state a line boundary can split.
        self.in_copy_data = False
        self.comment_depth = 0  # nesting depth of an open /* ... */
        self.dollar_tag: str | None = None  # open $tag$ body, None if not in one
        self.in_single_quote = False
        self.single_quote_escaped = False  # the open literal is an E'...'
        self.in_double_quote = False

    def feed(self, line: str) -> tuple[int, str] | None:
        """Scan one physical line (``\\n``-terminated except possibly the last).

        Returns ``(lineno, command)`` for the first disallowed meta-command, or
        ``None``.  Once it returns a hit the scanner must not be fed again.
        """
        n = len(line)

        # --- COPY ... FROM stdin data block: everything up to a lone "\." ---
        if self.in_copy_data:
            self.lineno += 1
            if line.rstrip("\n").rstrip("\r") == "\\.":
                self.in_copy_data = False
                self.at_stmt_start = True
            return None

        i = 0
        # --- resume a lexical context left open by the previous line ---
        if self.comment_depth:
            i = self._resume_block_comment(line, i, n)
        elif self.dollar_tag is not None:
            i = self._resume_dollar_body(line, i, n)
        elif self.in_single_quote:
            i = self._resume_single_quote(line, i, n)
        elif self.in_double_quote:
            i = self._resume_double_quote(line, i, n)

        while i < n:
            c = line[i]
            if c == "\n":
                self.lineno += 1
                self.at_stmt_start = True
                return None  # a physical line ends here by construction

            # COPY ... FROM stdin;  -> following lines are data until "\."
            if self.at_stmt_start and c in "Cc":
                rest = line[i:].rstrip("\n").rstrip("\r")
                if _COPY_FROM_STDIN_RE.match(rest):
                    self.in_copy_data = True
                    self.at_stmt_start = True
                    self.lineno += 1
                    return None

            # line comment "-- ..." — runs to end of line, no state carried
            if c == "-" and i + 1 < n and line[i + 1] == "-":
                i = line.find("\n", i)
                if i == -1:
                    return None
                continue  # the newline branch above closes the line
            # block comment "/* ... */" (PostgreSQL allows nesting)
            if c == "/" and i + 1 < n and line[i + 1] == "*":
                self.comment_depth = 1
                i = self._resume_block_comment(line, i + 2, n)
                continue
            # dollar-quoted string  $tag$ ... $tag$
            if c == "$":
                m = _DOLLAR_TAG_RE.match(line, i)
                if m:
                    self.dollar_tag = m.group(0)
                    i = self._resume_dollar_body(line, m.end(), n)
                    continue
            # single-quoted string  '...'  ('' escapes; E'...' also honors \)
            if c == "'":
                self.in_single_quote = True
                self.single_quote_escaped = (
                    i > 0
                    and line[i - 1] in "Ee"
                    and not (i > 1 and (line[i - 2].isalnum() or line[i - 2] == "_"))
                )
                i = self._resume_single_quote(line, i + 1, n)
                continue
            # quoted identifier  "..."  ("" escapes)
            if c == '"':
                self.in_double_quote = True
                i = self._resume_double_quote(line, i + 1, n)
                continue
            # a backslash outside every context above => a psql meta-command
            if c == "\\":
                word = self._cmd_word(line, i, n)
                if word not in _ALLOWED_PSQL_META_COMMANDS:
                    return (self.lineno, word)
                i += len(word)
                self.at_stmt_start = False
                continue

            self.at_stmt_start = c == ";" or (self.at_stmt_start and c.isspace())
            i += 1
        return None

    @staticmethod
    def _cmd_word(line: str, pos: int, n: int) -> str:
        """Return the meta-command token starting at the backslash at ``pos``."""
        j = pos + 1
        if j < n and line[j] in "!.?\\":
            return line[pos : j + 1]
        k = j
        while k < n and line[k].isalpha():
            k += 1
        return line[pos:k] if k > j else line[pos : pos + 1]

    # Each ``_resume_*`` scans from ``i`` until its context closes (clearing the
    # corresponding state and setting ``at_stmt_start = False``, as psql does
    # once the construct ends) or the line runs out (state stays set, so the
    # next ``feed`` resumes here).  Returning ``n`` ends the line.

    def _resume_block_comment(self, line: str, i: int, n: int) -> int:
        while i < n and self.comment_depth:
            if line[i] == "\n":
                self.lineno += 1
                i += 1
            elif line.startswith("/*", i):
                self.comment_depth += 1
                i += 2
            elif line.startswith("*/", i):
                self.comment_depth -= 1
                i += 2
            else:
                i += 1
        if not self.comment_depth:
            self.at_stmt_start = False
        return i

    def _resume_dollar_body(self, line: str, i: int, n: int) -> int:
        tag = self.dollar_tag
        close = line.find(tag, i)
        if close == -1:
            self.lineno += line.count("\n", i)
            return n
        self.lineno += line.count("\n", i, close)
        self.dollar_tag = None
        self.at_stmt_start = False
        return close + len(tag)

    def _resume_single_quote(self, line: str, i: int, n: int) -> int:
        while i < n:
            ch = line[i]
            if ch == "\n":
                self.lineno += 1
                i += 1
            elif ch == "\\" and self.single_quote_escaped:
                i += 2
            elif ch == "'":
                if i + 1 < n and line[i + 1] == "'":
                    i += 2
                else:
                    i += 1
                    self.in_single_quote = False
                    break
            else:
                i += 1
        if not self.in_single_quote:
            self.at_stmt_start = False
        return i

    def _resume_double_quote(self, line: str, i: int, n: int) -> int:
        while i < n:
            if line[i] == '"':
                if i + 1 < n and line[i + 1] == '"':
                    i += 2
                else:
                    i += 1
                    self.in_double_quote = False
                    break
            else:
                if line[i] == "\n":
                    self.lineno += 1
                i += 1
        if not self.in_double_quote:
            self.at_stmt_start = False
        return i


def _iter_physical_lines(text: str) -> Iterator[str]:
    """Yield ``text`` split on ``\\n`` only, keeping the terminator.

    NOT ``str.splitlines``: that also breaks on ``\\v``/``\\f``/``\\x85``/
    ``\\u2028``, which the scanner treats as ordinary characters — a split there
    would desync its ``at_stmt_start`` bookkeeping inside a string literal.
    """
    start = 0
    while (idx := text.find("\n", start)) != -1:
        yield text[start : idx + 1]
        start = idx + 1
    if start < len(text):
        yield text[start:]


def _find_disallowed_psql_meta_command(text: str) -> tuple[int, str] | None:
    """Return ``(lineno, command)`` of the first psql meta-command in ``text``
    that ``psql`` would INTERPRET and that is not in
    ``_ALLOWED_PSQL_META_COMMANDS``, or ``None`` if the SQL is safe.

    In-memory convenience wrapper over :class:`_PsqlSqlScanner` for callers that
    already hold the SQL (tests, small snippets).  ``_assert_dump_sql_safe``
    streams a file through the same scanner instead — see its docstring.
    """
    scanner = _PsqlSqlScanner()
    for line in _iter_physical_lines(text):
        hit = scanner.feed(line)
        if hit is not None:
            return hit
    return None


def _assert_dump_sql_safe(sql_path: str) -> None:
    """Raise ``RuntimeError`` if ``sql_path`` contains a psql meta-command that a
    ``psql -f`` restore would interpret (shell/file/connection access).

    Streams the file line by line through :class:`_PsqlSqlScanner`: a restore is
    the one operation whose input size is unbounded and attacker-supplied, and
    the previous whole-file ``read()`` cost ~2x the dump size in RSS (a 10 GB
    ``dump.sql`` needed ~20 GB) inside the very worker a memory soft limit
    watches.  Now the peak is one line.

    Read as latin-1 so scanning is byte-exact and decode-error-free regardless
    of the dump's encoding — every meta-command and structural token is ASCII.
    Default (universal) newline handling, so a ``\\r\\n`` dump scans identically
    to a ``\\n`` one.
    """
    scanner = _PsqlSqlScanner()
    hit = None
    with Path(sql_path).open(encoding="latin-1") as fh:
        for line in fh:
            hit = scanner.feed(line)
            if hit is not None:
                break
    if hit is not None:
        lineno, command = hit
        raise RuntimeError(
            f"Refusing to restore: the dump's SQL contains the psql "
            f"meta-command {command!r} (line {lineno}), which would run with "
            f"this server's OS/database privileges. A backup produced by Odoo's "
            f"own dump contains no such command; only \\restrict, \\unrestrict "
            f"and the \\. COPY terminator are permitted."
        )


__all__ = (
    "_PsqlSqlScanner",
    "_assert_dump_sql_safe",
    "_find_disallowed_psql_meta_command",
    "_iter_physical_lines",
)
