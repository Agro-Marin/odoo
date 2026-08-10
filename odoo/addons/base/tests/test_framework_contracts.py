import annotationlib
import inspect

from odoo.orm._protocols import FRAMEWORK_MODEL_PROTOCOLS
from odoo.tests import TransactionCase, tagged

_POSITIONAL = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


def _positional_capacity(func, *, drop_self: bool = False) -> tuple[int, float]:
    params = list(
        inspect.signature(
            func, annotation_format=annotationlib.Format.FORWARDREF
        ).parameters.values()
    )
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
