"""Enforce the ``HttpExtension`` protocol against the real ``ir.http`` model.

:class:`odoo.http._protocols.HttpExtension` documents every ``env["ir.http"]``
hook the http package calls. No type checker runs on this fork, so without this
test the protocol was a hand-maintained comment: renaming a hook on either side
(or changing its arity) would only surface as a runtime error mid-request. Here
we assert, for each protocol method, that ``ir.http``:

* exposes a callable of that name, and
* can be *called the way the http package calls it* — every protocol
  parameter passed positionally must bind (implementations may add extra
  optional parameters; they may not require more, or accept fewer).
"""

import inspect

from odoo.http._protocols import HttpExtension
from odoo.tests import TransactionCase, tagged


def _positional_capacity(func) -> tuple[int, float]:
    """Return ``(required, maximum)`` positional-argument counts of ``func``,
    excluding the bound ``self``/``cls`` (``func`` must be a bound method)."""
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
            # typing.Protocol injects dunders (__init__, __subclasshook__, …);
            # only the protocol's own declared hooks form the contract.
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

                # The http package calls hooks positionally: the protocol's
                # parameter count (minus ``self``) is the call shape.
                proto_params = list(inspect.signature(proto_func).parameters.values())[
                    1:
                ]  # drop ``self``
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
