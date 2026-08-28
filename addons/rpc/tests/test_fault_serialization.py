"""Tests for the XML-RPC exception-to-fault serialization contract."""

import xmlrpc.client

from markupsafe import Markup

from odoo import exceptions
from odoo.tests import TransactionCase, tagged

from odoo.addons.base.models.res_lang import LangData
from odoo.addons.rpc.controllers.xmlrpc import (
    RPC_FAULT_CODE_ACCESS_DENIED,
    RPC_FAULT_CODE_ACCESS_ERROR,
    RPC_FAULT_CODE_APPLICATION_ERROR,
    RPC_FAULT_CODE_WARNING,
    dumps,
    xmlrpc_handle_exception_int,
    xmlrpc_handle_exception_string,
)


@tagged("post_install", "-at_install")
class TestFaultSerialization(TransactionCase):
    def _fault_from(self, payload):
        """Unmarshal a serialized fault and return the Fault exception."""
        with self.assertRaises(xmlrpc.client.Fault) as capture:
            xmlrpc.client.loads(payload)
        return capture.exception

    def test_int_fault_codes_per_exception_type(self):
        """Each Odoo exception maps to its documented integer fault code."""
        cases = [
            (exceptions.AccessError("no access"), RPC_FAULT_CODE_ACCESS_ERROR),
            (exceptions.AccessDenied(), RPC_FAULT_CODE_ACCESS_DENIED),
            (exceptions.UserError("user oops"), RPC_FAULT_CODE_WARNING),
            (
                exceptions.RedirectWarning("redirect", 1, "Go"),
                RPC_FAULT_CODE_WARNING,
            ),
        ]
        for exception, expected_code in cases:
            fault = self._fault_from(xmlrpc_handle_exception_int(exception))
            self.assertEqual(fault.faultCode, expected_code)

    def test_int_fault_generic_exception_carries_traceback(self):
        """Unknown exceptions map to APPLICATION_ERROR with the traceback."""
        try:
            raise ValueError("boom in rpc")
        except ValueError as error:
            fault = self._fault_from(xmlrpc_handle_exception_int(error))
        self.assertEqual(fault.faultCode, RPC_FAULT_CODE_APPLICATION_ERROR)
        self.assertIn("boom in rpc", fault.faultString)

    def test_string_fault_access_denied_is_bare(self):
        """The legacy string protocol keeps AccessDenied terse."""
        fault = self._fault_from(
            xmlrpc_handle_exception_string(exceptions.AccessDenied())
        )
        self.assertEqual(fault.faultCode, "AccessDenied")

    def test_string_fault_user_error_is_prefixed(self):
        """The legacy string protocol prefixes warnings with their type."""
        fault = self._fault_from(
            xmlrpc_handle_exception_string(exceptions.UserError("user oops"))
        )
        self.assertTrue(str(fault.faultCode).startswith("warning -- UserError"))
        self.assertIn("user oops", str(fault.faultCode))


@tagged("post_install", "-at_install")
class TestFaultCarriesItsOwnException(TransactionCase):
    """The handlers take the exception; they must not read ambient state.

    Both read `sys.exc_info()` for the generic branch, which is whatever the
    *caller's* `except` block is handling rather than the argument. Inside the
    two controllers those coincide, so the bug was invisible there and showed
    up the moment the mapping was called anywhere else: outside an `except`,
    `sys.exc_info()` is `(None, None, None)` and `traceback.format_exception`
    renders the string "NoneType: None" into the fault, losing the error
    entirely.
    """

    def _fault_from(self, payload):
        with self.assertRaises(xmlrpc.client.Fault) as capture:
            xmlrpc.client.loads(payload)
        return capture.exception

    def test_a_never_raised_exception_still_names_itself(self):
        for handler in (xmlrpc_handle_exception_int, xmlrpc_handle_exception_string):
            with self.subTest(handler=handler.__name__):
                fault = self._fault_from(handler(ValueError("boom, unraised")))
                rendered = f"{fault.faultCode}{fault.faultString}"
                self.assertIn("boom, unraised", rendered)
                self.assertNotIn("NoneType: None", rendered)

    def test_the_exception_passed_wins_over_the_one_in_flight(self):
        """A handler called while another exception is being handled must
        serialize its argument, not the one `sys.exc_info()` happens to hold."""
        try:
            raise KeyError("the ambient one")
        except KeyError:
            fault = self._fault_from(
                xmlrpc_handle_exception_int(ValueError("the argument"))
            )
        self.assertIn("the argument", fault.faultString)
        self.assertNotIn("the ambient one", fault.faultString)

    def test_a_raised_exception_still_carries_its_stack(self):
        try:
            raise ValueError("raised for real")
        except ValueError as error:
            fault = self._fault_from(xmlrpc_handle_exception_int(error))
        self.assertIn("raised for real", fault.faultString)
        self.assertIn("Traceback (most recent call last)", fault.faultString)


@tagged("post_install", "-at_install")
class TestMarkupMarshalling(TransactionCase):
    """`Markup` must reach the marshaller as a plain `str`.

    `OdooMarshaller.dispatch[Markup]` converts before dumping, which reads like
    a redundant cast over a `str` subclass and is not: `Markup.replace` escapes
    its replacement, so `xmlrpc.client.escape` -- three `str.replace` calls --
    turns "&" into "&amp;amp;" when handed one. Marshalling a Markup as itself
    double-escapes every rendered HTML field on the wire.
    """

    def test_markup_is_escaped_exactly_once(self):
        payload = dumps((Markup("<b>a &amp; b</b>"),))
        (value,), _method = xmlrpc.client.loads(payload)
        self.assertEqual(value, "<b>a &amp; b</b>")

    def test_the_dispatch_override_keeps_the_interpreter_fallbacks(self):
        """Widening the lookup for one hierarchy must not cost the others.

        `__missing__` intercepts every dispatch miss, so the two fallbacks
        `xmlrpc.client` relies on have to survive it: marshalling an arbitrary
        instance through its `_arbitrary_instance` handler, and refusing a
        `ReadonlyDict` that stock `Marshaller` renders as an EMPTY struct
        because its `__slots__` leave nothing in `__dict__` to read.
        """

        class Arbitrary:
            def __init__(self):
                self.a = 1

        self.assertIn("struct", dumps((Arbitrary(),)))
        payload = dumps((LangData({"id": 1, "code": "en_US"}),))
        (value,), _method = xmlrpc.client.loads(payload)
        self.assertEqual(value["code"], "en_US")
        with self.assertRaises(TypeError):
            xmlrpc.client.Marshaller(allow_none=False).dumps(
                (LangData({"id": 1, "code": "en_US"}),)
            )

    def test_the_conversion_is_what_makes_it_so(self):
        """Pin the premise: dumping the Markup unconverted really does break."""
        self.assertNotEqual(
            xmlrpc.client.escape(Markup("a & b")),
            xmlrpc.client.escape("a & b"),
        )
