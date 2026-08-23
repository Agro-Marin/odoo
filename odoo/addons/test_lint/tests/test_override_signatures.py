import annotationlib
import inspect
import typing

from odoo.modules.registry import Registry
from odoo.tests.common import get_db_name, tagged

from .lint_case import LintCase, get_odoo_module_name

POSITIONAL_ONLY = inspect.Parameter.POSITIONAL_ONLY
POSITIONAL_OR_KEYWORD = inspect.Parameter.POSITIONAL_OR_KEYWORD
VAR_POSITIONAL = inspect.Parameter.VAR_POSITIONAL
KEYWORD_ONLY = inspect.Parameter.KEYWORD_ONLY
VAR_KEYWORD = inspect.Parameter.VAR_KEYWORD
EMPTY = inspect.Parameter.empty


def _stringify_annotation(ann: object) -> str:
    if ann is EMPTY:
        return ""
    if isinstance(ann, typing.ForwardRef):
        return ann.__forward_arg__
    if isinstance(ann, str):
        return ann
    origin = getattr(ann, "__origin__", None)
    if origin is not None:
        args = getattr(ann, "__args__", ())
        origin_name = (
            getattr(origin, "__qualname__", None)
            or getattr(origin, "_name", None)
            or repr(origin)
        )
        return f"{origin_name}[{', '.join(_stringify_annotation(a) for a in args)}]"
    if isinstance(ann, type):
        return ann.__qualname__
    return repr(ann)


failure_message = """\
Invalid override in {model} of {method}, {message}.

Original definition in {parent_module}:{original_decorators}
    def {method}{original_signature}

Incompatible override definition in {child_module}:{override_decorators}
    def {method}{override_signature}"""


MODULES_TO_IGNORE = {
    "pos_blackbox_be",
}
METHODS_TO_IGNORE = {
    "action_timer_stop",
}
MODEL_METHODS_TO_IGNORE = {
    (
        "account.intrastat.services.be.report.handler",
        "_be_intrastat_get_xml_file_content",
    ),
    ("hr.payslip", "action_payslip_payment_report"),
    ("hr.payslip.run", "action_payment_report"),
    ("ir.config_parameter", "init"),
    ("mrp.production", "action_generate_serial"),
    ("mrp.production", "set_qty_producing"),
    ("mrp.workorder", "button_start"),
    ("quality.check", "add_check_in_chain"),
    ("propose.change", "_do_remove_step"),
    ("propose.change", "_do_set_picture"),
    ("propose.change", "_do_update_step"),
    ("report.pos_hr.single_employee_sales_report", "_get_domain"),
    ("report.pos_hr.single_employee_sales_report", "get_sale_details"),
    ("sign.request", "_generate_completed_document"),
}


def check_parameter(
    pparam: inspect.Parameter,
    cparam: inspect.Parameter,
    is_private: bool = False,
) -> bool:
    return (
        (pparam.name == cparam.name or pparam.kind == POSITIONAL_ONLY or is_private)
        and (pparam.default is EMPTY or pparam.default == cparam.default)
        and (
            (pann := pparam.annotation) is EMPTY
            or (cann := cparam.annotation) is EMPTY
            or pann == cann
            or pann.__class__ != cann.__class__
            or _stringify_annotation(pann) == _stringify_annotation(cann)
        )
    )


