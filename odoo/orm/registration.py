import logging
import typing
from collections import defaultdict
from types import MappingProxyType

from odoo.exceptions import ValidationError
from odoo.tools import (
    LastOrderedSet,
    OrderedSet,
    discardattr,
    frozendict,
    sql,
)
from odoo.tools.translate import FIELD_TRANSLATE, _

from . import (
    fields,
    models,
)
from .primitives import LOG_ACCESS_COLUMNS
from .validation import check_pg_name, is_manual_name

if typing.TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.fields import Field
    from odoo.models import BaseModel
    from odoo.modules.registry import Registry

_logger = logging.getLogger("odoo.registry")

# MODEL DEFINITIONS vs MODEL CLASSES
#
# "Model definitions" are the (mostly static) classes written in module source;
# custom models are the exception, built dynamically. "Model classes" are what
# the registry holds and what recordsets are instances of; each is built
# dynamically when the registry loads, inheriting from all of the model's
# definitions (in reverse order, to match override order) plus, for inherited
# models, the parent model classes — so extensions to a parent are visible on
# the child. It also carries metadata inferred from its parents.
#
# E.g. with definitions A1/A2/A3 of model 'a' and B1/B2 of model 'b'
# (_inherit=['a','b']), parents of 'a' are (A2, A1) and of 'b' are (B2, a, B1),
# giving MRO 'a' = [a, A2, A1, Model] and 'b' = [b, B2, a, A2, A1, B1, Model].
#
# FIELDS: a field can be shared across registries (saving memory/time) only when
# set up directly on its model definition. It cannot be shared when it is
# related, overridden across definitions, or inherited from another model —
# because the field object is a key in per-registry dicts (cache, pending
# computations). Magic fields ('id', 'display_name', ...) are added on
# definition classes (not model classes) so they too can be shared.


def is_model_definition(cls: type) -> bool:
    """Return whether ``cls`` is a model definition class."""
    return isinstance(cls, models.MetaModel) and getattr(cls, "pool", None) is None


def is_model_class(cls: type) -> bool:
    """Return whether ``cls`` is a model registry class."""
    return getattr(cls, "pool", None) is not None


def add_to_registry(registry: Registry, model_def: type[BaseModel]) -> type[BaseModel]:
    """Add a model definition to the registry, creating or extending its model
    class, and return that model class.
    """
    # raise (not assert) so the contract holds under python -O
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

    # all models except 'base' implicitly inherit from 'base'
    name = model_def._name
    parent_names = list(model_def._inherit)
    if name != "base":
        parent_names.append("base")

    # create or retrieve the model's class
    if name in parent_names:
        if name not in registry:
            raise TypeError(f"Model {name!r} does not exist in registry.")
        model_cls = registry[name]
        _check_model_extension(model_cls, model_def)
    else:
        if name in registry:
            # A second fresh definition of an already-registered model (same
            # _name, no self-`_inherit`) — a classic accidental collision between
            # two modules.  It silently discards the first definition's fields
            # and metadata; surface it instead of losing work without a trace.
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
                "pool": registry,  # this makes it a model class
                "_name": name,
                "_register": False,
                "_original_module": model_def._module,
                "_inherit_module": {},  # map parent to introducing module
                "_inherit_children": OrderedSet(),  # names of children models
                "_inherits_children": set(),  # names of children models
                "_fields__": {},  # populated in _setup()
                "_table_objects": frozendict(),  # populated in _setup()
            },
        )
        model_cls._fields = MappingProxyType(model_cls._fields__)

    # determine all the classes the model should inherit from
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

    # model_cls.__bases__ must be assigned those classes; however, this
    # operation is quite slow, so we do it once in method _prepare_setup()
    model_cls._base_classes__ = tuple(bases)

    # determine the attributes of the model's class
    _init_model_class_attributes(model_cls)

    check_pg_name(model_cls._table)

    # Transience
    if model_cls._transient and not model_cls._log_access:
        msg = (
            "TransientModels must have log_access turned on, "
            "in order to implement their vacuum policy"
        )
        raise TypeError(msg)

    # update the registry after all checks have passed
    registry[name] = model_cls

    # mark all impacted models for setup
    for model_name in registry.descendants([name], "_inherit", "_inherits"):
        registry[model_name]._setup_done__ = False

    return model_cls


