import logging
import typing
from collections import defaultdict
from types import MappingProxyType

from odoo.db import schema as sql
from odoo.exceptions import ValidationError
from odoo.tools import LastOrderedSet, OrderedSet, discardattr, frozendict
from odoo.tools.translate import FIELD_TRANSLATE, _

from . import (
    fields,
    models,
)
from .helpers import ORM_CLASS_MEMOS
from .primitives import LOG_ACCESS_COLUMNS
from .validation import check_pg_name, is_manual_name

if typing.TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.fields import Field
    from odoo.models import BaseModel
    from odoo.orm.runtime import Registry

_logger = logging.getLogger("odoo.registry")


def is_model_definition(cls: type) -> bool:
    return isinstance(cls, models.MetaModel) and getattr(cls, "pool", None) is None


def is_model_class(cls: type) -> bool:
    return getattr(cls, "pool", None) is not None


def add_to_registry(registry: Registry, model_def: type[BaseModel]) -> type[BaseModel]:
    if not is_model_definition(model_def):
        raise TypeError(f"{model_def!r} is not a model definition class")

    if hasattr(model_def, "_constraints"):
        _logger.warning(
            "Model attribute '_constraints' is no longer supported, "
            "please use @api.constrains on methods instead."
        )
    if hasattr(model_def, "_sql_constraints"):
        _logger.warning(
            "Model attribute '_sql_constraints' is no longer supported, "
            "please define models.Constraint on the model."
        )

    name = model_def._name
    parent_names = list(model_def._inherit)
    if name != "base":
        parent_names.append("base")

    if name in parent_names:
        if name not in registry:
            raise TypeError(f"Model {name!r} does not exist in registry.")
        model_cls = registry[name]
        _check_model_extension(model_cls, model_def)
    else:
        if name in registry:
            _logger.warning(
                "Model %r defined in module %r replaces the existing definition "
                "(same _name without _inherit). Did you mean to inherit it?",
                name,
                model_def._module,
            )
        model_cls = type(
            name,
            (model_def,),
            {
                "pool": registry,
                "_name": name,
                "_register": False,
                "_original_module": model_def._module,
                "_inherit_module": {},
                "_inherit_children": OrderedSet(),
                "_inherits_children": set(),
                "_fields__": {},
                "_table_objects": frozendict(),
            },
        )
        model_cls._fields = MappingProxyType(model_cls._fields__)

    bases = LastOrderedSet([model_def])
    for parent_name in parent_names:
        if parent_name not in registry:
            raise TypeError(
                f"Model {name!r} inherits from non-existing model {parent_name!r}."
            )
        parent_cls = registry[parent_name]
        if parent_name == name:
            for base in parent_cls._base_classes__:
                bases.add(base)
        else:
            _check_model_parent_extension(model_cls, model_def, parent_cls)
            bases.add(parent_cls)
            model_cls._inherit_module[parent_name] = model_def._module
            parent_cls._inherit_children.add(name)

    model_cls._base_classes__ = tuple(bases)

    _init_model_class_attributes(model_cls)

    check_pg_name(model_cls._table)

    if model_cls._transient and not model_cls._log_access:
        msg = (
            "TransientModels must have log_access turned on, "
            "in order to implement their vacuum policy"
        )
        raise TypeError(msg)

    registry[name] = model_cls

    for model_name in registry.descendants([name], "_inherit", "_inherits"):
        registry[model_name]._setup_done__ = False

    return model_cls


def _check_model_extension(model_cls: type[BaseModel], model_def: type[BaseModel]):
    if model_cls._abstract and not model_def._abstract:
        raise TypeError(
            f"{model_def} transforms the abstract model {model_cls._name!r} into a non-abstract model. "
            "That class should either inherit from AbstractModel, or set a different '_name'."
        )
    if model_cls._transient != model_def._transient:
        if model_cls._transient:
            raise TypeError(
                f"{model_def} transforms the transient model {model_cls._name!r} into a non-transient model. "
                "That class should either inherit from TransientModel, or set a different '_name'."
            )
        raise TypeError(
            f"{model_def} transforms the model {model_cls._name!r} into a transient model. "
            "That class should either inherit from Model, or set a different '_name'."
        )


def _check_model_parent_extension(
    model_cls: type[BaseModel],
    model_def: type[BaseModel],
    parent_cls: type[BaseModel],
):
    if model_cls._abstract and not parent_cls._abstract:
        raise TypeError(
            f"In {model_def}, abstract model {model_cls._name!r} cannot inherit from non-abstract model {parent_cls._name!r}."
        )


