import logging
from collections import defaultdict
from contextlib import contextmanager, suppress
from datetime import datetime
from typing import TYPE_CHECKING, Any

from dateutil.relativedelta import relativedelta
from psycopg.errors import InsufficientPrivilege

from odoo.fields import Field, Many2one
from odoo.libs.sql import SQL

if TYPE_CHECKING:
    from collections.abc import Generator

    from odoo.api import Environment
    from odoo.models import Model

_logger = logging.getLogger(__name__)

MIN_DATETIME = datetime((datetime.now() - relativedelta(years=4)).year, 1, 1)
MAX_DATETIME = datetime.now()


def get_field_variation_date(
    model: Model, field: Field, factor: int, series_alias: str
) -> SQL:
    total_days = min((MAX_DATETIME - MIN_DATETIME).days, factor)
    cast_type = SQL(field._column_type[1])

    def redistribute(value):
        return SQL(
            "(%(value)s - (%(factor)s - %(series_alias)s) * (%(total_days)s::float/%(factor)s) * interval '1 days')::%(cast_type)s",
            value=value,
            factor=factor,
            series_alias=SQL.identifier(series_alias),
            total_days=total_days,
            cast_type=cast_type,
        )

    if not field.company_dependent:
        return redistribute(SQL.identifier(field.name))
    return SQL(
        "(SELECT jsonb_object_agg(key, %(expr)s) FROM jsonb_each_text(%(field)s))",
        expr=redistribute(SQL("value::%s", cast_type)),
        field=SQL.identifier(field.name),
    )


def get_field_variation_char(field: Field, postfix: str | SQL | None = None) -> SQL:
    if postfix is None:
        return SQL.identifier(field.name)
    if not isinstance(postfix, SQL):
        postfix = SQL.identifier(postfix)
    if field.translate:
        return SQL(
            """(
            SELECT jsonb_object_agg(key, value || %(postfix)s)
            FROM jsonb_each_text(%(field)s)
        )""",
            field=SQL.identifier(field.name),
            postfix=postfix,
        )
    else:
        return SQL(
            """
            CASE
                WHEN %(field)s IS NULL OR %(field)s IN ('/', '')
                THEN %(field)s
                ELSE %(field)s || %(postfix)s
            END
        """,
            field=SQL.identifier(field.name),
            postfix=postfix,
        )


class PopulateContext:
    def __init__(self) -> None:
        self.has_session_replication_role: bool = True

    @contextmanager
    def ignore_indexes(self, model: Model) -> Generator[None]:
        indexes = model.env.execute_query_dict(
            SQL(
                """
            SELECT indexname AS name, indexdef AS definition
              FROM pg_indexes
             WHERE tablename = %s
               AND schemaname = current_schema
               AND indexname NOT LIKE %s
               AND indexdef NOT LIKE %s
        """,
                model._table,
                "%pkey",
                "%UNIQUE%",
            )
        )
        if indexes:
            _logger.info("Dropping indexes on table %s...", model._table)
            for index in indexes:
                model.env.cr.execute(
                    SQL("DROP INDEX %s CASCADE", SQL.identifier(index["name"]))
                )
            try:
                yield
            finally:
                _logger.info("Adding indexes back on table %s...", model._table)
                for index in indexes:
                    with suppress(Exception):
                        model.env.cr.execute(index["definition"])
        else:
            yield

    @contextmanager
    def ignore_fkey_constraints(self, model: Model) -> Generator[None]:
        if not self.has_session_replication_role:
            yield
            return
        try:
            model.env.cr.execute("SET session_replication_role TO replica")
        except InsufficientPrivilege:
            _logger.warning(
                "Cannot ignore Fkey constraints during insertion due to "
                "insufficient privileges for current pg_role. Retrying without "
                "dropping the FK constraint check; the bulk insertion will be "
                "vastly slower than anticipated."
            )
            model.env.cr.rollback()
            self.has_session_replication_role = False
            yield
            return
        try:
            yield
        finally:
            with suppress(Exception):
                model.env.cr.execute("RESET session_replication_role")


