import io
import logging
import tokenize
import typing

if typing.TYPE_CHECKING:
    from odoo.cli.upgrade_code import FileManager

_DEPRECATED = ("_cr", "_uid", "_context")


def _rewrites(source: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError, IndentationError, SyntaxError:
        # Unparseable input is left untouched rather than half-rewritten.
        return out

    meaningful = [
        t
        for t in tokens
        if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT)
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
            lines[lineno - 1] = line[:col] + "env." + name[1:] + line[col + len(name) :]
        file.content = "".join(lines)