def _check_model_extension(model_cls: type[BaseModel], model_def: type[BaseModel]):
    """Check whether ``model_cls`` can be extended with ``model_def``."""
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
    """Check whether ``model_cls`` can inherit from ``parent_cls``."""
    if model_cls._abstract and not parent_cls._abstract:
        raise TypeError(
            f"In {model_def}, abstract model {model_cls._name!r} cannot inherit from non-abstract model {parent_cls._name!r}."
        )


def _init_model_class_attributes(model_cls: type[BaseModel]):
    """Initialize model class attributes."""
    # raise (not assert) so the contract holds under python -O
    if not is_model_class(model_cls):
        raise TypeError(f"{model_cls!r} is not a registry model class")

    model_cls._description = model_cls._name
    model_cls._table = model_cls._name.replace(".", "_")
    model_cls._log_access = model_cls._auto
    inherits = {}
    depends = {}

    for base in reversed(model_cls._base_classes__):
        if is_model_definition(base):
            # the following attributes are not taken from registry classes
            if model_cls._name not in base._inherit and not base._description:
                _logger.warning("The model %s has no _description", model_cls._name)
            model_cls._description = base._description or model_cls._description
            model_cls._table = base._table or model_cls._table
            model_cls._log_access = getattr(base, "_log_access", model_cls._log_access)

        inherits.update(base._inherits)

        for mname, fnames in base._depends.items():
            depends.setdefault(mname, []).extend(fnames)

    # avoid assigning an empty dict to save memory
    if inherits:
        model_cls._inherits = inherits
    if depends:
        model_cls._depends = depends

    # update _inherits_children of parent models
    registry = model_cls.pool
    for parent_name in model_cls._inherits:
        registry[parent_name]._inherits_children.add(model_cls._name)

    # recompute attributes of _inherit_children models
    for child_name in model_cls._inherit_children:
        _init_model_class_attributes(registry[child_name])


def setup_model_classes(env: Environment):
    registry = env.registry

    # setup ir.model before adding manual fields: _add_manual_models may rely
    # on overrides (e.g. is_mail_thread via env['ir.model']._instantiate_attrs)
    _prepare_setup(registry["ir.model"])

    # add manual models
    if registry._init_modules:
        _add_manual_models(env)

    # prepare the setup on all models
    models_classes = list(registry.values())
    for model_cls in models_classes:
        _prepare_setup(model_cls)

    # do the actual setup
    for model_cls in models_classes:
        _setup(model_cls, env)

    for model_cls in models_classes:
        _setup_fields(model_cls, env)

    for model_cls in models_classes:
        model_cls(env, (), ())._post_model_setup__()


def _prepare_setup(model_cls: type[BaseModel]):
    """Prepare the setup of the model."""
    if model_cls._setup_done__:
        # raise (not assert) so the invariant holds under python -O
        if model_cls.__bases__ != model_cls._base_classes__:
            raise TypeError(
                f"Model {model_cls._name!r}: __bases__ diverged from "
                f"_base_classes__ after setup"
            )
        return

    # changing base classes is costly, do it only when necessary
    if model_cls.__bases__ != model_cls._base_classes__:
        model_cls.__bases__ = model_cls._base_classes__

    # reset those attributes on the model's class for _setup_fields() below
    for attr in ("_rec_name", "_active_name"):
        discardattr(model_cls, attr)

    # reset properties memoized on model_cls's own __dict__ (via
    # ``helpers.own_class_memo``). The class object is reused across re-setup
    # (only ``__bases__`` is reassigned, above), so these memos survive class
    # recreation — discard them here, or a re-setup that adds/removes a field
    # keeps serving the stale tuple.
    for _memo in (
        "_constraint_methods__",
        "_ondelete_methods__",
        "_onchange_methods__",
        "_precompute_readonly_names__",
        "_properties_field_names__",
        "_stored_computed_fields__",
    ):
        discardattr(model_cls, _memo)


def _setup(model_cls: type[BaseModel], env: Environment):
    """Determine all the fields of the model.

    Orchestrates 7 setup phases for a model class:
    1. Collect and install field definitions (including database patches)
    2. Add manual (custom) fields
    3. Resolve inheritance and add inherited fields
    4. Initialize field metadata
    5. Validate _rec_name
    6. Validate _active_name
    7. Build table objects (constraints, indexes)
    """
    if model_cls._setup_done__:
        return

    # Detect cyclic _inherits before Phase 3 recurses to stack overflow:
    # _setup_done__ is set only in Phase 4, so a cycle would re-enter forever.
    # Read the marker MRO-blind (``__dict__.get``, not ``getattr``): registry
    # classes inherit from their parents' registry classes, so ``getattr`` could
    # see an ancestor mid-setup and raise with the wrong model name.
    if model_cls.__dict__.get("_setup_in_progress__", False):
        raise TypeError(f"Circular _inherits chain involving model {model_cls._name!r}")
    model_cls._setup_in_progress__ = True
    try:
        _setup_phases(model_cls, env)
    finally:
        # Remove the marker rather than leaving a ``False`` on every class dict.
        del model_cls._setup_in_progress__


