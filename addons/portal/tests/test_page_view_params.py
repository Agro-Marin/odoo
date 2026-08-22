import inspect

from odoo.tests import TransactionCase, tagged

from odoo.addons.portal.controllers.portal import CustomerPortal

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
        params = inspect.signature(CustomerPortal._get_page_view_values).parameters
        self.assertTrue(
            any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()),
            "_get_page_view_values must keep its **kwargs catch-all",
        )
