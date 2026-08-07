import typing
from collections import defaultdict
from operator import attrgetter
from typing import override

from odoo.libs.sql import pg_varchar
from odoo.tools import SQL, OrderedSet, unique

from .._recordset import is_recordset
from .base import Field
from .numeric import Integer
from .selection import Selection

if typing.TYPE_CHECKING:
    from .._typing import ModelLike
    from ..models import BaseModel

REFERENCE_VERIFIED_CACHE_KEY = "reference.verified_pairs"


class Reference(Selection):
    """Pseudo-relational field (no FK in database).

    The field value is stored as a :class:`string <str>` following the pattern
    ``"res_model,res_id"`` in database.
    """

    type = "reference"

    _column_type = ("varchar", pg_varchar())

    if not typing.TYPE_CHECKING:
        __get__ = Field.__get__

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> typing.Any:
        if is_recordset(value):
            value = self.convert_to_cache(value, record, validate)
        return Field.convert_to_column(self, value, record, values, validate)

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> str | None:
        if is_recordset(value):
            if not validate:
                return f"{value._name},{value.id}" if value else None
            if value._name in self.get_values(record.env) and len(value) <= 1:
                if not value:
                    return None
                res_id = value.id
                if isinstance(res_id, int):
                    memo = self._verified_pairs(record.env)
                    if (
                        value._name,
                        res_id,
                    ) not in memo and not self._reference_exists(
                        record, value._name, res_id, memo
                    ):
                        return None
                return f"{value._name},{res_id}"
        elif isinstance(value, str):
            res_model, sep, res_id = value.partition(",")
            if sep and res_model:
                try:
                    res_id_int = int(res_id)
                except ValueError:
                    res_id_int = None
                if res_id_int is not None:
                    if not validate:
                        return value
                    memo = self._verified_pairs(record.env)
                    if (res_model, res_id_int) in memo:
                        return value
                    if res_model in self.get_values(record.env):
                        if self._reference_exists(record, res_model, res_id_int, memo):
                            return value
                        return None
        elif not value:
            return None
        raise ValueError(f"Wrong value for {self}: {value!r}")

    def _verified_pairs(self, env) -> set[tuple[str, int]]:
        """Return this field's transaction-scoped set of verified
        ``(res_model, res_id)`` pairs (see :data:`REFERENCE_VERIFIED_CACHE_KEY`)."""
        per_field = env.cr.cache.setdefault(REFERENCE_VERIFIED_CACHE_KEY, {})
        return per_field.setdefault((self.model_name, self.name), set())

    def _reference_exists(
        self,
        record: ModelLike,
        res_model: str,
        res_id: int,
        memo: set[tuple[str, int]],
    ) -> bool:
        """Return whether the ``res_model,res_id`` target exists, with batching.

        The naive per-value ``browse(res_id).exists()`` issues one SELECT per
        converted value, which is O(n) on batch create (``_populate_create_cache``
        converts one ``(record, value)`` pair at a time and offers no batch
        hook).  Two layers keep this O(1) per batch instead:

        1. ``memo``, the field's transaction-scoped set of verified pairs
           (:meth:`_verified_pairs`, consulted by ``convert_to_cache`` before
           even the selection lookup), so repeated values — within a batch or
           across calls in the same transaction — are checked once;
        2. on a memo miss during batch-create cache population (singleton
           ``record`` whose prefetch set spans the just-INSERTed batch), the
           sibling rows' column values are fetched in one SELECT and validated
           together, one ``exists()`` query per referenced model, seeding the
           memo for the rest of the batch.

        Net cost for a create batch of N distinct references: one column fetch
        plus one existence query per distinct target model (plus a single
        selection lookup), instead of N of each.  Single-record paths keep
        their single query.
        """
        env = record.env
        if (res_model, res_id) in memo:
            return True

        ids_per_model: dict[str, set[int]] = {res_model: {res_id}}

        prefetch_ids = [id_ for id_ in record._prefetch_ids if isinstance(id_, int)]
        if (
            len(record._ids) == 1
            and len(prefetch_ids) > 1
            and self.store
            and self.column_type
            and env.backend is None
        ):
            env.cr.execute(
                SQL(
                    "SELECT DISTINCT %(column)s FROM %(table)s"
                    " WHERE id = ANY(%(ids)s) AND %(column)s IS NOT NULL",
                    column=SQL.identifier(self.name),
                    table=SQL.identifier(env[self.model_name]._table),
                    ids=prefetch_ids,
                )
            )
            valid_models = None
            for (sibling,) in env.cr.fetchall():
                model, sep, id_str = sibling.partition(",")
                try:
                    sibling_id = int(id_str)
                except ValueError:
                    continue
                if not sep or not model or (model, sibling_id) in memo:
                    continue
                if valid_models is None:
                    valid_models = set(self.get_values(env))
                if model in valid_models and model in env.registry:
                    ids_per_model.setdefault(model, set()).add(sibling_id)

        for model, ids in ids_per_model.items():
            existing = env[model].browse(ids).exists()
            memo.update((model, id_) for id_ in existing._ids)

        return (res_model, res_id) in memo

    @override
    def convert_to_record(
        self, value: typing.Any, record: ModelLike
    ) -> BaseModel | None:
        if value:
            res_model, res_id = value.split(",")
            return record.env[res_model].browse(int(res_id))
        return None

    @override
    def convert_to_read(
        self, value: typing.Any, record: ModelLike, use_display_name: bool = True
    ) -> str | typing.Literal[False]:
        return f"{value._name},{value.id}" if value else False

    @override
    def convert_to_export(self, value: typing.Any, record: ModelLike) -> str:
        return value.display_name if value else ""

    @override
    def convert_to_display_name(
        self, value: typing.Any, record: ModelLike
    ) -> str | typing.Literal[False]:
        return value.display_name if value else False


