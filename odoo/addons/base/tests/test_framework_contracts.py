"""Every framework→addon Protocol must be satisfied by the model it describes.

`odoo/orm/_protocols.py` declares what the core requires of the twelve
addon-owned models it calls two or more members on. Those declarations are worth
exactly as much as the thing that checks them, which is this file.

**Direction matters, and both are needed.** This suite checks
*declared → implemented*: every member `ResUsersProtocol` names exists on
`res.users` with a signature the framework's calls fit. The other direction --
*called → declared* -- is `tooling/architecture/model_member_surface_check.py`,
which reads the core's own call sites and fails when it reaches a member the
Protocol omits. Neither alone is enough: `HttpExtension` had only the first for
as long as it existed, and `http/_serve.py` was calling
`ir.http._apply_max_upload_size`, undeclared and therefore unchecked in both
existence and signature, until the second gate was written.

This is `addons/base`, not `odoo/`, because it needs a registry: a Protocol
describes the *runtime* model, assembled from every installed module's
contribution, and an addon that overrides one of these members with an
incompatible signature is exactly the failure worth catching.
"""

import inspect

from odoo.orm._protocols import FRAMEWORK_MODEL_PROTOCOLS
from odoo.tests import TransactionCase, tagged

_POSITIONAL = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


def _positional_capacity(func, *, drop_self: bool = False) -> tuple[int, float]:
    """``(required, maximum)`` positional arguments *func* accepts.

    ``**kwargs`` and keyword-only parameters are not counted, which is the whole
    subtlety: the first draft of this file compared the protocol's *parameter
    count* against the implementation's *positional capacity*, so
    ``res.lang._get_data(self, **kwargs)`` looked like a one-argument call the
    implementation could not take. It reported a contract violation that was
    entirely an artefact of counting two different things.

    ``drop_self`` is for an unbound protocol function, where ``self`` is still
    in the signature; a bound method has already lost it.
    """
    params = list(inspect.signature(func).parameters.values())
    if drop_self:
        params = params[1:]
    required = 0
    maximum = 0.0
    for param in params:
        if param.kind in _POSITIONAL:
            maximum += 1
            if param.default is inspect.Parameter.empty:
                required += 1
        elif param.kind is inspect.Parameter.VAR_POSITIONAL:
            maximum = float("inf")
    return required, maximum


@tagged("post_install", "-at_install")
class TestFrameworkModelContracts(TransactionCase):
    def test_the_protocol_map_is_populated(self):
        """An empty map would make every assertion below vacuous."""
        self.assertGreaterEqual(
            len(FRAMEWORK_MODEL_PROTOCOLS),
            10,
            "odoo/orm/_protocols.py declares fewer models than expected; the "
            "map may have been emptied rather than narrowed",
        )

    def test_every_declared_model_exists(self):
        for model_name in FRAMEWORK_MODEL_PROTOCOLS:
            with self.subTest(model=model_name):
                self.assertIn(
                    model_name,
                    self.env.registry,
                    f"{model_name} is declared in FRAMEWORK_MODEL_PROTOCOLS but "
                    f"is not in the registry",
                )

    def test_every_declared_member_exists_on_its_model(self):
        for model_name, protocol in FRAMEWORK_MODEL_PROTOCOLS.items():
            model = self.env[model_name]
            for name in self._declared_members(protocol):
                with self.subTest(model=model_name, member=name):
                    self.assertTrue(
                        hasattr(model, name),
                        f"{model_name} is missing {name!r}, which the framework "
                        f"calls and {protocol.__name__} declares",
                    )

    def test_every_declared_method_accepts_the_framework_s_calls(self):
        """A signature the core's call sites do not fit is a runtime TypeError.

        Compared by *positional capacity* rather than by equality: an addon may
        add optional parameters or accept ``*args`` and still satisfy the
        framework. What it may not do is require more than the framework passes,
        or accept fewer.
        """
        for model_name, protocol in FRAMEWORK_MODEL_PROTOCOLS.items():
            model = self.env[model_name]
            for name, proto_func in self._declared_methods(protocol):
                with self.subTest(model=model_name, member=name):
                    impl = getattr(model, name, None)
                    self.assertIsNotNone(impl, f"{model_name}.{name} is missing")
                    if not callable(impl):
                        self.fail(
                            f"{model_name}.{name} is declared as a method by "
                            f"{protocol.__name__} but is {type(impl).__name__} "
                            f"on the model"
                        )

                    wants_least, wants_most = _positional_capacity(
                        proto_func, drop_self=True
                    )
                    takes_least, takes_most = _positional_capacity(impl)
                    self.assertLessEqual(
                        takes_least,
                        wants_least,
                        f"{model_name}.{name} requires {takes_least} positional "
                        f"args but the framework passes as few as {wants_least}",
                    )
                    self.assertGreaterEqual(
                        takes_most,
                        wants_most,
                        f"{model_name}.{name} accepts at most {takes_most} "
                        f"positional args but the framework may pass "
                        f"{wants_most}",
                    )

    def test_declared_attributes_are_fields_not_methods(self):
        """``res.users.company_id`` and friends must stay data, not callables.

        The four attribute declarations are the reason a method-only contract
        would have missed a third of what the framework reads off ``res.users``.
        If one became a method, `Environment.company` would silently hold a
        bound method instead of a recordset.
        """
        for model_name, protocol in FRAMEWORK_MODEL_PROTOCOLS.items():
            model = self.env[model_name]
            for name in self._declared_attributes(protocol):
                with self.subTest(model=model_name, attribute=name):
                    self.assertIn(
                        name,
                        model._fields,
                        f"{protocol.__name__} declares {name!r} as an attribute, "
                        f"so {model_name} must carry a field of that name",
                    )

    # -- what a Protocol declares, split by kind ---------------------------

    @staticmethod
    def _declared_methods(protocol):
        return [
            (name, func)
            for name, func in inspect.getmembers(protocol, inspect.isfunction)
            if not name.startswith("__")
        ]

    @staticmethod
    def _declared_attributes(protocol) -> list[str]:
        return [
            name
            for name in getattr(protocol, "__annotations__", {})
            if not name.startswith("__")
        ]

    @classmethod
    def _declared_members(cls, protocol) -> list[str]:
        return [name for name, _ in cls._declared_methods(protocol)] + list(
            cls._declared_attributes(protocol)
        )
