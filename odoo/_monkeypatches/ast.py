import ast
import logging
import os
from typing import Protocol, cast


class _LiteralEval(Protocol):
    # Not Callable[[...], object]: that spells a positional-only parameter, and
    # this replaces ast.literal_eval, whose parameter is positional-or-keyword.
    def __call__(self, node_or_string: str | bytes | ast.AST) -> object: ...


_logger = logging.getLogger(__name__)
orig_literal_eval = ast.literal_eval

DEFAULT_BUFFER_SIZE = 102400


def get_buffer_size_from_env() -> int:
    raw = os.getenv("ODOO_LIMIT_LITEVAL_BUFFER")
    if not raw:
        return DEFAULT_BUFFER_SIZE
    try:
        size = int(raw)
    except ValueError:
        size = 0
    if size <= 0:
        _logger.error(
            "ODOO_LIMIT_LITEVAL_BUFFER must be a positive integer, got %r; "
            "defaulting to %d bytes",
            raw,
            DEFAULT_BUFFER_SIZE,
        )
        return DEFAULT_BUFFER_SIZE
    return size


def prepare_literal_eval(buffer_size: int) -> _LiteralEval:
    # The parameter keeps the stdlib's name. This function replaces
    # ast.literal_eval wholesale, so a caller spelling the argument by keyword
    # -- ast.literal_eval(node_or_string=src) -- must still reach it.
    def literal_eval(node_or_string: str | bytes | ast.AST) -> object:
        if (
            isinstance(node_or_string, str | bytes)
            and len(node_or_string) > buffer_size
        ):
            msg = "expression can't exceed buffer limit"
            raise ValueError(msg)
        # The guard above accepts bytes so an oversized one is refused here
        # rather than deeper in; the stdlib itself takes str | AST and rejects
        # bytes with its own ValueError, which is what the cast defers to.
        return orig_literal_eval(cast("str | ast.AST", node_or_string))

    return literal_eval


def patch_module() -> None:
    ast.literal_eval = prepare_literal_eval(get_buffer_size_from_env())