def field_needs_variation(model: Model, field: Field) -> bool:

    def is_unique(model_, field_):
        query = SQL(
            """
        SELECT EXISTS(SELECT 1
              FROM pg_index idx
                   JOIN pg_class t ON t.oid = idx.indrelid
                   JOIN pg_class i ON i.oid = idx.indexrelid
                   JOIN pg_attribute a ON a.attnum = ANY (idx.indkey) AND a.attrelid = t.oid
              WHERE t.relname = %s  -- tablename
                AND a.attname = %s  -- column
                AND t.relnamespace = current_schema::regnamespace
                AND idx.indisunique = TRUE) AS is_unique;
        """,
            model_._table,
            field_.name,
        )
        return model_.env.execute_query(query)[0][0]

    in_names_search = model._rec_names_search and field.name in model._rec_names_search
    in_name = model._rec_name and field.name == model._rec_name
    if (in_name or in_names_search) and field.type != "many2one":
        return True
    if field.type in ("date", "datetime"):
        return True
    if field.index == "trigram":
        return True
    return is_unique(model, field)


def get_field_variation(
    model: Model, field: Field, factor: int, series_alias: str
) -> SQL:
    match field.type:
        case "char" | "text":
            return get_field_variation_char(field, postfix=series_alias)
        case "date" | "datetime":
            return get_field_variation_date(model, field, factor, series_alias)
        case "html":
            return SQL.identifier(field.name)
        case _:
            _logger.warning(
                "The field %s of type %s was marked to be varied, "
                "but no variation branch was found! Defaulting to a raw copy.",
                field,
                field.type,
            )
            return SQL.identifier(field.name)


def fetch_last_id(model: Model) -> int:
    query = SQL(
        "SELECT id FROM %s ORDER BY id DESC LIMIT 1",
        SQL.identifier(model._table),
    )
    return model.env.execute_query(query)[0][0]


def populate_field(
    model: Model,
    field: Field,
    populated: dict[Model, int],
    factors: dict[Model, int],
    table_alias: str = "t",
    series_alias: str = "s",
) -> SQL | None:

    def copy_noop():
        return None

    def copy_raw(field_):
        return SQL.identifier(field_.name)

    def copy(field_):
        if field_needs_variation(model, field_):
            return get_field_variation(model, field_, factors[model], series_alias)
        else:
            return copy_raw(field_)

    def copy_id():
        last_id = fetch_last_id(model)
        populated[model] = last_id
        return SQL(
            "id + %(last_id)s * %(series_alias)s",
            last_id=last_id,
            series_alias=SQL.identifier(series_alias),
        )

    def copy_many2one(field_):
        if (comodel := model.env[field_.comodel_name]) in populated:
            comodel_max_id = populated[comodel]
            return SQL(
                "%(table_alias)s.%(field_name)s + %(comodel_max_id)s * (MOD(%(series_alias)s - 1, %(factor)s) + 1)",
                table_alias=SQL.identifier(table_alias),
                field_name=SQL.identifier(field_.name),
                comodel_max_id=comodel_max_id,
                series_alias=SQL.identifier(series_alias),
                factor=factors[comodel],
            )
        return copy(field_)

    if field.name == "id":
        return copy_id()
    match field.type:
        case "one2many":
            return copy_noop()
        case "many2many":
            return copy_noop()
        case "many2one":
            return copy_many2one(field)
        case "many2one_reference":
            return copy(field)
        case "binary":
            return copy(field) if not field.attachment else copy_noop()
        case _:
            return copy(field)


