import annotationlib
import functools
import inspect
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from werkzeug.exceptions import (
    NotFound,
    UnprocessableEntity,
)

from odoo import http
from odoo.http import request
from odoo.models import BaseModel
from odoo.service.model import get_public_method
from odoo.tools import frozendict

_logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=4096)
def _signature(func):
    """The signature of a public model method, computed once per registry class.

    `get_public_method` returns the unbound class function, which is stable for
    the life of a registry, so this caches cleanly. FORWARDREF is not optional:
    the annotations name types the ORM only imports under TYPE_CHECKING, and
    plain `inspect.signature` raises trying to evaluate them.
    """
    return inspect.signature(func, annotation_format=annotationlib.Format.FORWARDREF)


class WebJson2Controller(http.Controller):
    def _web_json_2_rpc_readonly(self, rule, args):
        try:
            model_name = args['__model__']
            method_name = args['__method__']
            Model = request.registry[model_name]
        except KeyError:
            # no need of a read/write cursor to send a 404 http error
            return True
        for cls in Model.mro():
            method = getattr(cls, method_name, None)
            if method is not None and hasattr(method, '_readonly'):
                return method._readonly
        return False

    # Take over /json/<path:subpath>
    @http.route(
        ['/json/2', '/json/2/<path:subpath>'],
        auth='public',
        type='json2',
        readonly=True,
        methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'],
    )
    def web_json_2_404(self, subpath=None):
        e = "Did you mean POST /json/2/<model>/<method>?"
        raise request.not_found(e)

    @http.route(
        '/json/2/<__model__>/<__method__>',
        methods=['POST'],
        auth='bearer',
        type='json2',
        readonly=_web_json_2_rpc_readonly,
        save_session=False,
    )
    def web_json_2_rpc(
        self,
        __model__: str,
        __method__: str,
        ids: Sequence[int] = (),
        context: Mapping[str, Any] = frozendict(),
        **kwargs,
    ):
        try:
            Model = request.env[__model__].with_context(context)
        except KeyError as exc:
            e = f"the model {__model__!r} does not exist"
            raise NotFound(e) from exc

        try:
            func = get_public_method(Model, __method__)
        except AttributeError as exc:
            raise NotFound(exc.args[0]) from exc
        if hasattr(func, '_api_model') and ids:
            e = f"cannot call {__model__}.{__method__} with ids"
            raise UnprocessableEntity(e)

        records = Model.browse(ids)
        # Bind before calling so a caller's own argument mistake is a 422 and
        # not confused with a TypeError raised inside the method itself.
        try:
            _signature(func).bind(records, **kwargs)
        except TypeError as exc:
            raise UnprocessableEntity(exc.args[0]) from exc

        result = func(records, **kwargs)
        if isinstance(result, BaseModel):
            result = result.ids

        return result
