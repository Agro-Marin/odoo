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

# Log under the public module name, like ``_db_helpers``: operators filter on
# ``odoo.service.db`` and should not have to learn the private split.
_logger = logging.getLogger("odoo.service.db")


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

# PostgreSQL identifier character classes, verbatim from the backend lexer
# (``src/backend/parser/scan.l``, shared by psql's ``psqlscan.l``)::
#
#     ident_start  [A-Za-z\200-\377_]
#     ident_cont   [A-Za-z\200-\377_0-9\$]
#
# Note that ``$`` is an identifier CONTINUATION character.  Because flex takes
# the LONGEST match, ``a$b$c`` is therefore ONE identifier and not ``a`` followed
# by the dollar-quote delimiter ``$b$`` — verified against PostgreSQL 18, which
# creates a table by that literal name.  The same rule makes the ``E`` of
# ``fooE'x'`` the tail of the identifier ``fooE``, leaving a PLAIN literal in
# which a backslash escapes nothing.  ``_ident_run_start`` below is how this
# character-at-a-time scanner reproduces that longest-match behaviour.
_IDENT_START_ASCII = frozenset(string.ascii_letters + "_")
_IDENT_CONT_ASCII = frozenset(string.ascii_letters + string.digits + "_$")

# Longest physical line :func:`_assert_dump_sql_safe` will buffer.  The largest
# line measured across real Odoo dumps was ~1.7 MB (a wide ``COPY`` data row), so
# 64 MiB leaves ~38x headroom while still bounding the scan; an operator with a
# genuinely enormous row can raise it via ``ODOO_DUMP_SCAN_MAX_LINE``.  The floor
# keeps a hostile or fat-fingered value from rejecting ordinary dumps.
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
        "at_stmt_start",
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
        # The scanner's stand-in for flex's longest-match rule (see
        # ``_IDENT_START_ASCII``): where does the token under the cursor begin?
        # ``_ident_run_start`` is the index in the CURRENT line at which the run
        # of identifier-continuation characters ending just before the cursor
        # started (-1 for "no run"), and ``_ident_run_is_ident`` says whether that
        # run is an identifier as opposed to a numeric literal.  Both are purely
        # intra-line: a newline is not an identifier character, so no run can
        # straddle a ``feed`` boundary.  O(1) per character.
        self._ident_run_start = -1
        self._ident_run_is_ident = False
        self.at_stmt_start = True  # start-of-file / just after a ';' or newline
        # Carried lexical contexts — the only state a line boundary can split.
        self.in_copy_data = False
        # A ``COPY ... FROM stdin`` has been seen but its terminating ``;`` has
        # not: the statement is still buffered, so psql is NOT yet reading data.
        self.copy_pending = False
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
        # A new physical line always starts outside any identifier run.
        self._reset_ident_run()

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
            #
            # Only ARM the switch here.  psql starts reading COPY data when the
            # statement is EXECUTED and the server answers PGRES_COPY_IN — that
            # is, at its terminating ``;`` — not when the word ``COPY`` is read.
            # Until then the statement merely sits in psql's query buffer, and
            # psql still interprets meta-commands, so switching early let
            # ``COPY t FROM stdin`` with NO semicolon swallow a following ``\!``
            # as if it were data (verified: psql ran the shell command and still
            # exited 0).  The ``;`` branch in the tail below completes the switch.
            if self.at_stmt_start and c in "Cc" and not self.copy_pending:
                rest = line[i:].rstrip("\n").rstrip("\r")
                if _COPY_FROM_STDIN_RE.match(rest):
                    self.copy_pending = True
                # Deliberately no ``continue``: the rest of the line is lexed as
                # ordinary SQL so a meta-command before the ``;`` is still caught.

            # line comment "-- ..." — runs to end of line, no state carried
            if c == "-" and i + 1 < n and line[i + 1] == "-":
                i = line.find("\n", i)
                if i == -1:
                    return None
                continue  # the newline branch above closes the line
            # block comment "/* ... */" (PostgreSQL allows nesting)
            if c == "/" and i + 1 < n and line[i + 1] == "*":
                self.comment_depth = 1
                self._reset_ident_run()
                i = self._resume_block_comment(line, i + 2, n)
                continue
            # dollar-quoted string  $tag$ ... $tag$ — but only where a token may
            # begin.  Inside an identifier ``$`` is just another identifier
            # character (``a$b$c``); after a NUMBER it is a real delimiter
            # (PostgreSQL 18 reports the error in ``SELECT 1$t$x$t$`` at the
            # token ``$t$x$t$``), which is why the test is "the run so far starts
            # with an identifier-start character", not merely "a run exists".
            if c == "$" and not self._continues_identifier():
                m = _DOLLAR_TAG_RE.match(line, i)
                if m:
                    self.dollar_tag = m.group(0)
                    self._reset_ident_run()
                    i = self._resume_dollar_body(line, m.end(), n)
                    continue
            # single-quoted string  '...'  ('' escapes; E'...' also honors \)
            if c == "'":
                self.in_single_quote = True
                # ``E'`` introduces an escape string only where that ``E`` STARTS
                # a token.  In ``fooE'x'`` the ``E`` is the tail of the identifier
                # ``fooE``, so the literal is plain and ``\`` escapes nothing.  The
                # ``E`` has already been folded into the run, so it began a token
                # iff the run began AT it (``run_start == i - 1``) or the run is
                # not an identifier at all (``1E'x'`` — a number, then an E-string).
                # ``E'`` introduces an escape string only where that ``E`` STARTS
                # a token, i.e. where the identifier run began at the ``E`` itself.
                # In ``fooE'x'`` the run began earlier, so the ``E`` is the tail of
                # the identifier ``fooE`` and the literal is PLAIN — a backslash in
                # it escapes nothing, so the literal ends at the next quote.
                self.single_quote_escaped = (
                    i > 0 and line[i - 1] in "Ee" and self._ident_run_start == i - 1
                )
                self._reset_ident_run()
                i = self._resume_single_quote(line, i + 1, n)
                continue
            # quoted identifier  "..."  ("" escapes)
            if c == '"':
                self.in_double_quote = True
                self._reset_ident_run()
                i = self._resume_double_quote(line, i + 1, n)
                continue
            # a backslash outside every context above => a psql meta-command
            if c == "\\":
                word = self._cmd_word(line, i, n)
                if word not in _ALLOWED_PSQL_META_COMMANDS:
                    return (self.lineno, word)
                i += len(word)
                self.at_stmt_start = False
                self._reset_ident_run()
                continue

            # Extend, RESTART or break the identifier run (see
            # ``_ident_run_start``).  The restart is the subtle case: ``$`` and
            # the digits are identifier-CONTINUATION characters that cannot START
            # an identifier, so in ``9a$b$c`` flex ends the numeric token ``9`` at
            # the ``a`` and begins an identifier there — which makes the later
            # ``$b$`` part of that identifier, not a dollar-quote delimiter.
            # Without the restart the whole run reads as digit-led, the scanner
            # opens a phantom dollar body and swallows the rest of the dump.
            if _is_ident_cont(c):
                if self._ident_run_start < 0:
                    self._ident_run_start = i
                    self._ident_run_is_ident = _is_ident_start(c)
                elif not self._ident_run_is_ident and _is_ident_start(c):
                    self._ident_run_start = i
                    self._ident_run_is_ident = True
            else:
                self._reset_ident_run()

            if c == ";":
                self.at_stmt_start = True
                if self.copy_pending:
                    # The armed ``COPY ... FROM stdin`` is executed here, so psql
                    # switches to reading data with the NEXT line.  The remainder
                    # of this line keeps being lexed as SQL (nothing follows the
                    # ``;`` in a real dump, and flagging a meta-command there is
                    # the conservative direction).
                    self.copy_pending = False
                    self.in_copy_data = True
            else:
                self.at_stmt_start = self.at_stmt_start and c.isspace()
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
        """Forget the current identifier run: the next character starts a token."""
        self._ident_run_start = -1
        self._ident_run_is_ident = False

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
    ``psql -f`` restore would interpret (shell/file/connection access), or if a
    single line is too long to scan within a bounded amount of memory.

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
        # ``readline(max_line + 1)`` never buffers more than that many characters,
        # so a line without a terminator cannot grow the peak.  A returned chunk
        # that is over the cap AND has no newline means the real line is longer
        # still: refuse rather than keep reading it in fragments, which would feed
        # the scanner a split token and desync its lexical state — the exact class
        # of divergence that makes this scanner bypassable.
        while chunk := fh.readline(max_line + 1):
            if len(chunk) > max_line and not chunk.endswith("\n"):
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
            f"own dump contains no such command; only \\restrict, \\unrestrict "
            f"and the \\. COPY terminator are permitted."
        )


__all__ = (
    "_PsqlSqlScanner",
    "_assert_dump_sql_safe",
    "_find_disallowed_psql_meta_command",
    "_iter_physical_lines",
)
