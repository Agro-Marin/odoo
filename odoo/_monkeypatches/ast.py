import ast
import logging
import os

_logger = logging.getLogger(__name__)
orig_literal_eval = ast.literal_eval


def literal_eval(expr: str | bytes | ast.AST) -> object:

    buffer_size = 102400
    buffer_size_env = os.getenv("ODOO_LIMIT_LITEVAL_BUFFER")

    if buffer_size_env:
        if buffer_size_env.isdigit():
            buffer_size = int(buffer_size_env)
        else:
            _logger.error(
                "ODOO_LIMIT_LITEVAL_BUFFER has to be an integer, defaulting to 100KiB"
            )

    # bytes as well as str: literal_eval accepts both and parses them the same
    # way, so checking only str left the cap trivially bypassable by passing the
    # same payload encoded.  An already-parsed ast.AST has no source length to
    # measure and never went through the parser here, so it is out of scope.
    if isinstance(expr, str | bytes) and len(expr) > buffer_size:
        msg = "expression can't exceed buffer limit"
        raise ValueError(msg)

    return orig_literal_eval(expr)


def patch_module() -> None:
    ast.literal_eval = literal_eval