def _setup_phases(model_cls: type[BaseModel], env: Environment) -> None:
    """The 7 setup phases of :func:`_setup`, split out so the caller can wrap
    them in a cycle-detection guard.
    """
    # Cache the model definition classes (non-registry classes from MRO),
    # used by fields.resolve_mro() and field collection below.
    model_cls._model_classes__ = tuple(
        c for c in model_cls.mro() if getattr(c, "pool", None) is None
    )

    # Phase 1: collect field definitions and install them on the model
    _collect_and_install_fields(model_cls, env)

    # Phase 2: add manual (studio/custom) fields
    if model_cls.pool._init_modules:
        _add_manual_fields(model_cls, env)

    # Phase 3: resolve _inherits delegation and add inherited fields
    _check_inherits(model_cls)
    for parent_name in model_cls._inherits:
        _setup(model_cls.pool[parent_name], env)
    _add_inherited_fields(model_cls)

    # Phase 4: initialize field metadata (mark setup done first to avoid cycles)
    model_cls._setup_done__ = True
    for field in model_cls._fields.values():
        field.prepare_setup()

    # Phase 5-6: validate rec_name and active_name
    _validate_rec_name(model_cls)
    _validate_active_name(model_cls)

    # Phase 7: build table objects (constraints, indexes)
    _build_table_objects(model_cls)


def _collect_and_install_fields(model_cls: type[BaseModel], env: Environment):
    """Collect field definitions from the MRO and install them on the model.

    Patches translate / company_dependent state from the database to prevent
    data loss during module upgrades.
    """
    # Clear existing fields to avoid clashes with inheritance between models
    for name in model_cls._fields:
        discardattr(model_cls, name)
    model_cls._fields__.clear()

    # Collect the definitions of each field (base definition + overrides)
    definitions = defaultdict(list)
    for cls in reversed(model_cls._model_classes__):
        # this condition is an optimization of is_model_definition(cls)
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
    """Preserve translate=True when the DB column is already translated.

    Prevents data loss when an upgrade drops translate from a field definition
    but the column still holds translated data.
    """
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
    """Preserve company_dependent=True when the DB column is already jsonb.

    Prevents data loss when an upgrade drops company_dependent from a field
    definition but the column is already jsonb.
    """
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
        # validate column type in case it was changed by an upgrade script
        col = sql.table_columns(env.cr, model_cls._table).get(name)
        if col and col["udt_name"] == "jsonb":
            _logger.debug(
                "Patching %s.%s with company_dependent=True",
                model_cls._name,
                name,
            )
            fields_.append(type(fields_[0])(company_dependent=True))


def _validate_rec_name(model_cls: type[BaseModel]):
    """Determine and validate the _rec_name attribute."""
    if model_cls._rec_name:
        # raise (not assert) so the validation holds under python -O
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
    """Determine and validate the _active_name attribute."""
    if model_cls._active_name:
        # raise (not assert) so the validation holds under python -O
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
    """Build the table objects (constraints, indexes) for the model."""
    # The MetaModel attaches a fresh empty list to every class it constructs
    # (including the registry class created at registration.add_to_registry),
    # so a non-empty list here means a constraint was declared on the registry
    # class itself rather than on a model definition.  raise (not assert) so
    # the invariant holds under python -O.
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
        if not field or field.type != "many2one":
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
    """Determine inherited fields."""
    if model_cls._abstract or not model_cls._inherits:
        return

    # When two _inherits parents share a field name, the last in iteration
    # order wins; warn so accidental collisions surface in the logs.  Only
    # names that will actually be inherited can collide: fields already
    # defined on the model itself (including the magic fields id,
    # display_name, create_uid/date, write_uid/date that every parent also
    # carries) are never inherited, so they are filtered out *before*
    # collision tracking — otherwise every model with two _inherits parents
    # would log six spurious magic-field warnings.
    to_inherit: dict[str, tuple[str, Field]] = {}
    for parent_model_name, parent_fname in model_cls._inherits.items():
        for name, field in model_cls.pool[parent_model_name]._fields.items():
            if name in model_cls._fields:
                # redefined locally: never inherited, not a collision
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

    # add the inherited fields (none of them is redefined locally: names
    # present in model_cls._fields were filtered out above)
    for name, (parent_fname, field) in to_inherit.items():
        # inherited fields are implemented as related fields, with the
        # following specific properties:
        #  - reading inherited fields should not bypass access rights
        #  - copy inherited fields iff their original field is copied
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
    """Setup the fields, except for recomputation triggers."""
    bad_fields = []
    many2one_company_dependents = model_cls.pool.many2one_company_dependents
    model = model_cls(env, (), ())
    for name, field in model_cls._fields.items():
        try:
            field.setup(model)
        except Exception:
            if field.base_field.manual:
                # WARNING (not DEBUG): manual fields are user-created (Studio);
                # the system recovers by skipping, but the user must see it.
                _logger.warning(
                    "Skipping manual field %s.%s during setup; the field will not be available",
                    model_cls._name,
                    name,
                    exc_info=True,
                )
                # Setup can fail for a manual related/function field whose
                # dependency (e.g. comodel) is not loaded yet.
                bad_fields.append(name)
                continue
            raise
        if field.type == "many2one" and field.company_dependent:
            many2one_company_dependents.add(field.comodel_name, field)

    for name in bad_fields:
        pop_field(model_cls, name)


