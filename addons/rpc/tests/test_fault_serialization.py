"""Tests for the XML-RPC exception-to-fault serialization contract."""

import xmlrpc.client

from odoo import exceptions
from odoo.tests import TransactionCase, tagged

from odoo.addons.rpc.controllers.xmlrpc import (
    RPC_FAULT_CODE_ACCESS_DENIED,
    RPC_FAULT_CODE_ACCESS_ERROR,
    RPC_FAULT_CODE_APPLICATION_ERROR,
    RPC_FAULT_CODE_WARNING,
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
