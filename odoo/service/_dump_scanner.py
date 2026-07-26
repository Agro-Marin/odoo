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

Depends only on the stdlib plus the leaf ``._env`` helper — no import cycle with
``db``.
"""

from __future__ import annotations

import logging
import re
import string
from pathlib import Path
from typing import TYPE_CHECKING

from ._env import env_int

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TextIO

_logger = logging.getLogger("odoo.service.db")


_META_ARG_NONE = r"[ \t]*(?:\r?\n|\Z)"
_META_ARG_KEY = r"[ \t]+[A-Za-z0-9]+[ \t]*(?:\r?\n|\Z)"
_ALLOWED_PSQL_META_COMMANDS: dict[str, re.Pattern[str]] = {
    "\\.": re.compile(_META_ARG_NONE),
    "\\restrict": re.compile(_META_ARG_KEY),
    "\\unrestrict": re.compile(_META_ARG_KEY),
}

_COPY_WORD_MAX_LEN = 5
_DOLLAR_TAG_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")

_IDENT_START_ASCII = frozenset(string.ascii_letters + "_")
_IDENT_CONT_ASCII = frozenset(string.ascii_letters + string.digits + "_$")

_DEFAULT_MAX_SCAN_LINE = 64 * 1024 * 1024
_MIN_MAX_SCAN_LINE = 4 * 1024 * 1024


def _is_ident_start(c: str) -> bool:
    return c in _IDENT_START_ASCII or c >= "\x80"


def _is_ident_cont(c: str) -> bool:
    return c in _IDENT_CONT_ASCII or c >= "\x80"


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
        "_ident_run_is_ident",
        "_ident_run_start",
        "_prev_word",
        "_stmt_is_copy",
        "_stmt_seen_token",
        "_word",
        "comment_depth",
        "copy_pending",
        "dollar_tag",
        "in_copy_data",
        "in_double_quote",
        "in_single_quote",
        "lineno",
        "single_quote_escaped",
    )

    def __init__(self) -> None:
        self.lineno = 1
        self._word = ""
        self._prev_word = ""
        self._stmt_seen_token = False
        self._stmt_is_copy = False
        self._ident_run_start = -1
        self._ident_run_is_ident = False
        self.in_copy_data = False
        self.copy_pending = False
        self.comment_depth = 0
        self.dollar_tag: str | None = None
        self.in_single_quote = False
        self.single_quote_escaped = False
        self.in_double_quote = False

    def feed(self, line: str) -> tuple[int, str] | None:
        """Scan one physical line (``\\n``-terminated except possibly the last).

        Returns ``(lineno, command)`` for the first disallowed meta-command, or
        ``None``.  Once it returns a hit the scanner must not be fed again.
        """
        n = len(line)
        self._reset_ident_run()

        if self.in_copy_data:
            self.lineno += 1
            if line.rstrip("\n").rstrip("\r") == "\\.":
                self.in_copy_data = False
                self._reset_statement()
            return None

        i = 0
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
                return None

            if c == "-" and i + 1 < n and line[i + 1] == "-":
                i = line.find("\n", i)
                if i == -1:
                    return None
                continue
            if c == "/" and i + 1 < n and line[i + 1] == "*":
                self.comment_depth = 1
                self._reset_ident_run()
                i = self._resume_block_comment(line, i + 2, n)
                continue
            if c == "$" and not self._continues_identifier():
                m = _DOLLAR_TAG_RE.match(line, i)
                if m:
                    self.dollar_tag = m.group(0)
                    self._reset_ident_run()
                    self._note_opaque_token()
                    i = self._resume_dollar_body(line, m.end(), n)
                    continue
            if c == "'":
                self.in_single_quote = True
                self.single_quote_escaped = (
                    i > 0 and line[i - 1] in "Ee" and self._ident_run_start == i - 1
                )
                self._reset_ident_run()
                self._note_opaque_token()
                i = self._resume_single_quote(line, i + 1, n)
                continue
            if c == '"':
                self.in_double_quote = True
                self._reset_ident_run()
                self._note_opaque_token()
                i = self._resume_double_quote(line, i + 1, n)
                continue
            if c == "\\":
                word = self._cmd_word(line, i, n)
                arg_pattern = _ALLOWED_PSQL_META_COMMANDS.get(word)
                if arg_pattern is None:
                    return (self.lineno, word)
                if not arg_pattern.match(line, i + len(word)):
                    end = line.find("\n", i)
                    text = line[i:] if end == -1 else line[i:end]
                    return (self.lineno, text.rstrip()[:80])
                self._reset_ident_run()
                self._note_opaque_token()
                nl = line.find("\n", i)
                if nl == -1:
                    return None
                i = nl
                continue

            if _is_ident_cont(c):
                if self._ident_run_start < 0:
                    self._ident_run_start = i
                    self._ident_run_is_ident = _is_ident_start(c)
                    self._word = c
                elif not self._ident_run_is_ident and _is_ident_start(c):
                    self._flush_word()
                    self._ident_run_start = i
                    self._ident_run_is_ident = True
                    self._word = c
                elif len(self._word) <= _COPY_WORD_MAX_LEN:
                    self._word += c
            else:
                self._reset_ident_run()

            if c == ";":
                if self.copy_pending:
                    self.copy_pending = False
                    self.in_copy_data = True
                self._reset_statement()
            i += 1
        return None

    def _continues_identifier(self) -> bool:
        """Is the cursor sitting inside an identifier rather than at a token start?

        ``True`` iff the run of identifier-continuation characters ending just
        before the cursor began with an identifier-START character.  A run that
        began with a digit is a numeric literal, not an identifier, so a ``$``
        after it really does open a dollar-quoted string.

        This reproduces flex's longest-match rule in O(1), which matters: an
        earlier backward-scanning version had to cap its lookback to stay linear
        on a hostile line, and the cap was itself a bypass.  Answering "not a
        dollar quote" is NOT the safe fallback it looks like — the scanner then
        lexes the body\'s contents as SQL, and a lone ``\'`` in there opens a
        phantom string literal that swallows every later meta-command.  Only
        exactness is safe; there is no conservative direction here.
        """
        return self._ident_run_is_ident

    def _reset_ident_run(self) -> None:
        """Forget the current identifier run: the next character starts a token.

        Every call site is a point where a code-context token ENDS (a non-word
        character, the opening of a string / quoted identifier / comment /
        dollar body, a meta-command, a line boundary), so this is also where the
        accumulated word is handed to the COPY state machine.
        """
        self._ident_run_start = -1
        self._ident_run_is_ident = False
        self._flush_word()

    def _flush_word(self) -> None:
        """Feed the just-completed code-context word to the COPY state machine.

        This is what decides ``copy_pending``, and it deliberately reads the
        LEXED token stream rather than the raw line.  A regex over raw text —
        which is what this replaced — cannot tell ``COPY t FROM stdin;`` from
        ``COPY (SELECT 1) TO STDOUT; -- FROM stdin``: the second is a perfectly
        valid statement that psql executes WITHOUT entering COPY-data mode, so
        arming the switch on it made the scanner skip every following line as
        "data" while psql went on interpreting them — including ``\\!``.  That
        was a silent remote-code-execution bypass of this whole module (psql
        even exits 0, so the restore reports success).  The same held for
        ``FROM stdin`` occurring in a block comment or inside a string literal.

        Mirroring psql: it enters COPY-data mode when the server answers
        PGRES_COPY_IN, which happens only for a statement whose first token is
        ``COPY`` and which really does say ``FROM STDIN``.  Comments contribute
        no token; strings, quoted identifiers and dollar bodies contribute an
        opaque one (:meth:`_note_opaque_token`) that can be neither.

        Over-detection is safe here and under-detection is loud: a statement
        that arms the switch but errors out server-side stops the restore under
        ``ON_ERROR_STOP=1``, and a real COPY block that failed to arm would have
        its ``\\N`` NULL markers flagged as meta-commands (a refused restore,
        never a silent pass).
        """
        word = self._word
        if not word:
            return
        self._word = ""
        upper = word.upper()
        if not self._stmt_seen_token:
            self._stmt_seen_token = True
            self._stmt_is_copy = upper == "COPY"
        elif self._stmt_is_copy and self._prev_word == "FROM" and upper == "STDIN":
            self.copy_pending = True
        self._prev_word = upper

    def _note_opaque_token(self) -> None:
        """Record a token whose text this scanner deliberately does not read.

        A string literal, quoted identifier, dollar-quoted body or meta-command
        occupies a token slot in the statement: it can never BE the ``COPY``
        keyword (``"COPY" t FROM stdin`` is a syntax error, not the COPY
        command) and it breaks the ``FROM``/``STDIN`` adjacency.
        """
        self._stmt_seen_token = True
        self._prev_word = ""

    def _reset_statement(self) -> None:
        """Start a fresh statement for COPY detection (after ``;`` or ``\\.``)."""
        self._word = ""
        self._prev_word = ""
        self._stmt_seen_token = False
        self._stmt_is_copy = False

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
        return i

    def _resume_dollar_body(self, line: str, i: int, n: int) -> int:
        tag = self.dollar_tag
        close = line.find(tag, i)
        if close == -1:
            self.lineno += line.count("\n", i)
            return n
        self.lineno += line.count("\n", i, close)
        self.dollar_tag = None
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
        return i


def _iter_physical_lines(text: str) -> Iterator[str]:
    """Yield ``text`` split on ``\\n`` only, keeping the terminator.

    NOT ``str.splitlines``: that also breaks on ``\\v``/``\\f``/``\\x85``/
    ``\\u2028``, which the scanner treats as ordinary characters — a split there
    would desync its token bookkeeping inside a string literal.
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


