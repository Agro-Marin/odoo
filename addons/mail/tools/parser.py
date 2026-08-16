import ast
import typing

from odoo.exceptions import ValidationError
from odoo.tools import is_list_of

if typing.TYPE_CHECKING:
    from odoo.api import Environment


def parse_res_ids(
    res_ids: str | list[int] | bool | None, env: Environment
) -> list[int] | str | bool | None:
    if is_list_of(res_ids, int) or not res_ids:
        return res_ids
    error_msg = env._(
        "Invalid res_ids %(res_ids_str)s (type %(res_ids_type)s)",
        res_ids_str=res_ids,
        res_ids_type=str(res_ids.__class__.__name__),
    )
    try:
        res_ids = ast.literal_eval(res_ids)
    except Exception as e:
        raise ValidationError(error_msg) from e

    if not is_list_of(res_ids, int):
        raise ValidationError(error_msg)

    return res_ids