def _add_manual_models(env: Environment):
    """Add extra models to the registry."""
    # clean up registry first
    removed_fields = OrderedSet()
    for name, model_cls in list(env.registry.items()):
        if model_cls._custom:
            removed_fields.update(model_cls._fields.values())
            del env.registry.models[name]
            # remove the model's name from its parents' _inherit_children
            for parent_cls in model_cls.__bases__:
                if hasattr(parent_cls, "pool"):
                    parent_cls._inherit_children.discard(name)

    if removed_fields:
        # discard removed custom fields from the registry's dependency maps
        # (notably field_setup_dependents); otherwise they leak and duplicate
        # across successive registry setups
        env.registry._discard_fields(list(removed_fields))

    # can't use self._fields for translated fields: not set up yet
    env.cr.execute(
        "SELECT *, name->>'en_US' AS name FROM ir_model WHERE state = 'manual'"
    )
    for model_data in env.cr.dictfetchall():
        attrs = env["ir.model"]._instantiate_attrs(model_data)

        # adapt _auto and _log_access if necessary
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
    """Add extra fields on model."""
    IrModelFields = env["ir.model.fields"]

    fields_data = IrModelFields._get_manual_field_data(model_cls._name)
    for name, field_data in fields_data.items():
        if name not in model_cls._fields and field_data["state"] == "manual":
            try:
                attrs = IrModelFields._instantiate_attrs(field_data)
                if attrs:
                    field = fields.Field._by_type__[field_data["ttype"]](**attrs)
                    add_field(model_cls, name, field)
            except Exception:
                _logger.exception(
                    "Failed to load field %s.%s: skipped",
                    model_cls._name,
                    field_data["name"],
                )


def add_field(model_cls: type[BaseModel], name: str, field: Field):
    """Add ``field`` under ``name`` on ``model_cls``."""
    # name must be an existing field on the model or an _inherits parent, or a
    # custom field (starting with `x_`)
    is_class_field = any(
        isinstance(getattr(model, name, None), fields.Field)
        for model in [model_cls]
        + [model_cls.pool[inherit] for inherit in model_cls._inherits]
    )
    if not (is_class_field or is_manual_name(name)):
        raise ValidationError(  # pylint: disable=missing-gettext
            f"The field `{name}` is not defined in the `{model_cls._name}` Python class and does not start with 'x_'"
        )

    # Assert the attribute to assign is a Field
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
    # add field as an attribute and in model_cls._fields__ (for reflection)
    model_cls._fields__[name] = field


def pop_field(model_cls: type[BaseModel], name: str) -> Field | None:
    """Remove the field named ``name`` from ``model_cls``."""
    field = model_cls._fields__.pop(name, None)
    discardattr(model_cls, name)
    if model_cls._rec_name == name:
        # fixup _rec_name and display_name's dependencies
        model_cls._rec_name = None
        if model_cls.display_name in model_cls.pool.field_depends:
            model_cls.pool.field_depends[model_cls.display_name] = tuple(
                dep
                for dep in model_cls.pool.field_depends[model_cls.display_name]
                if dep != name
            )
    return field
