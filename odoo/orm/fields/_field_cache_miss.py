import typing
from collections.abc import Callable

from odoo.exceptions import AccessError, MissingError
from odoo.tools.misc import SENTINEL

if typing.TYPE_CHECKING:
    from .._typing import BaseModel
    from ..primitives import IdType
    from ..runtime import Environment
    from .base import Field


def _batch_then_single(
    batch: Callable[[], None],
    single: Callable[[], None],
    recs: BaseModel,
    *,
    catching: tuple[type[BaseException], ...],
    reraise_when_single: bool = True,
) -> bool:
    try:
        batch()
        return False
    except catching:
        if reraise_when_single and len(recs) == 1:
            raise
    single()
    return True


def cache_miss_stored(field: Field, record: BaseModel, env: Environment, record_id):
    recs = field._to_prefetch(record)
    _batch_then_single(
        lambda: recs._fetch_field(field),
        lambda: record._fetch_field(field),
        recs,
        catching=(AccessError,),
    )
    field_cache = field._get_cache(env)
    value = field_cache.get(record_id, SENTINEL)
    if value is SENTINEL:
        raise MissingError(
            "\n".join(
                [
                    env._("Record does not exist or has been deleted."),
                    env._(
                        "(Record: %(record)s, User: %(user)s)",
                        record=record,
                        user=env.uid,
                    ),
                ]
            )
        ) from None
    return value


def cache_miss_origin(field: Field, record: BaseModel, env: Environment, record_id):
    recs = field._to_prefetch(record)
    origin_prefetch = recs._origin._prefetch_ids
    spawn = type(recs)._spawn
    recs_env = recs.env

    def _batch() -> None:
        for rec in recs:
            rec_id = rec._ids[0]
            if origin_id := (rec_id or getattr(rec_id, "origin", None)):
                rec_origin = spawn(recs_env, (origin_id,), origin_prefetch)
                field._update_cache(
                    rec,
                    field.convert_to_cache(rec_origin[field.name], rec, validate=False),
                )

    def _single() -> None:
        field._update_cache(
            record,
            field.convert_to_cache(record._origin[field.name], record, validate=False),
        )

    _batch_then_single(
        _batch, _single, recs, catching=(AccessError, KeyError, MissingError)
    )
    return field._get_cache(env)[record_id]


def cache_miss_compute(field: Field, record: BaseModel, env: Environment, record_id):
    if env.is_protected(field, record):
        value = field.convert_to_cache(False, record, validate=False)
        field._update_cache(record, value)
    else:
        recs = record if field.recursive else field._to_prefetch(record)
        if _batch_then_single(
            lambda: field.compute_value(recs),
            lambda: field.compute_value(record),
            recs,
            catching=(AccessError, MissingError),
            reraise_when_single=False,
        ):
            recs = record

        missing_recs_ids = tuple(field._cache_missing_ids(recs))
        if missing_recs_ids:
            missing_recs = record.browse(missing_recs_ids)
            if field.readonly and not field.store:
                raise ValueError(
                    f"Compute method failed to assign {missing_recs}.{field.name}"
                )
            false_value = field.convert_to_cache(False, record, validate=False)
            field._update_cache(missing_recs, false_value)

        field_cache = field._get_cache(env)
        value = field_cache[record_id]
    return value


def cache_miss_delegating(field: Field, record: BaseModel, env: Environment):
    def is_inherited_field(name):
        candidate = record._fields[name]
        related = candidate.related
        return bool(
            candidate.inherited and related and related.split(".")[0] == field.name
        )

    parent = record.env[field.comodel_name].new(
        {
            name: value
            for name, value in record._cache.items()
            if is_inherited_field(name)
        }
    )
    value = field.convert_to_cache(parent, record, validate=False)
    field._update_cache(record, value)
    if inv_recs := parent._new_records:
        for invf in env.registry.field_inverses[field]:
            invf._update_inverse(inv_recs, record)
    return value


def cache_miss_default(field: Field, record: BaseModel, env: Environment, record_id):
    value = field.convert_to_cache(False, record, validate=False)
    field._update_cache(record, value)
    defaults = record.default_get([field.name])
    if field.name in defaults:
        value = field.convert_to_cache(defaults[field.name], record)
        field._update_cache(record, value)
    return field._get_cache(env)[record_id]


def get_cache_miss(
    field: Field, record: BaseModel, env: Environment, record_id: IdType
) -> typing.Any:
    if field.store and record_id:
        value = cache_miss_stored(field, record, env, record_id)
    elif field.store and record._has_origin and not (field.compute and field.readonly):
        value = cache_miss_origin(field, record, env, record_id)
    elif field.compute:
        value = cache_miss_compute(field, record, env, record_id)
    elif field.is_delegating and not record_id:
        value = cache_miss_delegating(field, record, env)
    else:
        value = cache_miss_default(field, record, env, record_id)

    return field.convert_to_record(value, record)
