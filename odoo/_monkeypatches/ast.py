import ast
import logging
import os
from collections.abc import Callable

_logger = logging.getLogger(__name__)
orig_literal_eval = ast.literal_eval

DEFAULT_BUFFER_SIZE = 102400


def buffer_size_from_env() -> int:
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


def make_literal_eval(buffer_size: int) -> Callable[[str | bytes | ast.AST], object]:
    def literal_eval(expr: str | bytes | ast.AST) -> object:
        if isinstance(expr, str | bytes) and len(expr) > buffer_size:
            msg = "expression can't exceed buffer limit"
            raise ValueError(msg)
        return orig_literal_eval(expr)

    return literal_eval


def patch_module() -> None:
    ast.literal_eval = make_literal_eval(buffer_size_from_env())
