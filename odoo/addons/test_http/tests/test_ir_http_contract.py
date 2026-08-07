import inspect

from odoo.http._protocols import HttpExtension
from odoo.tests import TransactionCase, tagged


def _positional_capacity(func) -> tuple[int, float]:
    required = 0
    maximum = 0.0
    for param in inspect.signature(func).parameters.values():
        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            maximum += 1
            if param.default is inspect.Parameter.empty:
                required += 1
        elif param.kind is inspect.Parameter.VAR_POSITIONAL:
            maximum = float("inf")
    return required, maximum


@tagged("post_install", "-at_install")
class TestIrHttpImplementsProtocol(TransactionCase):
    def test_ir_http_satisfies_http_extension_protocol(self):
        ir_http = self.env["ir.http"]
        hooks = [
            (name, func)
            for name, func in inspect.getmembers(HttpExtension, inspect.isfunction)
            if not name.startswith("__")
        ]
        self.assertGreaterEqual(len(hooks), 13, "protocol hooks went missing")
        for name, proto_func in hooks:
            with self.subTest(hook=name):
                impl = getattr(ir_http, name, None)
                self.assertIsNotNone(
                    impl,
                    f"ir.http is missing the {name!r} hook declared by "
                    "odoo.http._protocols.HttpExtension",
                )
                self.assertTrue(callable(impl), f"ir.http.{name} is not callable")

                proto_params = list(inspect.signature(proto_func).parameters.values())[
                    1:
                ]
                n_call_args = len(proto_params)
                n_required_call_args = sum(
                    1 for p in proto_params if p.default is inspect.Parameter.empty
                )
                required, maximum = _positional_capacity(impl)
                self.assertLessEqual(
                    required,
                    n_required_call_args,
                    f"ir.http.{name} requires {required} positional args but the "
                    f"http package passes as few as {n_required_call_args}",
                )
                self.assertGreaterEqual(
                    maximum,
                    n_call_args,
                    f"ir.http.{name} accepts at most {maximum} positional args "
                    f"but the http package may pass {n_call_args}",
                )
