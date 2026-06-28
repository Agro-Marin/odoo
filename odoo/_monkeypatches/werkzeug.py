from types import CodeType
from typing import Any

from werkzeug.datastructures import MultiDict
from werkzeug.routing import Rule
from werkzeug.wrappers import Request, Response


def patch_module() -> None:
    # NOTE: a second set of werkzeug patches lives in ``odoo/http/wrappers.py``
    # (``HTTPException.get_response`` / ``abort`` wrapping into ``odoo.http``
    # Response objects). They cannot move here: this hook runs when ``werkzeug``
    # is first imported, before ``odoo.http`` exists. See that module's note.
    from odoo.tools.json import scriptsafe

    Request.json_module = Response.json_module = scriptsafe

    def _multidict_deepcopy(
        self: MultiDict, memo: dict[int, Any] | None = None
    ) -> MultiDict:
        return orig_deepcopy(self)

    orig_deepcopy = MultiDict.deepcopy
    MultiDict.deepcopy = _multidict_deepcopy  # type: ignore[method-assign]

    _orig_get_func_code = Rule._get_func_code

    @staticmethod  # type: ignore[misc]
    def _get_func_code(code: CodeType, name: str) -> Any:
        assert isinstance(code, CodeType)
        return _orig_get_func_code(code, name)

    Rule._get_func_code = _get_func_code  # type: ignore[method-assign]
