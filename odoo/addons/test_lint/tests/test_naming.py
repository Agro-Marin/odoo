import inspect

from odoo.modules.registry import Registry
from odoo.tests.common import get_db_name, tagged

from .lint_case import LintCase

INVALID_NAMES = frozenset({"ids", "context"})


@tagged("-at_install", "post_install")
class TestNaming(LintCase):
    def test_parameter_rpc_compatible(self):
        offenders = []
        seen = set()
        checked = 0

        registry = Registry(get_db_name())
        for model_name, model_cls in registry.items():
            for method_name, method in inspect.getmembers(model_cls, inspect.isroutine):
                if method_name.startswith("_") or getattr(
                    method, "_api_private", False
                ):
                    continue
                key = getattr(method, "__func__", method)
                if key in seen:
                    continue
                seen.add(key)
                checked += 1

                try:
                    signature = inspect.signature(
                        method,
                        annotation_format=inspect.Format.STRING,
                    )
                except ValueError, TypeError:
                    continue
                if bad := INVALID_NAMES.intersection(signature.parameters):
                    offenders.append(
                        f"{model_name}.{method_name}: {', '.join(sorted(bad))}"
                    )

        self.assertGreater(checked, 100, "the scan reached almost no public methods")
        self.assert_ratchet(
            offenders,
            "lint_rpc_reserved_parameter",
            "public method(s) taking an RPC-reserved parameter name",
            "Rename it: `ids` and `context` are consumed by the RPC layer "
            "before the method ever sees them.",
        )