def _init_model_class_attributes(model_cls: type[BaseModel]):
    if not is_model_class(model_cls):
        raise TypeError(f"{model_cls!r} is not a registry model class")

    if model_cls.__dict__.get("_init_attrs_in_progress__", False):
        raise TypeError(f"Circular _inherit chain involving model {model_cls._name!r}")
    model_cls._init_attrs_in_progress__ = True
    try:
        _init_model_class_attributes_once(model_cls)
    finally:
        del model_cls._init_attrs_in_progress__


def _init_model_class_attributes_once(model_cls: type[BaseModel]):
    model_cls._description = model_cls._name
    model_cls._table = model_cls._name.replace(".", "_")
    model_cls._log_access = model_cls._auto
    inherits = {}
    depends = {}

    for base in reversed(model_cls._base_classes__):
        if is_model_definition(base):
            if model_cls._name not in base._inherit and not base._description:
                _logger.warning("The model %s has no _description", model_cls._name)
            model_cls._description = base._description or model_cls._description
            model_cls._table = base._table or model_cls._table
            model_cls._log_access = getattr(base, "_log_access", model_cls._log_access)

        inherits.update(base._inherits)

        for mname, fnames in base._depends.items():
            depends.setdefault(mname, []).extend(fnames)

    if inherits:
        model_cls._inherits = frozendict(inherits)
    if depends:
        model_cls._depends = depends

    registry = model_cls.pool
    for parent_name in model_cls._inherits:
        registry[parent_name]._inherits_children.add(model_cls._name)

    for child_name in model_cls._inherit_children:
        _init_model_class_attributes(registry[child_name])


def setup_model_classes(env: Environment):
    registry = env.registry

    _prepare_setup(registry["ir.model"])

    if registry._init_modules:
        _add_manual_models(env)

    models_classes = list(registry.values())
    for model_cls in models_classes:
        _prepare_setup(model_cls)

    for model_cls in models_classes:
        _setup(model_cls, env)

    for model_cls in models_classes:
        _setup_fields(model_cls, env)

    for model_cls in models_classes:
        model_cls(env, (), ())._post_model_setup__()


def _prepare_setup(model_cls: type[BaseModel]):
    if model_cls._setup_done__:
        if model_cls.__bases__ != model_cls._base_classes__:
            raise TypeError(
                f"Model {model_cls._name!r}: __bases__ diverged from "
                f"_base_classes__ after setup"
            )
        return

    if model_cls.__bases__ != model_cls._base_classes__:
        model_cls.__bases__ = model_cls._base_classes__

    for attr in ("_rec_name", "_active_name"):
        discardattr(model_cls, attr)

    for _memo in ORM_CLASS_MEMOS:
        discardattr(model_cls, _memo)


def _setup(model_cls: type[BaseModel], env: Environment):
    if model_cls._setup_done__:
        return

    if model_cls.__dict__.get("_setup_in_progress__", False):
        raise TypeError(f"Circular _inherits chain involving model {model_cls._name!r}")
    model_cls._setup_in_progress__ = True
    try:
        _setup_phases(model_cls, env)
    finally:
        del model_cls._setup_in_progress__


def _setup_phases(model_cls: type[BaseModel], env: Environment) -> None:
    model_cls._model_classes__ = tuple(
        c for c in model_cls.mro() if getattr(c, "pool", None) is None
    )

    _collect_and_install_fields(model_cls, env)

    if model_cls.pool._init_modules:
        _add_manual_fields(model_cls, env)

    _check_inherits(model_cls)
    for parent_name in model_cls._inherits:
        _setup(model_cls.pool[parent_name], env)
    _add_inherited_fields(model_cls)

    model_cls._setup_done__ = True
    for field in model_cls._fields.values():
        field.prepare_setup()

    _validate_rec_name(model_cls)
    _validate_active_name(model_cls)

    _build_table_objects(model_cls)


def _collect_and_install_fields(model_cls: type[BaseModel], env: Environment):
    for name in model_cls._fields:
        discardattr(model_cls, name)
    model_cls._fields__.clear()

    definitions = defaultdict(list)
    for cls in reversed(model_cls._model_classes__):
        if isinstance(cls, models.MetaModel):
            for field in cls._field_definitions:
                definitions[field.name].append(field)

    for name, fields_ in definitions.items():
        _patch_translate_field(model_cls, name, fields_)
        _patch_company_dependent_field(model_cls, env, name, fields_)

        if (
            len(fields_) == 1
            and fields_[0]._direct
            and fields_[0].model_name == model_cls._name
        ):
            model_cls._fields__[name] = fields_[0]
        else:
            Field = type(fields_[-1])
            add_field(model_cls, name, Field(_base_fields__=tuple(fields_)))