def _drain_physical_line(fh: TextIO, cap: int) -> None:
    """Discard the remainder of the current physical line in ``cap``-sized reads.

    Used only for an oversized COPY-*data* line (see :func:`_assert_dump_sql_safe`):
    the first over-cap chunk has already been read and dropped, so this consumes
    the rest of the line — up to and including its newline, or EOF — without ever
    buffering more than ``cap`` characters.  The memory bound therefore holds on a
    data line of ANY length.
    """
    while True:
        part = fh.readline(cap)
        if not part or part.endswith("\n"):
            return


def _assert_dump_sql_safe(sql_path: str) -> None:
    """Raise ``RuntimeError`` if ``sql_path`` contains a psql meta-command that a
    ``psql -f`` restore would interpret (shell/file/connection access), or if a
    single SQL-context line is too long to scan within a bounded amount of memory.

    Streams the file line by line through :class:`_PsqlSqlScanner`: a restore is
    the one operation whose input size is unbounded and attacker-supplied, and
    the previous whole-file ``read()`` cost ~2x the dump size in RSS (a 10 GB
    ``dump.sql`` needed ~20 GB) inside the very worker a memory soft limit
    watches.  Now the peak is one line — but the ATTACKER chooses the line
    lengths, so that bound only holds if it is enforced: a newline-free dump
    restores the old O(file) peak exactly (measured: a 419 MB single line drove
    RSS to 879 MB, the decoded ``str`` roughly doubling the bytes).  Hence the
    ``readline`` size cap below, which is what actually makes the peak bounded.

    Read as latin-1 so scanning is byte-exact and decode-error-free regardless
    of the dump's encoding — every meta-command and structural token is ASCII.
    Default (universal) newline handling, so a ``\\r\\n`` dump scans identically
    to a ``\\n`` one.
    """
    max_line = env_int(
        "ODOO_DUMP_SCAN_MAX_LINE",
        _DEFAULT_MAX_SCAN_LINE,
        minimum=_MIN_MAX_SCAN_LINE,
        logger=_logger,
    )
    scanner = _PsqlSqlScanner()
    hit = None
    with Path(sql_path).open(encoding="latin-1") as fh:
        while chunk := fh.readline(max_line + 1):
            if len(chunk) > max_line and not chunk.endswith("\n"):
                if scanner.in_copy_data:
                    _drain_physical_line(fh, max_line + 1)
                    scanner.lineno += 1
                    continue
                raise RuntimeError(
                    f"Refusing to restore: the dump's SQL has a line longer than "
                    f"{max_line} characters (at line {scanner.lineno}), which "
                    f"cannot be scanned within a bounded amount of memory. A "
                    f"backup produced by Odoo's own dump has no such line; raise "
                    f"ODOO_DUMP_SCAN_MAX_LINE if this dump is genuinely legitimate."
                )
            hit = scanner.feed(chunk)
            if hit is not None:
                break
    if hit is not None:
        lineno, command = hit
        raise RuntimeError(
            f"Refusing to restore: the dump's SQL contains the psql "
            f"meta-command {command!r} (line {lineno}), which would run with "
            f"this server's OS/database privileges. A backup produced by Odoo's "
            f"own dump contains no such command; the only permitted forms are "
            f"``\\restrict <key>`` / ``\\unrestrict <key>`` with an alphanumeric "
            f"key, and the ``\\.`` COPY terminator alone on its line."
        )


__all__ = (
    "_PsqlSqlScanner",
    "_assert_dump_sql_safe",
    "_find_disallowed_psql_meta_command",
    "_iter_physical_lines",
)
