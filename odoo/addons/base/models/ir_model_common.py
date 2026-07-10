"""Shared, class-independent helpers for the ``ir.model.*`` reflection family.

A leaf module: depends only on ORM core, never on the ``ir_model*`` model
classes. Housing these constants and pure functions here lets the siblings
(``ir_model``, ``ir_model_fields``, ...) share them without importing each
other, which previously formed an import cycle.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from itertools import batched
from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from odoo import api, models
from odoo.tools import SQL
from odoo.tools.safe_eval import datetime, dateutil, safe_eval, time
from odoo.tools.translate import LazyTranslate

if TYPE_CHECKING:
    from odoo.db.cursor import BaseCursor

_lt = LazyTranslate(__name__)

# Messages are declared in extenso so they are properly exported in translation terms
ACCESS_ERROR_HEADER = {
    "read": _lt(
        "You are not allowed to access '%(document_kind)s' (%(document_model)s) records."
    ),
    "write": _lt(
        "You are not allowed to modify '%(document_kind)s' (%(document_model)s) records."
    ),
    "create": _lt(
        "You are not allowed to create '%(document_kind)s' (%(document_model)s) records."
    ),
    "unlink": _lt(
        "You are not allowed to delete '%(document_kind)s' (%(document_model)s) records."
    ),
}
ACCESS_ERROR_GROUPS = _lt(
    "This operation is allowed for the following groups:\n%(groups_list)s"
)
ACCESS_ERROR_NOGROUP = _lt("No group currently allows this operation.")
ACCESS_ERROR_RESOLUTION = _lt(
    "Contact your administrator to request access if necessary."
)

MODULE_UNINSTALL_FLAG = "_force_unlink"

# base environment for doing a safe_eval
SAFE_EVAL_BASE = {
    "datetime": datetime,
    "dateutil": dateutil,
    "time": time,
}


def make_compute(text: str, deps: str | None) -> Callable[[models.BaseModel], Any]:
    """Return a compute function from its code body and dependencies.

    ``text`` is a Python block that writes results back through subscript
    assignment (``for record in self: record[fname] = ...``); ``safe_eval``
    forbids ``STORE_ATTR``, so ``record.fname = ...`` is *not* usable and the
    function's return value is unused.  ``deps`` is a comma-separated field list.
    """

    def compute(self: models.BaseModel) -> None:
        safe_eval(text, SAFE_EVAL_BASE | {"self": self}, mode="exec")

    # Drop blank tokens so a stray/trailing comma ("a," or "a,,b" — plausible on
    # a user-edited manual field) never yields an empty dependency name, which
    # would later fail as ``model._fields['']`` during registry setup.
    dep_names = [name.strip() for name in deps.split(",")] if deps else []
    dep_names = [name for name in dep_names if name]
    return api.depends(*dep_names)(compute)


def mark_modified(records: models.BaseModel, fnames: list[str]) -> None:
    """Mark the given fields as modified on records."""
    # protect all modified fields, to avoid them being recomputed
    field_objs = [records._fields[fname] for fname in fnames]
    with records.env.protecting(field_objs, records):
        records.modified(fnames)


def compute_modules(records: models.BaseModel) -> None:
    """Shared compute for the ``modules`` field of ``ir.model`` and
    ``ir.model.fields``: the sorted, comma-separated list of installed modules
    that define (or extend) each record, derived from its XML ids.
    """
    installed = records.env["ir.module.module"].search_fetch(
        [("state", "=", "installed")], ["name"]
    )
    installed_names = set(installed.mapped("name"))
    xml_ids = records._get_external_ids()
    for record in records:
        module_names = {xml_id.split(".")[0] for xml_id in xml_ids[record.id]}
        record.modules = ", ".join(sorted(installed_names & module_names))


def reload_schema(
    env: api.Environment,
    setup_models: Collection[str],
    init_models: Collection[str] = (),
) -> None:
    """Reload the registry (and optionally the DB schema) after a change to the
    reflected model/field definitions: flush pending updates, run an incremental
    ``_setup_models__`` for ``setup_models``, then ``init_models`` for
    ``init_models`` and their ``_inherits`` descendants.

    :param setup_models: model names passed to ``_setup_models__``. An *empty*
        collection still runs the incremental setup (reloading custom models);
        ``ir.model.create`` relies on this.
    :param init_models: model names whose DB schema must be updated; empty means
        "registry reload only".
    """
    env.flush_all()  # _setup_models__ must read up-to-date rows from the db
    registry = env.registry
    registry._setup_models__(env.cr, setup_models)
    if init_models:
        affected_models = registry.descendants(init_models, "_inherits")
        registry.init_models(
            env.cr, affected_models, dict(env.context, update_custom_fields=True)
        )


def _model_slug(model_name: str) -> str:
    """Return the XML-id-safe form of a dotted model name (``a.b`` -> ``a_b``)."""
    return model_name.replace(".", "_")


def model_xmlid(module: str, model_name: str) -> str:
    """Return the XML id of the given model."""
    return f"{module}.model_{_model_slug(model_name)}"


def inherit_xmlid(module: str, model_name: str, parent_name: str) -> str:
    """Return the XML id of the given ``ir.model.inherit`` record."""
    return (
        f"{module}.model_inherit__{_model_slug(model_name)}__{_model_slug(parent_name)}"
    )


def field_xmlid(module: str, model_name: str, field_name: str) -> str:
    """Return the XML id of the given field."""
    return f"{module}.field_{_model_slug(model_name)}__{field_name}"


def selection_xmlid(module: str, model_name: str, field_name: str, value: str) -> str:
    """Return the XML id of the given selection."""
    xvalue = value.replace(".", "_").replace(" ", "_").lower()
    return f"{module}.selection__{_model_slug(model_name)}__{field_name}__{xvalue}"


def query_insert(
    cr: BaseCursor, table: str, rows: list[dict[str, Any]] | Mapping[str, Any]
) -> list[int]:
    """Insert rows in a table. ``rows`` is a list of dicts, all with the same
    set of keys. Return the ids of the new rows.

    The columns are taken from the first row, so every row must carry exactly
    that key set: a missing key raises ``KeyError`` and an extra key is ignored.
    """
    if isinstance(rows, Mapping):
        rows = [rows]
    if not rows:
        return []
    cols = list(rows[0])
    return cr.copy_from(
        table,
        cols,
        [tuple(row[col] for col in cols) for row in rows],
        returning_ids=True,
    )


def query_update(
    cr: BaseCursor, table: str, values: dict[str, Any], selectors: list[str]
) -> list[int]:
    """Update the table with the given values (dict), and use the columns in
    ``selectors`` to select the rows to update.
    """
    selector_set = set(selectors)
    assignments = [
        SQL("%s = %s", SQL.identifier(key), val)
        for key, val in values.items()
        if key not in selector_set
    ]
    if not assignments:
        raise ValueError(
            f"query_update: no columns to update on {table!r}; every key in "
            f"{list(values)} is a selector ({selectors}), so the SET clause "
            "would be empty."
        )
    query = SQL(
        "UPDATE %s SET %s WHERE %s RETURNING id",
        SQL.identifier(table),
        SQL(", ").join(assignments),
        SQL(" AND ").join(
            SQL("%s = %s", SQL.identifier(key), values[key]) for key in selectors
        ),
    )
    cr.execute(query)
    return [row[0] for row in cr.fetchall()]


def select_en(
    model: models.BaseModel, fnames: list[str], model_names: list[str]
) -> list[tuple[Any, ...]]:
    """Select the given columns for the rows whose ``model`` is in *model_names*.

    Translated fields are returned in 'en_US'.  Only usable on tables that have
    a ``model`` text column (``ir.model``, ``ir.model.fields``, ...); siblings
    keyed differently read with a purpose-built query instead.
    """
    if not model_names:
        return []
    cols = SQL(", ").join(
        (
            SQL("%s->>'en_US'", SQL.identifier(fname))
            if model._fields[fname].translate
            else SQL.identifier(fname)
        )
        for fname in fnames
    )
    query = SQL(
        "SELECT %s FROM %s WHERE model = ANY(%s)",
        cols,
        SQL.identifier(model._table),
        list(model_names),
    )
    return model.env.execute_query(query)


def _build_upsert_query(
    model: models.BaseModel,
    fnames: list[str],
    conflict: list[str],
    values: SQL,
) -> SQL:
    """Build the ``MERGE`` statement used by :func:`upsert_en`.

    Pure (no database access): *values* is the pre-rendered
    ``(v, ...), (v, ...)`` source list for one batch.  Kept separate from
    execution so the generated SQL is unit-testable without a cursor.
    """
    fields = model._fields
    comma = SQL(", ").join
    col_ids = [SQL.identifier(fname) for fname in fnames]

    # Unlike INSERT … VALUES (which resolves NULL types against the target
    # column), MERGE … USING (VALUES …) treats the source as an independent
    # sub-query: an all-NULL column defaults to text, causing type mismatches
    # (text vs jsonb/int4). Cast every source column to its target type.
    def _pg_cast(fname: str) -> SQL:
        ct = fields[fname].column_type
        if ct and ct[0] not in ("varchar", "text"):
            return SQL("::%s", SQL(ct[0]))
        return SQL("")

    casts = [_pg_cast(fname) for fname in fnames]
    s_cols = [
        SQL("s.%s%s", col_id, cast) for col_id, cast in zip(col_ids, casts, strict=True)
    ]
    on_pred = SQL(" AND ").join(
        SQL("t.%s = s.%s", SQL.identifier(c), SQL.identifier(c)) for c in conflict
    )
    assignments = comma(
        (
            # ``translate is True`` (user translations) keep other languages by
            # merging jsonb; callable-translate and plain columns overwrite, as
            # translated values are reloaded right after reflection.
            SQL(
                "%s = COALESCE(t.%s, '{}'::jsonb) || s.%s%s",
                col_id,
                col_id,
                col_id,
                cast,
            )
            if fields[fname].translate is True
            else SQL("%s = s.%s%s", col_id, col_id, cast)
        )
        for fname, col_id, cast in zip(fnames, col_ids, casts, strict=True)
    )
    # Include conflict columns in RETURNING so the caller can reconstruct the
    # input order: unlike INSERT … ON CONFLICT (whose RETURNING follows VALUES
    # order), MERGE emits rows in join order, which is non-deterministic.
    returning = comma(
        [SQL("NEW.id")] + [SQL("NEW.%s", SQL.identifier(c)) for c in conflict]
    )
    return SQL(
        """
        MERGE INTO %(table)s t
        USING (VALUES %(values)s) AS s(%(cols)s)
        ON %(on_pred)s
        WHEN MATCHED THEN
            UPDATE SET %(assignments)s
        WHEN NOT MATCHED THEN
            INSERT (%(cols)s) VALUES (%(s_cols)s)
        RETURNING %(returning)s
        """,
        table=SQL.identifier(model._table),
        values=values,
        cols=comma(col_ids),
        on_pred=on_pred,
        assignments=assignments,
        s_cols=comma(s_cols),
        returning=returning,
    )


def upsert_en(
    model: models.BaseModel,
    fnames: list[str],
    rows: list[tuple[Any, ...]],
    conflict: list[str],
) -> list[int]:
    """Insert or update the table with the given rows using MERGE.

    :param model: recordset of the model to query
    :param fnames: list of column names (must be non-empty)
    :param rows: list of tuples, where each tuple value corresponds to a column
        name; rows must be unique on the *conflict* columns
    :param conflict: list of column names for the MERGE ON predicate
    :return: the ids of the inserted or updated rows, in the same order as *rows*
    """
    if not rows:
        return []
    if not fnames:
        raise ValueError("upsert_en: fnames must not be empty")

    fields = model._fields

    # Input order is reconstructed by mapping each conflict-key tuple to its
    # returned id, which needs hashable scalar keys that compare equal between
    # input and RETURNING output. A translated column round-trips as a jsonb
    # ``dict`` (unhashable, unequal), breaking this — reject it explicitly.
    if bad := [c for c in conflict if fields[c].translate]:
        raise ValueError(
            f"upsert_en: conflict columns cannot be translated fields (got {bad}); "
            "the RETURNING/reorder logic assumes scalar, hashable keys."
        )

    # Duplicate conflict keys within one batch make PostgreSQL MERGE raise
    # (a CardinalityViolation when the target exists, a UniqueViolation when it
    # doesn't), and would collapse two input rows onto one id.  Reject up front.
    conflict_indices = [fnames.index(c) for c in conflict]
    keys = [tuple(row[i] for i in conflict_indices) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError(
            f"upsert_en: rows are not unique on conflict columns {conflict}; "
            "MERGE cannot resolve duplicate source keys."
        )

    # for translated fields, we can actually erase the json value, as
    # translations will be reloaded after this
    def identity(val: Any) -> Any:
        return val

    def jsonify(val: Any) -> Any:
        # Jsonb (not Json) so MERGE's USING VALUES source table has jsonb type,
        # matching the target column for the || operator.
        return Jsonb({"en_US": val}) if val is not None else val

    wrappers = [(jsonify if fields[fname].translate else identity) for fname in fnames]
    values = [
        tuple(func(val) for func, val in zip(wrappers, row, strict=True))
        for row in rows
    ]

    # psycopg3 limits query parameters to 65535.  Each row contributes exactly
    # len(fnames) parameters (tuple expansion in the VALUES list), so keep
    # rows_per_batch * len(fnames) well under the limit.
    comma = SQL(", ").join
    batch_size = 65000 // len(fnames) or 1
    key_to_id = {}
    for batch in batched(values, batch_size, strict=False):
        query = _build_upsert_query(model, fnames, conflict, comma(batch))
        # Map conflict-key → id from the (unordered) result set.
        for result_row in model.env.execute_query(query):
            key_to_id[result_row[1:]] = result_row[0]

    return [key_to_id[key] for key in keys]
