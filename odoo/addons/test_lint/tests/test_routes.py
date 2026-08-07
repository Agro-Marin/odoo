import logging
from pprint import pformat
from unittest.mock import patch

from odoo import http
from odoo.http import routing as http_routing
from odoo.tests.common import TransactionCase, no_retry, tagged

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
@no_retry
class RoutesLinter(TransactionCase):
    def test_routes_definition(self):
        _check_and_complete_route_definition = http._check_and_complete_route_definition
        checked = 0

        def extended_check(controller_cls, submethod, merged_routing):
            nonlocal checked
            checked += 1
            if "type" in merged_routing:
                useless_overrides = {
                    key: value
                    for key, value in submethod.original_routing.items()
                    if key not in ("routes", "type")
                    if merged_routing.get(key) == value
                }
                if useless_overrides:
                    _logger.warning(
                        "The endpoint %s is duplicating the existing routing configuration : %s",
                        f"{controller_cls.__module__}.{controller_cls.__name__}.{submethod.__name__}",
                        pformat(useless_overrides),
                    )

            return _check_and_complete_route_definition(
                controller_cls, submethod, merged_routing
            )

        installed_modules = set(
            self.env["ir.module.module"]
            .search(
                [
                    ("state", "=", "installed"),
                ]
            )
            .mapped("name")
        )
        with patch(
            "odoo.http.routing._check_and_complete_route_definition", extended_check
        ):
            for _ in http._generate_routing_rules(installed_modules, nodb_only=False):
                pass
        self.assertGreater(checked, 0, "route-linter hook was never invoked")

    def test_reexported_hook_is_the_routing_one(self):
        self.assertIs(
            http._check_and_complete_route_definition,
            http_routing._check_and_complete_route_definition,
        )