def populate_model(
    model: Model,
    populated: dict[Any, int],
    factors: dict[Any, int],
    separator_code: str,
) -> None:
    def update_sequence(model_):
        model_.env.execute_query(
            SQL(
                "SELECT SETVAL(%(sequence)s, %(last_id)s, TRUE)",
                sequence=f"{model_._table}_id_seq",
                last_id=fetch_last_id(model_),
            )
        )

    def has_column(field_):
        return field_.is_column

    assert model not in populated, (
        f"We do not populate a model ({model}) that has already been populated."
    )
    _logger.info("Populating model %s %s times...", model._name, factors[model])
    dest_fields = []
    src_fields = []
    update_fields = []
    table_alias = "t"
    series_alias = "s"
    for _, field in sorted(model._fields.items(), key=lambda pair: pair[0] != "id"):
        if has_column(field):
            if field_needs_variation(model, field) and field.type in (
                "char",
                "text",
            ):
                update_fields.append(field)
            if src := populate_field(
                model, field, populated, factors, table_alias, series_alias
            ):
                dest_fields.append(SQL.identifier(field.name))
                src_fields.append(src)
    if update_fields:
        _logger.warning(
            "Renaming existing %s records to keep varied fields unique (%s): "
            "populate modifies original rows, not only the copies.",
            model._name,
            ", ".join(field.name for field in update_fields),
        )
        query = SQL(
            "UPDATE %(table)s SET (%(src_columns)s) = ROW(%(dest_columns)s)",
            table=SQL.identifier(model._table),
            src_columns=SQL(", ").join(
                SQL.identifier(field.name) for field in update_fields
            ),
            dest_columns=SQL(", ").join(
                get_field_variation_char(field, postfix=SQL("CHR(%s)", separator_code))
                for field in update_fields
            ),
        )
        model.env.cr.execute(query)
    query = SQL(
        """
        INSERT INTO %(table)s (%(dest_columns)s)
        SELECT %(src_columns)s FROM %(table)s %(table_alias)s,
        GENERATE_SERIES(1, %(factor)s) %(series_alias)s
    """,
        table=SQL.identifier(model._table),
        factor=factors[model],
        dest_columns=SQL(", ").join(dest_fields),
        src_columns=SQL(", ").join(src_fields),
        table_alias=SQL.identifier(table_alias),
        series_alias=SQL.identifier(series_alias),
    )
    model.env.cr.execute(query)
    if populated[model]:
        update_sequence(model)


class Many2oneFieldWrapper(Many2one):
    def __init__(self, model: Any, field_name: str, comodel_name: str) -> None:
        super().__init__(comodel_name)
        self._setup_attrs__(model, field_name)


class Many2manyModelWrapper:
    def __init__(self, env: Environment, field: Field) -> None:
        self._name = field.relation
        self._table = field.relation
        self._inherits = {}
        self.env = env
        self._rec_name = None
        self._rec_names_search = []
        column1 = field.column1 or field.base_field.column1
        column2 = field.column2 or field.base_field.column2
        self._fields = {
            column1: Many2oneFieldWrapper(self, column1, field.model_name),
            column2: Many2oneFieldWrapper(self, column2, field.comodel_name),
        }

    def __repr__(self) -> str:
        return f"<Many2manyModelWrapper({self._name!r})>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Many2manyModelWrapper) and self._name == other._name

    def __hash__(self) -> int:
        return hash(self._name)


def infer_many2many_model(
    env: Environment, field: Field
) -> Model | Many2manyModelWrapper:
    for model_name, model_class in env.registry.items():
        if model_class._table == field.relation:
            return env[model_name]
    return Many2manyModelWrapper(env, field)


def populate_models(model_factors: dict[Any, int], separator_code: int) -> None:

    def has_records(model_):
        query = SQL("SELECT EXISTS (SELECT 1 FROM %s)", SQL.identifier(model_._table))
        return model_.env.execute_query(query)[0][0]

    populated: dict[Model, int] = defaultdict(int)
    ctx: PopulateContext = PopulateContext()

    def process(model_):
        if model_ in populated:
            return
        if not has_records(model_):
            populated[model_] = 0
            return

        for model_name in model_._inherits:
            delegated = model_.env[model_name]
            model_factors.setdefault(delegated, model_factors[model_])
            process(delegated)

        with ctx.ignore_fkey_constraints(model_), ctx.ignore_indexes(model_):
            populate_model(model_, populated, model_factors, separator_code)

        for field in model_._fields.values():
            if field.store and field.copy:
                match field.type:
                    case "one2many":
                        comodel = model_.env[field.comodel_name]
                        if comodel != model_:
                            model_factors[comodel] = model_factors[model_]
                            process(comodel)
                    case "many2many":
                        m2m_model = infer_many2many_model(model_.env, field)
                        model_factors[m2m_model] = model_factors[model_]
                        process(m2m_model)

    for model in list(model_factors):
        process(model)
