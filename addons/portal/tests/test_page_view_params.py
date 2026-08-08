"""A query param must never collide with a portal page-view argument.

Every portal document route ends in
``CustomerPortal._get_page_view_values(document, access_token, values,
session_history, no_breadcrumbs, **kwargs)``, reached through a per-module
wrapper, with the route's leftover query string splatted in as ``**kwargs``::

    # account
    values = self._invoice_get_page_view_values(invoice_sudo, access_token, **kw)
      -> self._get_page_view_values(invoice, access_token, values,
                                    "my_invoices_history", False, **kwargs)

So ``/my/invoices/42?values=x`` supplied a second value for an argument the
caller already passes positionally: ``TypeError: ... got multiple values for
argument 'values'`` -- an HTTP 500 on routes declared ``auth="public"``.
Confirmed for ``document``, ``values``, ``session_history``, ``no_breadcrumbs``
and, in the account wrapper, ``invoice``.

The fix is structural rather than a filter: these parameters are declared
positional-only (PEP 570), so a same-named query param lands harmlessly in
``kwargs`` -- which is where unrecognised client keys already go. The test below
pins that property to the signature, because it is the signature (not any call
site) that carries the guarantee.
"""

import inspect

from odoo.tests import TransactionCase, tagged

from odoo.addons.portal.controllers.portal import CustomerPortal

#: Arguments the callers supply positionally; a client must not be able to
#: rebind any of them by name.
POSITIONAL_ONLY_PAGE_VIEW_ARGS = (
    "document",
    "access_token",
    "values",
    "session_history",
    "no_breadcrumbs",
)


@tagged("-at_install", "post_install")
class TestPageViewParams(TransactionCase):
    def test_page_view_args_are_positional_only(self):
        """Guard the PEP 570 marker against a well-meaning signature cleanup."""
        params = inspect.signature(CustomerPortal._get_page_view_values).parameters
        for name in POSITIONAL_ONLY_PAGE_VIEW_ARGS:
            self.assertIn(name, params, f"{name} disappeared from the signature")
            self.assertEqual(
                params[name].kind,
                inspect.Parameter.POSITIONAL_ONLY,
                f"{name!r} must stay positional-only: otherwise a query string "
                f"'?{name}=x' on any portal document page becomes a duplicate "
                f"argument and answers HTTP 500",
            )

    def test_page_view_still_accepts_arbitrary_extra_kwargs(self):
        """The extension point survives: unknown client keys are still accepted.

        ``**kwargs`` is how ``error``/``warning``/``success``/``pid``/``hash``
        reach the payment and chatter templates, so it must keep swallowing
        names the method does not know -- including the ones that used to clash.
        """
        params = inspect.signature(CustomerPortal._get_page_view_values).parameters
        self.assertTrue(
            any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()),
            "_get_page_view_values must keep its **kwargs catch-all",
        )
