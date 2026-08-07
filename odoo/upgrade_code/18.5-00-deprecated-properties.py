"""Convert deprecated recordset properties to their ``env`` equivalents.

``x._cr`` / ``x._uid`` / ``x._context`` -> ``x.env.cr`` / ``.uid`` / ``.context``.

TESTED: ``odoo/tools/tests/test_upgrade_code_deprecated_properties.py``.

This was a bare regex until 2026-08 and mis-rewrote five of seven realistic
shapes, three of them into code that does not run: it edited string literals and
comments, turned ``self.env._cr`` into ``self.env.env.cr``, and turned
``self._cr = cr`` in a non-recordset ``__init__`` into ``self.env.cr = cr``.
Against this repository it would have broken ``db/savepoint.py``,
``tools/translate.py`` and ``web/controllers/json_helpers.py``.

It is now driven by ``tokenize``: strings and comments yield no NAME tokens, and
the neighbouring tokens let it skip an owner that is already ``env`` and skip
assignment targets. One limitation is inherent — whether ``x`` is a recordset
cannot be decided statically, so a read on a non-recordset is still converted.
See ``odoo/cli/upgrade_code.py`` before running this.
"""

import io
import logging
import tokenize
import typing

if typing.TYPE_CHECKING:
    from odoo.cli.upgrade_code import FileManager

_DEPRECATED = ("_cr", "_uid", "_context")


def _rewrites(source: str) -> list[tuple[int, int, str]]:
    """Byte-free (line, col) spans to replace, computed from real tokens.

    The previous implementation was a bare regex over the raw text::

        re.compile(r"\\._(cr|uid|context)\\b").sub(r".env.\\1", content)

    which is unsound in three ways, all of which produce code that is worse than
    what it replaced:

    * ``self.env._cr``      -> ``self.env.env.cr``   (broken)
    * ``conn._cr = cur``    -> ``conn.env.cr = cur`` (broken; ``conn`` has no env)
    * ``'use ._context'``   -> ``'use .env.context'`` (rewrites a string literal)

    Working from the tokenizer removes all three: strings and comments never
    yield NAME tokens, and the token *before* the dot is available, so an
    attribute already reached through ``env`` can be left alone.
    """
    out: list[tuple[int, int, str]] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable input is left untouched rather than half-rewritten.
        return out

    meaningful = [
        t for t in tokens if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT)
    ]
    for index, token in enumerate(meaningful):
        if token.type != tokenize.NAME or token.string not in _DEPRECATED:
            continue
        if index < 1:
            continue
        dot = meaningful[index - 1]
        if dot.type != tokenize.OP or dot.string != ".":
            continue  # a bare `_context = {}` definition, not an attribute read
        if index >= 2:
            owner = meaningful[index - 2]
            if owner.type == tokenize.NAME and owner.string == "env":
                continue  # `env._cr` is already the runtime object
        nxt = meaningful[index + 1] if index + 1 < len(meaningful) else None
        if nxt is not None and nxt.type == tokenize.OP and nxt.string in ("=", ":="):
            # An ASSIGNMENT TARGET. `record.env.cr = ...` is not a thing, so a
            # `x._cr = ...` is by construction not the deprecated recordset
            # property this script converts -- it is some other object that
            # happens to use the name (`conn._cr = make_cursor()`).
            continue
        out.append((token.start[0], token.start[1], token.string))
    return out


def upgrade(file_manager: FileManager) -> None:
    log = logging.getLogger(__name__)

    for file in file_manager:
        if file.path.suffix != ".py":
            continue
        source = file.content
        spans = _rewrites(source)
        if not spans:
            continue
        lines = source.splitlines(keepends=True)
        # Apply back-to-front so earlier offsets stay valid.
        for lineno, col, name in sorted(spans, reverse=True):
            line = lines[lineno - 1]
            if line[col : col + len(name)] != name:
                log.warning(
                    "%s:%s: token offset did not match %r; skipped",
                    file.path,
                    lineno,
                    name,
                )
                continue
            lines[lineno - 1] = (
                line[:col] + "env." + name[1:] + line[col + len(name) :]
            )
        file.content = "".join(lines)
