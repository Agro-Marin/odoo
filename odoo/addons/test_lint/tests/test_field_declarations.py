import ast
import functools
import inspect
from collections import defaultdict
from pathlib import Path

from odoo.modules.registry import Registry
from odoo.orm.models.metaclass import MetaModel
from odoo.tests.common import get_db_name, tagged

from ._checker_field_declaration import bound_names
from .lint_case import LintCase, is_core_path

HOOK_ATTRIBUTES = ("compute", "inverse", "search", "selection", "group_expand")


def auto_label(name: str) -> str:
    return (
        (name[:-4] if name.endswith("_ids") else name.removesuffix("_id"))
        .replace("_", " ")
        .title()
    )


@functools.cache
def _field_lines(path: str) -> dict[tuple[str, str], int]:
    lines: dict[tuple[str, str], int] = {}
    tree = ast.parse(Path(path).read_bytes(), path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            for name in bound_names(statement):
                lines.setdefault((node.name, name), statement.lineno)
    return lines


def _declared_at(cls: type, field_name: str) -> str:
    try:
        path = inspect.getsourcefile(cls) or "?"
    except TypeError:
        return f"?:{cls.__name__}.{field_name}"
    lineno = _field_lines(path).get((cls.__name__, field_name), 0)
    return f"{path}:{lineno} {cls.__name__}.{field_name}"


def redundant_labels(model_cls) -> list[str]:
    definitions: dict[str, list] = defaultdict(list)
    for cls in model_cls._model_classes__:
        if isinstance(cls, MetaModel):
            for field in cls._field_definitions:
                definitions[field.name].append((cls, field))
    found = []
    for name, chain in definitions.items():
        auto = auto_label(name)
        for index, (cls, field) in enumerate(chain):
            args = field._args__
            if args.get("string") != auto or "related" in args:
                continue
            if not is_core_path(inspect.getsourcefile(cls) or ""):
                continue
            if all(
                "related" not in lower._args__
                and lower._args__.get("string") in (None, auto)
                for _, lower in chain[index + 1 :]
            ):
                found.append(f"{_declared_at(cls, name)} string={auto!r}")
    return found


def is_constraint(func) -> bool:
    return callable(func) and hasattr(func, "_constrains")


# Mirrors the predicate in odoo/orm/models/mixins/_constraints.py
# (_constraint_methods), which only logs: keep the two in step.
def is_writeable_by_constraint(field) -> bool:
    return bool(field.store or field.inverse or field.inherited or field.related)


def constrains_finding(model_name, attr_name, name, reason) -> str:
    return f"{model_name}.{attr_name} @api.constrains({name!r}): {reason}"


def constrains_findings(model_name, fields, members, model) -> list[str]:
    found = []
    for attr_name, func in members:
        names = func._constrains
        if callable(names):
            names = names(model.sudo())
        for name in names:
            field = fields.get(name)
            if field is None:
                reason = "not a field name"
            elif not is_writeable_by_constraint(field):
                reason = "not writeable"
            else:
                continue
            found.append(constrains_finding(model_name, attr_name, name, reason))
    return found


@tagged("-at_install", "post_install")
class TestFieldDeclarations(LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = Registry(get_db_name())

    def test_every_hook_a_field_names_is_a_method_of_its_model(self):
        missing = []
        checked = 0
        for model_name, model_cls in self.registry.items():
            for field in model_cls._fields.values():
                for attribute in HOOK_ATTRIBUTES:
                    method = getattr(field, attribute, None)
                    if not isinstance(method, str):
                        continue
                    checked += 1
                    if not callable(getattr(model_cls, method, None)):
                        missing.append(
                            f"{model_name}.{field.name} {attribute}={method!r} "
                            f"({field._module})"
                        )
        self.assertGreater(checked, 100, "the scan reached almost no hooks")
        self.assert_ratchet(
            missing,
            "lint_field_hook_missing",
            "field hook(s) naming a method the model does not have",
            "Nothing checks the name at setup: resolve_mro() finds no method, the "
            "field gets no dependencies, and the first read raises AttributeError. "
            "Define the method, or on a mixin whose hosts supply it, declare the "
            "contract with a method that raises NotImplementedError.",
        )

    def test_every_onchange_names_a_field(self):
        unknown = []
        checked = 0
        for model_name, model_cls in self.registry.items():
            if model_cls._abstract:
                continue
            for attr_name, func in inspect.getmembers(model_cls, callable):
                names = getattr(func, "_onchange", None)
                if not names or callable(names):
                    continue
                checked += 1
                unknown.extend(
                    f"{model_name}.{attr_name} @api.onchange({name!r})"
                    for name in names
                    if name not in model_cls._fields
                )
        self.assertGreater(checked, 20, "the scan reached almost no onchanges")
        self.assert_ratchet(
            unknown,
            "lint_field_trigger_unknown",
            "@api.onchange parameter(s) naming no field",
            "The ORM logs a warning the first time the model's hooks are read and "
            "then never fires the method for that name: the onchange never runs. "
            "Name the field.",
        )

    def test_every_constrains_parameter_is_a_writeable_field(self):
        invalid = []
        checked = 0
        with self.superuser_env() as env:
            for model_name, model_cls in self.registry.items():
                if model_cls._abstract:
                    continue
                members = inspect.getmembers(model_cls, is_constraint)
                checked += len(members)
                invalid.extend(
                    constrains_findings(
                        model_name, model_cls._fields, members, env[model_name]
                    )
                )
        self.assertGreater(checked, 50, "the scan reached almost no constraints")
        self.assert_ratchet(
            invalid,
            "lint_constrains_parameter_invalid",
            "@api.constrains parameter(s) naming no field or a field no write reaches",
            "The ORM logs one warning and registers the method anyway, but "
            "_check_fields runs it only for the written field names it declares: "
            "a dotted path or a missing name never matches, and a non-stored "
            "compute without inverse is never written. Constrain the field on the "
            "model that stores it.",
        )

    def test_constrains_gate_reads_a_planted_fault(self):
        partner = self.registry["res.partner"]
        unwriteable = next(
            name
            for name, field in partner._fields.items()
            if not is_writeable_by_constraint(field)
        )

        def planted(*names):
            def check(self):
                pass

            check._constrains = names
            return check

        dynamic = planted()
        dynamic._constrains = lambda model: ("name", "no_such_field")
        members = [
            ("_check_clean", planted("name")),
            ("_check_dotted", planted("parent_id.name")),
            ("_check_unwriteable", planted(unwriteable)),
            ("_check_dynamic", dynamic),
        ]
        with self.superuser_env() as env:
            found = constrains_findings(
                "res.partner", partner._fields, members, env["res.partner"]
            )
        self.assertEqual(
            sorted(found),
            [
                constrains_finding(
                    "res.partner", "_check_dotted", "parent_id.name", "not a field name"
                ),
                constrains_finding(
                    "res.partner", "_check_dynamic", "no_such_field", "not a field name"
                ),
                constrains_finding(
                    "res.partner", "_check_unwriteable", unwriteable, "not writeable"
                ),
            ],
        )

    def test_no_declaration_restates_the_label_the_field_would_get_anyway(self):
        found = []
        for model_cls in self.registry.values():
            found.extend(redundant_labels(model_cls))
        self.assert_ratchet(
            found,
            "lint_field_string_restates_label",
            "field declaration(s) whose string= is the label Field._setup_attrs__ "
            "derives from the name",
            "Drop the argument: the ORM strips _id/_ids, replaces underscores and "
            "title-cases, so an explicit string= should be there only when it says "
            "something the name does not.",
        )
