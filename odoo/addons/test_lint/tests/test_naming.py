import inspect

from odoo.modules.registry import Registry
from odoo.tests.common import get_db_name, tagged

from .lint_case import LintCase

INVALID_NAMES = frozenset({"ids", "context"})


@tagged("-at_install", "post_install")
class TestNaming(LintCase):
    def test_parameter_rpc_compatible(self):
        # `ids` and `context` are consumed by the RPC layer before the method
        # is ever called, so a public method taking either never receives what
        # its caller passed.
        #
        # Deduplicated on the resolved function object, not on the class that
        # introduced the method. The rule protects the *effective* method --
        # the one RPC dispatches to -- so an override that adds `ids` to a
        # clean base has to be caught, which keying on the original definition
        # cannot do. Identity works because `getattr(cls, name)` hands back the
        # same plain function for every model sharing it: 9 815 (model, method)
        # pairs collapse to ~1 800 distinct functions, and the pairs were
        # re-signaturing the same object up to 500 times over.
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
                # `__func__` for a classmethod: `getattr` builds a fresh bound
                # object on every access, so the bound form is never identical
                # twice and would defeat the dedup entirely.
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
                    # A builtin or C-level callable with no introspectable
                    # signature carries no Python parameter names to offend.
                    continue
                if bad := INVALID_NAMES.intersection(signature.parameters):
                    offenders.append(
                        f"{model_name}.{method_name}: {', '.join(sorted(bad))}"
                    )

        self.assertGreater(checked, 100, "the scan reached almost no public methods")
        self.assert_ratchet(
            offenders,
            0,
            "public method(s) taking an RPC-reserved parameter name",
            "Rename it: `ids` and `context` are consumed by the RPC layer "
            "before the method ever sees them.",
        )
