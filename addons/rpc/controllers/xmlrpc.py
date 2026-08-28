import logging
import traceback
import xmlrpc.client
from collections import defaultdict
from datetime import date, datetime

from markupsafe import Markup

import odoo.exceptions
from odoo.fields import Command, Date, Datetime
from odoo.http import Controller, Response, dispatch_rpc, request, route
from odoo.tools import lazy
from odoo.tools.misc import ReadonlyDict, frozendict

from .common import detach_database, warn_endpoint_is_deprecated

logger = logging.getLogger(__name__)

# XML-RPC fault codes. Some care must be taken when changing these: the
# constants are also defined client-side and must remain in sync.
# User code must use the exceptions defined in ``odoo.exceptions`` (not
# create directly ``xmlrpc.client.Fault`` objects).
RPC_FAULT_CODE_APPLICATION_ERROR = 1
RPC_FAULT_CODE_WARNING = 2
RPC_FAULT_CODE_ACCESS_DENIED = 3
RPC_FAULT_CODE_ACCESS_ERROR = 4

# 0 to 31, excluding tab, newline, and carriage return
CONTROL_CHARACTERS = dict.fromkeys(set(range(32)) - {9, 10, 13})


def _format_traceback(e: BaseException) -> str:
    """The traceback of *this* exception, rather than of whatever is in flight.

    Both handlers used to read `sys.exc_info()`, which is the exception the
    *caller's* `except` block is handling. Inside `xmlrpc_1`/`xmlrpc_2` that is
    the same object, but it makes both functions depend on ambient state
    instead of their own argument: called anywhere else -- a unit test, a
    second surface reusing the mapping -- `sys.exc_info()` is `(None, None,
    None)` and the fault carries the string "NoneType: None" in place of the
    error.
    """
    return "".join(traceback.format_exception(type(e), e, e.__traceback__))


def xmlrpc_handle_exception_int(e):
    if isinstance(e, odoo.exceptions.RedirectWarning):
        fault = xmlrpc.client.Fault(RPC_FAULT_CODE_WARNING, str(e))
    elif isinstance(e, odoo.exceptions.AccessError):
        fault = xmlrpc.client.Fault(RPC_FAULT_CODE_ACCESS_ERROR, str(e))
    elif isinstance(e, odoo.exceptions.AccessDenied):
        fault = xmlrpc.client.Fault(RPC_FAULT_CODE_ACCESS_DENIED, str(e))
    elif isinstance(e, odoo.exceptions.UserError):
        fault = xmlrpc.client.Fault(RPC_FAULT_CODE_WARNING, str(e))
    else:
        fault = xmlrpc.client.Fault(
            RPC_FAULT_CODE_APPLICATION_ERROR, _format_traceback(e)
        )

    return dumps(fault)


def xmlrpc_handle_exception_string(e):
    if isinstance(e, odoo.exceptions.RedirectWarning):
        fault = xmlrpc.client.Fault(f"warning -- Warning\n\n{e}", "")
    elif isinstance(e, odoo.exceptions.MissingError):
        fault = xmlrpc.client.Fault(f"warning -- MissingError\n\n{e}", "")
    elif isinstance(e, odoo.exceptions.AccessError):
        fault = xmlrpc.client.Fault(f"warning -- AccessError\n\n{e}", "")
    elif isinstance(e, odoo.exceptions.AccessDenied):
        fault = xmlrpc.client.Fault("AccessDenied", str(e))
    elif isinstance(e, odoo.exceptions.UserError):
        fault = xmlrpc.client.Fault(f"warning -- UserError\n\n{e}", "")
    # InternalError
    else:
        fault = xmlrpc.client.Fault(str(e), _format_traceback(e))

    return dumps(fault)


class _MarshallerDispatch(dict):
    """Marshaller dispatch table that also answers for ``ReadonlyDict`` subclasses.

    ``xmlrpc.client.Marshaller`` looks handlers up by exact ``type(value)``, so a
    subclass of a registered type is a miss, and its own fallback for a miss needs
    a ``__dict__`` that ``ReadonlyDict.__slots__`` denies. Widening the lookup for
    this one hierarchy keeps ``LangData`` & co. marshallable without extending the
    same courtesy to subclasses of ``str`` or ``int``, which the interpreter
    refuses on purpose because their instances do not round-trip.
    """

    def __missing__(self, cls):
        # `issubclass()` raises TypeError rather than returning False when handed
        # a non-class, so the key is type-checked before it is asked about. The
        # only non-type key in play is the interpreter's "_arbitrary_instance"
        # fallback, and copying `Marshaller.dispatch` brings that key along, so
        # today it is found and never reaches here -- measured. The guard is for
        # the day it is not: a TypeError out of a dispatch miss reads as a
        # marshalling bug, a KeyError reads as the missing handler it is.
        if isinstance(cls, type) and issubclass(cls, ReadonlyDict):
            # dict.__getitem__, not self[...]: were the ReadonlyDict entry below
            # ever dropped, a plain lookup would re-enter this method and recurse
            # until the stack ran out instead of raising KeyError.
            handler = self[cls] = dict.__getitem__(self, ReadonlyDict)
            return handler
        raise KeyError(cls)


