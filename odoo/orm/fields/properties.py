import ast
import contextlib
import json
import typing
import uuid
from collections import abc, defaultdict
from operator import attrgetter
from typing import override

from psycopg.types.json import Json as PsycopgJson

from odoo.exceptions import AccessError, MissingError, UserError
from odoo.libs.json import fast_clone
from odoo.tools import SQL, OrderedSet, html_sanitize, is_list_of
from odoo.tools.misc import frozendict, has_list_types

from .._recordset import is_recordset
from ..domain import Domain
from ..parsing import parse_field_expr
from ..primitives import COLLECTION_TYPES, SQL_OPERATORS
from ..validation import regex_alphanumeric
from .base import Field, _logger

if typing.TYPE_CHECKING:
    from odoo.tools import Query

    from .._typing import ModelLike
    from ..models import BaseModel

NoneType = type(None)


def check_property_field_value_name(property_name: str) -> None:
    if not (0 < len(property_name) <= 512) or not regex_alphanumeric.fullmatch(
        property_name
    ):
        raise ValueError(f"Wrong property field value name {property_name!r}.")


RELATIONAL_PROPERTY_TYPES = frozenset(("many2one", "many2many"))


class Properties(Field):
    type = "properties"
    cache_truthiness_matches = False
    """Not even the truthiness. ``convert_to_record`` returns a ``Property``,
    an ``abc.Mapping`` whose ``__len__`` counts the properties the *definition*
    declares -- not the entries in the cached values dict. A record still
    holding values for a definition that has since been emptied caches a
    truthy dict and reads back a falsy ``Property``, so ``filtered(fname)``
    kept records that ``filtered(lambda r: r[fname])`` dropped."""
    is_properties = True
    _column_type = ("jsonb", "jsonb")
    copy = False
    prefetch = False
    write_sequence = 10

    store = True
    readonly = False
    precompute = True

    definition = None
    definition_record = None
    definition_record_field = None

    _description_definition_record = property(attrgetter("definition_record"))
    _description_definition_record_field = property(
        attrgetter("definition_record_field")
    )

    HTML_SANITIZE_OPTIONS = {
        "sanitize_attributes": True,
        "sanitize_tags": True,
        "sanitize_style": False,
        "sanitize_form": True,
        "sanitize_conditional_comments": True,
        "strip_style": False,
        "strip_classes": False,
    }

    ALLOWED_TYPES = (
        "boolean",
        "integer",
        "float",
        "text",
        "char",
        "html",
        "date",
        "datetime",
        "monetary",
        "many2one",
        "many2many",
        "selection",
        "tags",
        "separator",
    )

    @override
    def _setup_attrs__(self, model_class: type[BaseModel], name: str) -> None:
        super()._setup_attrs__(model_class, name)
        self._setup_definition_attrs(model_class)

    def _setup_definition_attrs(self, model_class: type[BaseModel]) -> None:
        if self.definition:
            assert self.definition.count(".") == 1
            self.definition_record, self.definition_record_field = (
                self.definition.rsplit(".", 1)
            )

            if not self.inherited_field:
                self._depends = (self.definition_record,)
                self.compute = self._compute

    @override
    def setup_related(self, model: BaseModel) -> None:
        super().setup_related(model)
        if self.inherited_field and not self.definition:
            self.definition = self.inherited_field.definition
            self._setup_definition_attrs(model)

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> typing.Any:
        if not value:
            return None

        value = self.convert_to_cache(value, record, validate=validate)
        return PsycopgJson(value)

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> dict[str, typing.Any] | None:
        if not value:
            return None

        if isinstance(value, Property):
            value = value._values

        elif isinstance(value, dict):
            value = fast_clone(self._recordsets_to_ids(value, record))

        elif isinstance(value, str):
            value = json.loads(value)
            if not isinstance(value, dict):
                raise ValueError(f"Wrong property value {value!r}")

        elif isinstance(value, list):
            self._remove_display_name(value)
            value = self._list_to_dict(value)

        else:
            raise TypeError(f"Wrong property type {type(value)!r}")

        if validate:
            for property_name, property_value in value.items():
                if property_name.endswith("_html"):
                    value[property_name] = html_sanitize(
                        property_value,
                        **self.HTML_SANITIZE_OPTIONS,
                    )

        return value

    def _recordsets_to_ids(
        self, values: dict[str, typing.Any], record: ModelLike
    ) -> dict[str, typing.Any]:
        if not any(is_recordset(value) for value in values.values()):
            return values

        types_by_name: dict[str, str] = {}
        with contextlib.suppress(AccessError, MissingError, ValueError):
            for definition in self._get_properties_definition(record) or ():
                if definition.get("name"):
                    types_by_name[definition["name"]] = definition.get("type")

        converted = dict(values)
        for name, value in values.items():
            if not is_recordset(value):
                continue
            property_type = types_by_name.get(name)
            if property_type == "many2one":
                converted[name] = value.id
            elif property_type == "many2many":
                converted[name] = value.ids
            else:
                raise ValueError(
                    f"Cannot store a recordset in property {name!r} of "
                    f"{self}: its definition declares "
                    f"{property_type or 'no relational type'}"
                )
        return converted

    @override
    def convert_to_record(self, value: typing.Any, record: ModelLike) -> Property:
        return Property(value or {}, self, record)

    @override
    def convert_to_read(
        self, value: typing.Any, record: ModelLike, use_display_name: bool = True
    ) -> typing.Any:
        return self.convert_to_read_multi([value], record, use_display_name)[0]

    def convert_to_read_multi(
        self,
        values: list[typing.Any],
        records: ModelLike,
        use_display_name: bool = True,
    ) -> list[typing.Any]:
        if not records:
            return values
        if len(values) != len(records):
            raise ValueError(
                f"convert_to_read_multi: expected {len(records)} values, got {len(values)}"
            )

        result = []
        for record, value in zip(records, values, strict=True):
            value = value._values if isinstance(value, Property) else value
            if definition := self._get_properties_definition(record):
                value = value or {}
                assert isinstance(value, dict), f"Wrong type {value!r}"
                result.append(self._dict_to_list(value, definition))
            else:
                result.append([])

        res_ids_per_model = self._get_res_ids_per_model(records.env, result)

        for value in result:
            self._parse_json_types(value, records.env, res_ids_per_model)

        if use_display_name:
            for value in result:
                self._add_display_name(value, records.env)

        return result

    @override
    def convert_to_write(self, value: typing.Any, record: ModelLike) -> typing.Any:
        return value

    @override
    def convert_to_export(self, value: typing.Any, record: ModelLike) -> typing.Any:
        if isinstance(value, Property):
            value = value._values
        return value or ""

    def _get_res_ids_per_model(
        self, env: typing.Any, values_list: list[typing.Any]
    ) -> dict[str, set[int]]:
        ids_per_model = defaultdict(OrderedSet)

        for record_values in values_list:
            for property_definition in record_values:
                comodel = property_definition.get("comodel")
                type_ = property_definition.get("type")
                property_value = property_definition.get("value") or []
                default = property_definition.get("default") or []

                if type_ not in RELATIONAL_PROPERTY_TYPES or comodel not in env:
                    continue

                if type_ == "many2one":
                    default = [default] if default else []
                    property_value = (
                        [property_value] if isinstance(property_value, int) else []
                    )
                elif not is_list_of(property_value, int):
                    property_value = []

                ids_per_model[comodel].update(default)
                ids_per_model[comodel].update(property_value)

        res_ids_per_model = {}
        for model, ids in ids_per_model.items():
            recs = env[model].browse(ids).exists()
            res_ids_per_model[model] = set(recs.ids)

            for record in recs:
                with contextlib.suppress(AccessError):
                    record.display_name  # noqa: B018

        return res_ids_per_model

    @override
    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        if isinstance(value, str):
            value = json.loads(value)

        if isinstance(value, Property):
            value = value._values

        if len(records[self.definition_record]) > 1 and value:
            raise UserError(
                records.env._(
                    "Updating records with different property fields definitions is not supported. Update by separate definition instead."
                )
            )

        if isinstance(value, dict):
            return super().mark_dirty(records, value)

        definition_changed = any(
            definition.get("definition_changed") or definition.get("definition_deleted")
            for definition in (value or [])
        )
        if definition_changed:
            value = [
                definition
                for definition in value
                if not definition.get("definition_deleted")
            ]
            for definition in value:
                definition.pop("definition_changed", None)

            container = records[self.definition_record]
            if container:
                properties_definition = fast_clone(value)
                for property_definition in properties_definition:
                    property_definition.pop("value", None)
                container[self.definition_record_field] = properties_definition

                _logger.info(
                    "Properties field: User #%i changed definition of %r",
                    records.env.user.id,
                    container,
                )

        return super().mark_dirty(records, value)

    def _compute(self, records: BaseModel) -> None:
        for record in records.sudo():
            record[self.name] = self._add_default_values(
                record.env,
                {
                    self.name: record[self.name],
                    self.definition_record: record[self.definition_record],
                },
            )

    def _add_default_values(
        self, env: typing.Any, values: dict[str, typing.Any]
    ) -> list[typing.Any] | dict[str, typing.Any]:
        properties_values = values.get(self.name) or {}

        if isinstance(properties_values, Property):
            properties_values = properties_values._values

        if not values.get(self.definition_record):
            return {}

        container_id = values[self.definition_record]
        if not isinstance(container_id, int) and not hasattr(container_id, "_ids"):
            raise ValueError(f"Wrong container value {container_id!r}")

        if isinstance(container_id, int):
            current_model = env[self.model_name]
            definition_record_field = current_model._fields[self.definition_record]
            container_model_name = definition_record_field.comodel_name
            container_id = env[container_model_name].sudo().browse(container_id)

        properties_definition = container_id[self.definition_record_field]
        if not (
            properties_definition
            or (
                isinstance(properties_values, list)
                and any(d.get("definition_changed") for d in properties_values)
            )
        ):
            return {}

        assert isinstance(properties_values, (list, dict))
        if isinstance(properties_values, list):
            self._remove_display_name(properties_values)
            properties_list_values = properties_values
        else:
            properties_list_values = self._dict_to_list(
                properties_values, properties_definition
            )

        for properties_value in properties_list_values:
            if properties_value.get("value") is None:
                property_name = properties_value.get("name")
                context_key = f"default_{self.name}.{property_name}"
                if property_name and context_key in env.context:
                    default = env.context[context_key]
                else:
                    default = properties_value.get("default")
                if default:
                    properties_value["value"] = default

        return properties_list_values

    def _get_properties_definition(
        self, record: ModelLike
    ) -> list[dict[str, typing.Any]] | None:
        assert self.definition_record is not None
        container = record[self.definition_record]
        if container:
            return container.sudo()[self.definition_record_field]
        return None

    @classmethod
    def _add_display_name(
        cls,
        values_list: list[dict[str, typing.Any]],
        env: typing.Any,
        value_keys: tuple[str, ...] = ("value", "default"),
    ) -> None:
        for property_definition in values_list:
            property_type = property_definition.get("type")
            property_model = property_definition.get("comodel")
            if not property_model:
                continue

            for value_key in value_keys:
                property_value = property_definition.get(value_key)

                if (
                    property_type == "many2one"
                    and property_value
                    and isinstance(property_value, int)
                ):
                    try:
                        display_name = (
                            env[property_model].browse(property_value).display_name
                        )
                        property_definition[value_key] = (
                            property_value,
                            display_name,
                        )
                    except AccessError:
                        property_definition[value_key] = (property_value, None)
                    except MissingError:
                        property_definition[value_key] = False

                elif (
                    property_type == "many2many"
                    and property_value
                    and is_list_of(property_value, int)
                ):
                    property_definition[value_key] = []
                    records = env[property_model].browse(property_value)
                    for record in records:
                        try:
                            property_definition[value_key].append(
                                (record.id, record.display_name)
                            )
                        except AccessError:
                            property_definition[value_key].append((record.id, None))
                        except MissingError:
                            continue

    @classmethod
    def _remove_display_name(
        cls,
        values_list: list[dict[str, typing.Any]],
        value_key: str = "value",
    ) -> None:
        for property_definition in values_list:
            if not isinstance(property_definition, dict) or not property_definition.get(
                "name"
            ):
                continue

            property_value = property_definition.get(value_key)
            if not property_value:
                continue

            property_type = property_definition.get("type")

            if property_type == "many2one" and has_list_types(
                property_value, [int, (str, NoneType)]
            ):
                property_definition[value_key] = property_value[0]

            elif property_type == "many2many":
                if is_list_of(property_value, (list, tuple)):
                    property_definition[value_key] = [
                        many2many_value[0] for many2many_value in property_value
                    ]

    @classmethod
    def _add_missing_names(cls, values_list: list[dict[str, typing.Any]]) -> None:
        for definition in values_list:
            if definition.get("definition_changed") and not definition.get("name"):
                definition["name"] = str(uuid.uuid4()).replace("-", "")[:16]

    @classmethod
    def _parse_json_types(
        cls,
        values_list: list[dict[str, typing.Any]],
        env: typing.Any,
        res_ids_per_model: dict[str, set[int]],
    ) -> None:
        for property_definition in values_list:
            property_value = property_definition.get("value")
            property_type = property_definition.get("type")
            res_model = property_definition.get("comodel")

            if property_type not in cls.ALLOWED_TYPES:
                raise ValueError(f"Wrong property type {property_type!r}")

            if property_value is None:
                continue

            if property_type == "boolean":
                property_value = bool(property_value)

            elif property_type in ("char", "text") and not isinstance(
                property_value, str
            ):
                property_value = False

            elif property_value and property_type == "selection":
                options = property_definition.get("selection") or []
                options = {option[0] for option in options if option or ()}
                if property_value not in options:
                    property_value = False

            elif property_value and property_type == "tags":
                all_tags = {tag[0] for tag in property_definition.get("tags") or ()}
                property_value = [tag for tag in property_value if tag in all_tags]

            elif property_type == "many2one":
                if (
                    not isinstance(property_value, int)
                    or res_model not in env
                    or property_value not in res_ids_per_model[res_model]
                ):
                    property_value = False

            elif property_type == "many2many":
                if not is_list_of(property_value, int):
                    property_value = []

                elif len(property_value) != len(set(property_value)):
                    property_value = list(dict.fromkeys(property_value))

                property_value = (
                    [
                        id_
                        for id_ in property_value
                        if id_ in res_ids_per_model[res_model]
                    ]
                    if res_model in env
                    else []
                )

            elif property_type == "html":
                property_value = (
                    property_definition["name"].endswith("_html") and property_value
                )

            property_definition["value"] = property_value

    @classmethod
    def _list_to_dict(
        cls, values_list: list[dict[str, typing.Any]]
    ) -> dict[str, typing.Any]:
        if not is_list_of(values_list, dict):
            raise ValueError(f"Wrong properties value {values_list!r}")

        cls._add_missing_names(values_list)

        dict_value = {}
        for property_definition in values_list:
            property_value = property_definition.get("value")
            property_type = property_definition.get("type")
            property_model = property_definition.get("comodel")
            if property_value is None:
                continue

            if is_recordset(property_value):
                property_value = (
                    property_value.id
                    if property_type == "many2one"
                    else property_value.ids
                )
            if property_type not in ("integer", "float") or property_value != 0:
                property_value = property_value or False
            if (
                property_type in RELATIONAL_PROPERTY_TYPES
                and property_model
                and property_value
            ):
                if (
                    property_type == "many2many"
                    and property_value
                    and not is_list_of(property_value, int)
                ):
                    raise ValueError(f"Wrong many2many value {property_value!r}")

                if property_type == "many2one" and not isinstance(property_value, int):
                    raise ValueError(f"Wrong many2one value {property_value!r}")

            dict_value[property_definition["name"]] = property_value

        return dict_value

    @classmethod
    def _dict_to_list(
        cls,
        values_dict: dict[str, typing.Any],
        properties_definition: list[dict[str, typing.Any]],
    ) -> list[dict[str, typing.Any]]:
        if not is_list_of(properties_definition, dict):
            raise ValueError(f"Wrong properties value {properties_definition!r}")

        values_list = fast_clone(properties_definition)
        for property_definition in values_list:
            if property_definition["name"] in values_dict:
                property_definition["value"] = values_dict[property_definition["name"]]
            else:
                property_definition.pop("value", None)
        return values_list

    @override
    def expression_getter(self, field_expr: str) -> typing.Any:
        _fname, property_name = parse_field_expr(field_expr)
        if not property_name:
            raise ValueError(f"Missing property name for {self}")

        def get_property(record: BaseModel) -> typing.Any:
            property_value = self.__get__(
                record.with_context(property_selection_get_key=True)
            )
            value = property_value.get(property_name)
            if value:
                return value
            for definition in self._get_properties_definition(record) or ():
                if definition.get("name") == property_name:
                    break
            else:
                return value or False

            if not value and definition["type"] in RELATIONAL_PROPERTY_TYPES:
                return record.env.get(definition.get("comodel"))
            return value

        return get_property

    @override
    def filter_function(
        self, records: BaseModel, field_expr: str, operator: str, value: typing.Any
    ) -> typing.Any:
        getter = self.expression_getter(field_expr)
        domain = None
        if operator == "any" or isinstance(value, Domain):
            domain = Domain(value).optimize(records)
        elif (
            operator == "in"
            and isinstance(value, COLLECTION_TYPES)
            and hasattr(getter(records[:1]), "_ids")
        ):
            domain = Domain("id", "in", value).optimize(records)
        if domain is not None:
            return lambda rec: getter(rec).filtered_domain(domain)

        match = super().filter_function(records, field_expr, operator, value)
        if operator != "in" or not isinstance(value, COLLECTION_TYPES):
            return match

        value_set = value if isinstance(value, abc.Set) else set(value)
        match_empty = False in value_set or self.falsy_value in value_set

        def match_collection(rec):
            rec_value = getter(rec)
            if type(rec_value) is not list:
                return match(rec)
            return match_empty if not rec_value else not value_set.isdisjoint(rec_value)

        return match_collection

    def property_to_sql(
        self,
        field_sql: SQL,
        property_name: str,
        model: ModelLike,
        alias: str,
        query: Query,
    ) -> SQL:
        check_property_field_value_name(property_name)
        return SQL("(%s -> %s)", field_sql, property_name)

    @override
    def condition_to_sql(
        self,
        field_expr: str,
        operator: str,
        value: typing.Any,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        fname, property_name = parse_field_expr(field_expr)
        if not property_name:
            raise ValueError(f"Missing property name for {self}")
        raw_sql_field = model._field_to_sql(alias, fname, query)
        sql_left = model._field_to_sql(alias, field_expr, query)

        if operator in ("in", "not in"):
            assert isinstance(value, COLLECTION_TYPES)
            if len(value) == 1 and any(v is True for v in value):
                check_null_op_false = "!=" if operator == "in" else "="
                value = []
                operator = "in" if operator == "not in" else "not in"
            elif any(v is False for v in value):
                check_null_op_false = "=" if operator == "in" else "!="
                value = [v for v in value if v is not False]
            else:
                value = list(value)
                check_null_op_false = None

            sqls = []
            if check_null_op_false:
                sqls.append(
                    SQL(
                        "%s%s'false'::jsonb",
                        sql_left,
                        SQL_OPERATORS[check_null_op_false],
                    )
                )
                if check_null_op_false == "=":
                    sqls.extend(
                        (
                            SQL("%s IS NULL", raw_sql_field),
                            SQL("NOT (%s ? %s)", raw_sql_field, property_name),
                        )
                    )
            for one_value in value:
                sql_value = SQL("%s", json.dumps(one_value))
                sql_array = SQL("%s", json.dumps([one_value]))
                if operator == "in":
                    sqls.append(
                        SQL(
                            "(%s = %s OR %s @> %s)",
                            sql_left,
                            sql_value,
                            sql_left,
                            sql_array,
                        )
                    )
                else:
                    sqls.append(
                        SQL(
                            "(%s != %s AND NOT %s @> %s)",
                            sql_left,
                            sql_value,
                            sql_left,
                            sql_array,
                        )
                    )
            assert sqls, "No SQL generated for property"
            if len(sqls) == 1:
                return sqls[0]
            combine_sql = SQL(" OR ") if operator == "in" else SQL(" AND ")
            return SQL("(%s)", combine_sql.join(sqls))

        def unaccent(x):
            return x

        if operator.endswith("like"):
            if operator.endswith("ilike"):
                unaccent = model.env.registry.unaccent
            if "=" in operator:
                value = str(value)
            else:
                value = f"%{value}%"

        try:
            sql_operator = SQL_OPERATORS[operator]
        except KeyError:
            raise ValueError(f"Invalid operator {operator} for Properties") from None

        if isinstance(value, str):
            sql_left = SQL("(%s ->> %s)", raw_sql_field, property_name)
            sql_right = SQL("%s", value)
            sql = SQL(
                "%s%s%s",
                unaccent(sql_left),
                sql_operator,
                unaccent(sql_right),
            )
            if operator in Domain.NEGATIVE_OPERATORS:
                sql = SQL("(%s OR %s IS NULL)", sql, sql_left)
            return sql

        sql_right = SQL("%s", json.dumps(value))
        return SQL(
            "%s%s%s",
            unaccent(sql_left),
            sql_operator,
            unaccent(sql_right),
        )


class Property(abc.Mapping):
    def __init__(
        self,
        values: dict[str, typing.Any],
        field: Properties,
        record: ModelLike,
    ) -> None:
        self._values = values
        self.record = record
        self.field = field
        self._definitions_by_name: dict[str, typing.Any] | None = None

    def _definitions(self) -> dict[str, typing.Any]:
        index = self._definitions_by_name
        if index is None:
            values = self.field.convert_to_read(
                self._values,
                self.record,
                use_display_name=False,
            )
            index = self._definitions_by_name = {prop["name"]: prop for prop in values}
        return index

    def __iter__(self) -> typing.Iterator[str]:
        if not self.record:
            yield from self._values
            return
        definitions = self._definitions()
        for key in self._values:
            if key in definitions:
                yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __eq__(self, other: object) -> bool:
        return self._values == (other._values if isinstance(other, Property) else other)

    def __getitem__(self, property_name: str) -> typing.Any:
        if not self.record:
            return False

        prop = self._definitions().get(property_name)
        if not prop:
            raise KeyError(property_name)

        if prop.get("type") in RELATIONAL_PROPERTY_TYPES and prop.get("comodel"):
            return self.record.env[prop.get("comodel")].browse(prop.get("value"))

        if prop.get("type") == "selection" and prop.get("value"):
            if self.record.env.context.get("property_selection_get_key"):
                return next(
                    (
                        sel[0]
                        for sel in prop.get("selection")
                        if sel[0] == prop["value"]
                    ),
                    False,
                )
            return next(
                (sel[1] for sel in prop.get("selection") if sel[0] == prop["value"]),
                False,
            )

        if prop.get("type") == "tags" and prop.get("value"):
            tags = prop.get("tags") or ()
            if self.record.env.context.get("property_selection_get_key"):
                return [tag[0] for tag in tags if tag[0] in prop["value"]]
            return ", ".join(tag[1] for tag in tags if tag[0] in prop["value"])

        value = prop.get("value")
        if prop.get("type") not in ("integer", "float") or value != 0:
            value = value or False
        return value

    def __hash__(self) -> int:
        return hash(
            frozendict(
                {
                    name: tuple(value) if isinstance(value, list) else value
                    for name, value in self._values.items()
                }
            )
        )


class PropertiesDefinition(Field):
    type = "properties_definition"
    cache_truthiness_matches = False
    """Not even the truthiness. ``convert_to_record`` drops every definition
    entry whose ``name`` or ``type`` is falsy, so a non-empty cached list can
    read back as ``[]``. The validator now refuses to *write* such an entry,
    but the column can still hold one written before that or by SQL, and the
    reader is the authority on what the field is worth."""
    _column_type = ("jsonb", "jsonb")
    copy = True
    readonly = False
    prefetch = True

    REQUIRED_KEYS = ("name", "type")
    ALLOWED_KEYS = (
        "name",
        "string",
        "type",
        "comodel",
        "default",
        "suffix",
        "selection",
        "tags",
        "domain",
        "view_in_cards",
        "fold_by_default",
        "currency_field",
    )
    PROPERTY_PARAMETERS_MAP = {
        "comodel": RELATIONAL_PROPERTY_TYPES,
        "currency_field": {"monetary"},
        "domain": RELATIONAL_PROPERTY_TYPES,
        "selection": {"selection"},
        "tags": {"tags"},
    }

    @override
    def convert_to_column(
        self,
        value: typing.Any,
        record: ModelLike,
        values: dict[str, typing.Any] | None = None,
        validate: bool = True,
    ) -> typing.Any:
        if not value:
            return None

        if isinstance(value, str):
            value = json.loads(value)

        if not isinstance(value, list):
            raise TypeError(f"Wrong properties definition type {type(value)!r}")

        if validate:
            Properties._remove_display_name(value, value_key="default")

            self._validate_properties_definition(value, record.env)

        return PsycopgJson(record._convert_to_column_properties_definition(value))

    @override
    def convert_to_cache(
        self, value: typing.Any, record: ModelLike, validate: bool = True
    ) -> list[dict[str, typing.Any]] | None:
        if not value:
            return None

        if isinstance(value, list):
            value = json.dumps(value)

        if isinstance(value, str):
            value = json.loads(value)

        if not isinstance(value, list):
            raise TypeError(f"Wrong properties definition type {type(value)!r}")

        if validate:
            Properties._remove_display_name(value, value_key="default")

            self._validate_properties_definition(value, record.env)

        return record._convert_to_cache_properties_definition(value)

    @override
    def convert_to_record(
        self, value: typing.Any, record: ModelLike
    ) -> list[dict[str, typing.Any]]:
        if not value:
            return []

        result = []

        for property_definition in value:
            if not all(property_definition.get(key) for key in self.REQUIRED_KEYS):
                continue

            property_definition = fast_clone(property_definition)

            type_ = property_definition.get("type")

            if type_ in RELATIONAL_PROPERTY_TYPES:
                property_model = property_definition.get("comodel")
                if property_model not in record.env:
                    property_definition["comodel"] = False
                    property_definition.pop("domain", None)
                elif property_domain := property_definition.get("domain"):
                    if len(property_domain) > 8192:
                        del property_definition["domain"]
                    else:
                        try:
                            dom = Domain(ast.literal_eval(property_domain))
                            model = record.env[property_model]
                            dom.validate(model)
                        except ValueError, SyntaxError, MemoryError:
                            del property_definition["domain"]

            elif type_ in ("selection", "tags"):
                property_definition[type_] = property_definition.get(type_) or []

            result.append(property_definition)

        return result

    @override
    def convert_to_read(
        self, value: typing.Any, record: ModelLike, use_display_name: bool = True
    ) -> typing.Any:
        if not value:
            return value

        if use_display_name:
            Properties._add_display_name(value, record.env, value_keys=("default",))

        return value

    @override
    def convert_to_write(self, value: typing.Any, record: ModelLike) -> typing.Any:
        return value

    def _validate_properties_definition(
        self, properties_definition: list[dict[str, typing.Any]], env: typing.Any
    ) -> None:
        allowed_keys = (
            self.ALLOWED_KEYS
            + env["base"]._additional_allowed_keys_properties_definition()
        )
        allowed_keys_set = set(allowed_keys)

        env["base"]._validate_properties_definition(properties_definition, self)

        properties_names = set()
        param_map_items = self.PROPERTY_PARAMETERS_MAP.items()

        for property_definition in properties_definition:
            for (
                property_parameter,
                allowed_types,
            ) in param_map_items:
                if (
                    property_definition.get("type") not in allowed_types
                    and property_parameter in property_definition
                ):
                    raise ValueError(
                        f"Invalid property parameter {property_parameter!r}"
                    )

            property_definition_keys = set(property_definition.keys())

            invalid_keys = property_definition_keys - allowed_keys_set
            if invalid_keys:
                raise ValueError(
                    "Some key are not allowed for a properties definition [%s]."
                    % ", ".join(invalid_keys),
                )

            # Truthiness, not presence, and *before* the name is read. This is
            # the exact test convert_to_record applies when it decides which
            # definitions to hand back (`all(definition.get(key) for key in
            # REQUIRED_KEYS)`), so a definition this method accepts is one that
            # method returns. Checking presence let ``{"name": "a", "type": ""}``
            # through: it was stored, and every later read returned ``[]``,
            # because "" is present but falsy. The name half was already checked
            # for truthiness below and the type half was not, which is why an
            # empty name was refused and an empty type was not.
            missing_keys = [
                key for key in self.REQUIRED_KEYS if not property_definition.get(key)
            ]
            if missing_keys:
                raise ValueError(
                    "Some keys are missing or empty for a properties definition [%s]."
                    % ", ".join(missing_keys),
                )

            check_property_field_value_name(property_definition["name"])

            property_type = property_definition["type"]
            property_name = property_definition["name"]
            if property_name in properties_names:
                raise ValueError(f"The property name {property_name!r} is duplicated.")
            properties_names.add(property_name)

            if property_type == "html" and not property_name.endswith("_html"):
                msg = "HTML property name should end with `_html`."
                raise ValueError(msg)

            if property_type != "html" and property_name.endswith("_html"):
                msg = "Only HTML properties can have the `_html` suffix."
                raise ValueError(msg)

            if property_type not in Properties.ALLOWED_TYPES:
                raise ValueError(f"Wrong property type {property_type!r}.")

            if property_type == "html" and (
                default := property_definition.get("default")
            ):
                property_definition["default"] = html_sanitize(
                    default, **Properties.HTML_SANITIZE_OPTIONS
                )

            model = property_definition.get("comodel")
            if model and (
                model not in env or env[model].is_transient() or env[model]._abstract
            ):
                raise ValueError(f"Invalid model name {model!r}")

            property_selection = property_definition.get("selection")
            if property_selection:
                if not is_list_of(property_selection, (list, tuple)) or not all(
                    len(selection) == 2 for selection in property_selection
                ):
                    raise ValueError(f"Wrong options {property_selection!r}.")

                all_options = [option[0] for option in property_selection]
                if len(all_options) != len(set(all_options)):
                    duplicated = set(
                        filter(lambda x: all_options.count(x) > 1, all_options)
                    )
                    raise ValueError(
                        f"Some options are duplicated: {', '.join(duplicated)}."
                    )

            property_tags = property_definition.get("tags")
            if property_tags:
                if not is_list_of(property_tags, (list, tuple)) or not all(
                    len(tag) == 3 and isinstance(tag[2], int) for tag in property_tags
                ):
                    raise ValueError(f"Wrong tags definition {property_tags!r}.")

                all_tags = [tag[0] for tag in property_tags]
                if len(all_tags) != len(set(all_tags)):
                    duplicated = set(filter(lambda x: all_tags.count(x) > 1, all_tags))
                    raise ValueError(
                        f"Some tags are duplicated: {', '.join(duplicated)}."
                    )