def _patch_translate_field(model_cls: type[BaseModel], name: str, fields_: list):
    key = f"{model_cls._name}.{name}"
    if key not in model_cls.pool._database_translated_fields:
        return

    translate = next(
        (
            field._args__["translate"]
            for field in reversed(fields_)
            if "translate" in field._args__
        ),
        False,
    )
    if not translate:
        field_translate = FIELD_TRANSLATE.get(
            model_cls.pool._database_translated_fields[key],
            True,
        )
        _logger.debug("Patching %s.%s with translate=True", model_cls._name, name)
        fields_.append(type(fields_[0])(translate=field_translate))


def _patch_company_dependent_field(
    model_cls: type[BaseModel], env: Environment, name: str, fields_: list
):
    key = f"{model_cls._name}.{name}"
    if key not in model_cls.pool._database_company_dependent_fields:
        return

    company_dependent = next(
        (
            field._args__["company_dependent"]
            for field in reversed(fields_)
            if "company_dependent" in field._args__
        ),
        False,
    )
    if not company_dependent:
        col = sql.table_columns(env.cr, model_cls._table).get(name)
        if col and col["udt_name"] == "jsonb":
            _logger.debug(
                "Patching %s.%s with company_dependent=True",
                model_cls._name,
                name,
            )
            fields_.append(type(fields_[0])(company_dependent=True))


def _validate_rec_name(model_cls: type[BaseModel]):
    if model_cls._rec_name:
        if model_cls._rec_name not in model_cls._fields:
            raise TypeError(
                f"Invalid _rec_name={model_cls._rec_name!r} "
                f"for model {model_cls._name!r}"
            )
    elif "name" in model_cls._fields:
        model_cls._rec_name = "name"
    elif model_cls._custom and "x_name" in model_cls._fields:
        model_cls._rec_name = "x_name"


def _validate_active_name(model_cls: type[BaseModel]):
    if model_cls._active_name:
        if (
            model_cls._active_name not in model_cls._fields
            or model_cls._active_name not in ("active", "x_active")
        ):
            raise TypeError(
                f"Invalid _active_name={model_cls._active_name!r} for model "
                f"{model_cls._name!r}; only 'active' and 'x_active' are supported "
                f"and the field must be present on the model"
            )
    elif "active" in model_cls._fields:
        model_cls._active_name = "active"
    elif "x_active" in model_cls._fields:
        model_cls._active_name = "x_active"


def _build_table_objects(model_cls: type[BaseModel]):
    if model_cls._table_object_definitions:
        raise TypeError(
            f"Model {model_cls._name!r}: registry class must not own "
            f"table-object definitions"
        )
    model_cls._table_objects = frozendict(
        {
            cons.full_name(model_cls): cons
            for cls in reversed(model_cls._model_classes__)
            if isinstance(cls, models.MetaModel)
            for cons in cls._table_object_definitions
        }
    )


def _check_inherits(model_cls: type[BaseModel]):
    for comodel_name, field_name in model_cls._inherits.items():
        field = model_cls._fields.get(field_name)
        if not field or not field.is_many2one:
            raise TypeError(
                f"Missing many2one field definition for _inherits reference {field_name!r} in model {model_cls._name!r}. "
                f"Add a field like: {field_name} = fields.Many2one({comodel_name!r}, required=True, ondelete='cascade')"
            )
        if not (
            field.delegate
            and field.required
            and (field.ondelete or "").lower() in ("cascade", "restrict")
        ):
            raise TypeError(
                f"Field definition for _inherits reference {field_name!r} in {model_cls._name!r} "
                "must be marked as 'delegate', 'required' with ondelete='cascade' or 'restrict'"
            )


def _add_inherited_fields(model_cls: type[BaseModel]):
    if model_cls._abstract or not model_cls._inherits:
        return

    to_inherit: dict[str, tuple[str, Field]] = {}
    for parent_model_name, parent_fname in model_cls._inherits.items():
        for name, field in model_cls.pool[parent_model_name]._fields.items():
            if name in model_cls._fields:
                continue
            if (existing := to_inherit.get(name)) is not None:
                _logger.warning(
                    "Model %r inherits field %r from both %r and %r; "
                    "the latter (parent_field=%r) wins by inherits order",
                    model_cls._name,
                    name,
                    existing[1].model_name,
                    field.model_name,
                    parent_fname,
                )
            to_inherit[name] = (parent_fname, field)

    for name, (parent_fname, field) in to_inherit.items():
        field_cls = type(field)
        add_field(
            model_cls,
            name,
            field_cls(
                inherited=True,
                inherited_field=field,
                related=f"{parent_fname}.{name}",
                related_sudo=False,
                copy=field.copy,
                readonly=field.readonly,
                export_string_translation=field.export_string_translation,
            ),
        )