def assert_valid_override(parent_signature, child_signature, is_private):
    pparams = parent_signature.parameters
    cparams = child_signature.parameters

    if pparams == cparams:
        return

    parent_has_varargs = any(pp.kind == VAR_POSITIONAL for pp in pparams.values())
    parent_has_varkwargs = any(pp.kind == VAR_KEYWORD for pp in pparams.values())

    child_has_varargs = any(cp.kind == VAR_POSITIONAL for cp in cparams.values())
    child_has_varkwargs = any(cp.kind == VAR_KEYWORD for cp in cparams.values())

    pos_kinds = (POSITIONAL_ONLY, POSITIONAL_OR_KEYWORD)
    pposparams = [pp for pp in pparams.values() if pp.kind in pos_kinds]
    cposparams = [cp for cp in cparams.values() if cp.kind in pos_kinds]
    if len(cposparams) < len(pposparams):
        assert child_has_varargs, "missing positional parameters"
        pposparams = pposparams[: len(cposparams)]
    elif len(cposparams) > len(pposparams):
        assert parent_has_varargs, "too many positional parameters"
        cposparams = cposparams[: len(pposparams)]
    for pparam, cparam in zip(pposparams, cposparams, strict=True):
        assert check_parameter(pparam, cparam, is_private=is_private), (
            f"wrong positional parameter {cparam.name!r}"
        )

    kw_kinds = (KEYWORD_ONLY,) if is_private else (POSITIONAL_OR_KEYWORD, KEYWORD_ONLY)
    pkwparams = {pp_name: pp for pp_name, pp in pparams.items() if pp.kind in kw_kinds}
    ckwparams = {cp_name: cp for cp_name, cp in cparams.items() if cp.kind in kw_kinds}
    for name, pparam in pkwparams.items():
        cparam = ckwparams.get(name)
        if cparam is None:
            assert child_has_varkwargs, f"missing keyword parameter {name!r}"
        else:
            assert check_parameter(pparam, cparam, is_private=is_private), (
                f"wrong keyword parameter {name!r}"
            )
    if not parent_has_varkwargs:
        for name in ckwparams.keys() - pkwparams.keys():
            assert ckwparams[name].default is not EMPTY, "too many keyword parameters"


def assert_attribute_override(parent_method, child_method, is_private):
    if is_private:
        attributes = ("_autovacuum",)
    else:
        attributes = ("_autovacuum", "_api_model")
    for attribute in attributes:
        parent_attr = getattr(parent_method, attribute, None)
        child_attr = getattr(child_method, attribute, None)
        assert parent_attr == child_attr, f"attribute {attribute!r} does not match"
    assert not getattr(parent_method, "__final__", False), "parent method is final"
    assert bool(getattr(parent_method, "__deprecated__", False)) == bool(
        getattr(child_method, "__deprecated__", False)
    ), "parent and child method should either both be deprecated or none of them"


def get_decorators(method):
    if (
        not method.__name__.startswith("_")
        and hasattr(method, "_api_model")
        and method._api_model
    ):
        return "\n    @api.model"
    return ""


@tagged("-at_install", "post_install")
class TestLintOverrideSignatures(LintCase):
    def test_lint_override_signature(self):
        self.failureException = TypeError
        registry = Registry(get_db_name())

        for model_name, model_cls in registry.items():
            if model_cls._module in MODULES_TO_IGNORE:
                continue
            for method_name, _ in inspect.getmembers(model_cls, inspect.isroutine):
                if (
                    method_name.startswith("__")
                    or method_name in METHODS_TO_IGNORE
                    or (model_name, method_name) in MODEL_METHODS_TO_IGNORE
                ):
                    continue

                reverse_mro = reversed(model_cls.mro()[1:-1])
                for parent_class in reverse_mro:
                    method = getattr(parent_class, method_name, None)
                    if callable(method):
                        break
                else:
                    continue

                parent_module = get_odoo_module_name(parent_class.__module__)
                _annfmt = annotationlib.Format.FORWARDREF
                original_signature = inspect.signature(
                    method, annotation_format=_annfmt
                )
                original_decorators = get_decorators(method)
                is_private = method_name.startswith("_")

                for child_class in reverse_mro:
                    if method_name not in child_class.__dict__:
                        continue
                    override = getattr(child_class, method_name)

                    child_module = get_odoo_module_name(child_class.__module__)
                    override_signature = inspect.signature(
                        override, annotation_format=_annfmt
                    )
                    override_decorators = get_decorators(override)

                    with self.subTest(
                        module=child_module,
                        model=model_name,
                        method=method_name,
                    ):
                        try:
                            assert_valid_override(
                                original_signature,
                                override_signature,
                                is_private=is_private,
                            )
                            assert override_decorators == original_decorators, (
                                "decorators does not match"
                            )
                            assert_attribute_override(
                                method, override, is_private=is_private
                            )
                        except AssertionError as exc:
                            msg = failure_message.format(
                                message=exc.args[0],
                                model=model_name,
                                method=method_name,
                                child_module=child_module,
                                parent_module=parent_module,
                                original_signature=original_signature,
                                override_signature=override_signature,
                                original_decorators=original_decorators,
                                override_decorators=override_decorators,
                            )
                            raise TypeError(msg) from None