class OdooMarshaller(xmlrpc.client.Marshaller):
    dispatch = _MarshallerDispatch(xmlrpc.client.Marshaller.dispatch)

    def dump_frozen_dict(self, value, write):
        value = dict(value)
        self.dump_struct(value, write)

    # By default, in xmlrpc, bytes are converted to xmlrpc.client.Binary object.
    # Historically, odoo is sending binary as base64 string.
    # In python 3, base64.b64{de,en}code() methods now works on bytes.
    def dump_bytes(self, value, write):
        self.dump_unicode(value.decode(), write)

    def dump_datetime(self, value, write):
        # override to marshall as a string for backwards compatibility
        value = Datetime.to_string(value)
        self.dump_unicode(value, write)

    # convert date objects to strings in iso8061 format.
    def dump_date(self, value, write):
        value = Date.to_string(value)
        self.dump_unicode(value, write)

    def dump_lazy(self, value, write):
        v = value._value
        return self.dispatch[type(v)](self, v, write)

    def dump_unicode(self, value, write):
        # XML 1.0 disallows control characters, remove them otherwise they break clients
        return super().dump_unicode(value.translate(CONTROL_CHARACTERS), write)

    dispatch[frozendict] = dump_frozen_dict
    # Unlike frozendict, a ReadonlyDict is not a dict, so dispatch-by-exact-type
    # misses it and xmlrpc.client's own fallback cannot take it either.
    # `Environment.context` and the translation caches are ReadonlyDicts that can
    # reach a response; `Field.context` was one too until it moved to frozendict.
    dispatch[ReadonlyDict] = dump_frozen_dict
    dispatch[bytes] = dump_bytes
    dispatch[datetime] = dump_datetime
    dispatch[date] = dump_date
    dispatch[lazy] = dump_lazy
    dispatch[str] = dump_unicode
    dispatch[Command] = dispatch[int]
    dispatch[defaultdict] = dispatch[dict]
    # `str(value)` is load-bearing, not tidying: `Markup.replace` escapes its
    # replacement, so xmlrpc.client's own `escape()` turns "&" into "&amp;amp;"
    # when handed a Markup. Marshalling one as itself double-escapes every
    # rendered HTML field on the wire.
    dispatch[Markup] = lambda self, value, write: self.dispatch[str](
        self, str(value), write
    )


def dumps(params: list | tuple | xmlrpc.client.Fault) -> str:
    response = OdooMarshaller(allow_none=False).dumps(params)
    return f"""\
<?xml version="1.0"?>
<methodResponse>
{response}
</methodResponse>
"""


# ==========================================================
# RPC Controller
# ==========================================================


class XMLRPC(Controller):
    """Handle RPC connections."""

    def _xmlrpc(self, service):
        """Common method to handle an XML-RPC request."""
        data = request.httprequest.get_data()
        params, method = xmlrpc.client.loads(data, use_datetime=True)
        result = dispatch_rpc(service, method, params)
        return dumps((result,))

    @route(
        "/xmlrpc/<service>",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def xmlrpc_1(self, service):
        """XML-RPC service that returns faultCode as strings.

        This entrypoint is historical and non-compliant, but kept for
        backwards-compatibility.
        """
        warn_endpoint_is_deprecated(logger, __name__)
        detach_database()
        try:
            response = self._xmlrpc(service)
        except Exception as error:
            error.error_response = Response(
                response=xmlrpc_handle_exception_string(error),
                mimetype="text/xml",
            )
            raise
        return Response(response=response, mimetype="text/xml")

    @route(
        "/xmlrpc/2/<service>",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def xmlrpc_2(self, service):
        """XML-RPC service that returns faultCode as int."""
        warn_endpoint_is_deprecated(logger, __name__)
        detach_database()
        try:
            response = self._xmlrpc(service)
        except Exception as error:
            error.error_response = Response(
                response=xmlrpc_handle_exception_int(error),
                mimetype="text/xml",
            )
            raise
        return Response(response=response, mimetype="text/xml")
