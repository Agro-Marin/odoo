import ast
import logging
import os
from typing import Protocol, cast


class _LiteralEval(Protocol):
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
    def literal_eval(node_or_string: str | bytes | ast.AST) -> object:
        if (
            isinstance(node_or_string, str | bytes)
            and len(node_or_string) > buffer_size
        ):
            msg = "expression can't exceed buffer limit"
            raise ValueError(msg)
        return orig_literal_eval(cast("str | ast.AST", node_or_string))

    return literal_eval


def patch_module() -> None:
    ast.literal_eval = prepare_literal_eval(get_buffer_size_from_env())