def _setup_fields(model_cls: type[BaseModel], env: Environment):
    bad_fields = []
    many2one_company_dependents = model_cls.pool.many2one_company_dependents
    model = model_cls(env, (), ())
    for name, field in model_cls._fields.items():
        try:
            field.setup(model)
        except Exception:
            if field.base_field.manual:
                _logger.warning(
                    "Skipping manual field %s.%s during setup; the field will not be available",
                    model_cls._name,
                    name,
                    exc_info=True,
                )
                bad_fields.append(name)
                continue
            raise
        if field.is_many2one and field.company_dependent:
            many2one_company_dependents.add(field.comodel_name, field)

    for name in bad_fields:
        pop_field(model_cls, name)


def _add_manual_models(env: Environment):
    removed_fields = OrderedSet()
    for name, model_cls in list(env.registry.items()):
        if model_cls._custom:
            removed_fields.update(model_cls._fields.values())
            del env.registry.models[name]
            for parent_cls in model_cls.__bases__:
                if hasattr(parent_cls, "pool"):
                    parent_cls._inherit_children.discard(name)
            for parent_name in model_cls._inherits:
                inherits_parent_cls = env.registry.models.get(parent_name)
                if inherits_parent_cls is not None:
                    inherits_parent_cls._inherits_children.discard(name)

    if removed_fields:
        env.registry._discard_fields(list(removed_fields))

    env.cr.execute(
        "SELECT *, name->>'en_US' AS name FROM ir_model WHERE state = 'manual'",
        prepare=False,
    )
    for model_data in env.cr.dictfetchall():
        attrs = env["ir.model"]._prepare_class_attrs(model_data)

        table_name = model_data["model"].replace(".", "_")
        table_kind = sql.table_kind(env.cr, table_name)
        if table_kind not in (sql.TableKind.Regular, None):
            _logger.info(
                "Model %r is backed by table %r which is not a regular table (%r), disabling automatic schema management",
                model_data["model"],
                table_name,
                table_kind,
            )
            attrs["_auto"] = False
            columns = sql.table_columns(env.cr, table_name).keys()
            attrs["_log_access"] = set(LOG_ACCESS_COLUMNS) <= columns

        model_def = type("CustomDefinitionModel", (models.Model,), attrs)
        add_to_registry(env.registry, model_def)


def _add_manual_fields(model_cls: type[BaseModel], env: Environment):
    IrModelFields = env["ir.model.fields"]

    fields_data = IrModelFields._get_manual_field_data(model_cls._name)
    for name, field_data in fields_data.items():
        if name not in model_cls._fields and field_data["state"] == "manual":
            try:
                if not IrModelFields._is_field_ready(field_data):
                    continue
                attrs = IrModelFields._prepare_field_attrs(field_data)
                field = fields.Field._by_type__[field_data["ttype"]](**attrs)
                add_field(model_cls, name, field)
            except Exception:
                _logger.exception(
                    "Failed to load field %s.%s: skipped",
                    model_cls._name,
                    field_data["name"],
                )


def add_field(model_cls: type[BaseModel], name: str, field: Field):
    is_class_field = any(
        isinstance(getattr(model, name, None), fields.Field)
        for model in [model_cls]
        + [model_cls.pool[inherit] for inherit in model_cls._inherits]
    )
    if not (is_class_field or is_manual_name(name)):
        raise ValidationError(
            f"The field `{name}` is not defined in the `{model_cls._name}` Python class and does not start with 'x_'"
        )

    if not isinstance(field, fields.Field):
        raise ValidationError(
            _("You can only add `fields.Field` objects to a model fields")
        )

    if not isinstance(getattr(model_cls, name, field), fields.Field):
        _logger.warning(
            "In model %r, field %r overriding existing value",
            model_cls._name,
            name,
        )
    setattr(model_cls, name, field)
    field._toplevel = True
    field.__set_name__(model_cls, name)
    model_cls._fields__[name] = field


def pop_field(model_cls: type[BaseModel], name: str) -> Field | None:
    field = model_cls._fields__.pop(name, None)
    discardattr(model_cls, name)
    if model_cls._rec_name == name:
        model_cls._rec_name = None
        if model_cls.display_name in model_cls.pool.field_depends:
            model_cls.pool.field_depends[model_cls.display_name] = tuple(
                dep
                for dep in model_cls.pool.field_depends[model_cls.display_name]
                if dep != name
            )
    return field