class Many2oneReference(Integer):
    """Pseudo-relational field (no FK in database).

    The field value is stored as an :class:`integer <int>` id in database.

    Contrary to :class:`Reference` fields, the model has to be specified
    in a :class:`Char` field, whose name has to be specified in the
    `model_field` attribute for the current :class:`Many2oneReference` field.

    :param str model_field: name of the :class:`Char` where the model name is stored.
    """

    type = "many2one_reference"

    model_field = None
    aggregator = None

    _related_model_field = property(attrgetter("model_field"))

    _description_model_field = property(attrgetter("model_field"))

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> typing.Any:
        if is_recordset(value):
            value = value._ids[0] if value._ids else None
        return super().convert_to_cache(value, record, validate)

    @override
    def _update_inverses(self, records: BaseModel, value: typing.Any) -> None:
        """Add `records` to the cached values of the inverse fields of `self`.

        Only the inverse fields whose model actually appears in ``records`` are
        visited. A reference field is the inverse of one field per model that
        points at it -- 136 of them for ``mail.message.res_id`` -- while a given
        batch names one or two models, so indexing the (default)dict per inverse
        field built an empty entry and a throwaway recordset for every other
        one: 13600 browses per ``create()`` of 100 partners, 28ms of the 48ms
        spent here.
        """
        if not value:
            return
        model_ids = self._record_ids_per_res_model(records)

        for invf in records.pool.field_inverses[self]:
            ids = model_ids.get(invf.model_name)
            if not ids:
                continue
            recs = records.browse(ids)
            corecord = records.env[invf.model_name].browse(value)
            recs = recs.filtered_domain(invf.get_comodel_domain(corecord))
            if not recs:
                continue
            ids0 = invf._get_cache(corecord.env).get(corecord.id)
            if ids0 is not None or not corecord.id:
                ids1 = tuple(unique((ids0 or ()) + recs._ids))
                invf._update_cache(corecord, ids1)

    def _record_ids_per_res_model(self, records: BaseModel) -> dict[str, OrderedSet]:
        model_ids = defaultdict(OrderedSet)
        for record in records:
            model = record[self.model_field]
            if not model and record._fields[self.model_field].compute:
                record._fields[self.model_field].compute_value(record)
                model = record[self.model_field]
                if not model:
                    continue
            model_ids[model].add(record.id)
        return model_ids
