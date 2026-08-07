import contextlib
import functools
import itertools
import logging
import math
from collections.abc import Callable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, NamedTuple

import psycopg

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.libs.datetime import utc
from odoo.libs.json import loads as json_loads
from odoo.tools import SQL, OrderedSet
from odoo.tools.translate import LazyTranslate, code_translations

_logger = logging.getLogger(__name__)
_lt = LazyTranslate(__name__)

REFERENCING_FIELDS = frozenset({None, "id", ".id"})

DATE_LENGTH = 10


def only_ref_fields(record: dict[str | None, Any]) -> dict[str | None, Any]:
    return {k: v for k, v in record.items() if k in REFERENCING_FIELDS}


def exclude_ref_fields(record: dict[str | None, Any]) -> dict[str | None, Any]:
    return {k: v for k, v in record.items() if k not in REFERENCING_FIELDS}


def escape_import_message(text: str) -> str:
    return text.replace("%", "%%")


BOOLEAN_TRANSLATIONS = (_lt("yes"), _lt("no"), _lt("true"), _lt("false"))


class ImportPolicy(StrEnum):
    REPORT = "report"
    SKIP_RECORD = "import_skip_records"
    SET_EMPTY = "import_set_empty_fields"


class FakeField(NamedTuple):
    comodel_name: str | None
    name: str


type FieldLike = fields.Field | FakeField
type Converter = Callable[[Any], tuple[Any, list]]
type RecordConverter = Callable[[dict, Callable], dict]


class RefLookup(NamedTuple):
    id: int | bool | None
    field_type: str
    error_msg: str
    warnings: list


class OdooImportWarning(Warning):
    pass


class ImportReferenceNotFound(ValueError):
    pass


class IrFieldsConverter(models.AbstractModel):
    _name = "ir.fields.converter"
    _description = "Fields Converter"

    @api.model
    def _format_import_error(
        self,
        error_type: type[Exception],
        error_msg: str,
        error_params: str | dict[str, Any] | tuple = (),
        error_args: dict[str, Any] | None = None,
    ) -> Exception:

        def sanitize(p: Any) -> str:
            return escape_import_message(str(p))

        if error_params:
            match error_params:
                case str():
                    error_params = sanitize(error_params)
                case dict():
                    error_params = {k: sanitize(v) for k, v in error_params.items()}
                case tuple():
                    error_params = tuple(sanitize(v) for v in error_params)
        return error_type(error_msg % error_params, error_args or {})

    @api.model
    def _import_policy_path(self, field: FieldLike) -> str:
        return "/".join(
            self.env.context.get("parent_fields_hierarchy", []) + [field.name]
        )

    @api.model
    def _import_policy_lists(self) -> tuple[Sequence[str], Sequence[str]]:
        context = self.env.context
        if not context.get("import_file"):
            return (), ()
        return (
            context.get("import_skip_records") or (),
            context.get("import_set_empty_fields") or (),
        )

    @api.model
    def _import_field_policy(self, field: FieldLike) -> ImportPolicy:
        path = self._import_policy_path(field)
        skip_records, set_empty_fields = self._import_policy_lists()
        if path in skip_records:
            return ImportPolicy.SKIP_RECORD
        if path in set_empty_fields:
            return ImportPolicy.SET_EMPTY
        return ImportPolicy.REPORT

    @api.model
    def _nested_skip_subfields(self, hierarchy: list[str]) -> set[str]:
        skip_records, _set_empty = self._import_policy_lists()
        prefix = "/".join(hierarchy) + "/"
        return {
            path[len(prefix) :].partition("/")[0]
            for path in skip_records
            if path.startswith(prefix)
        }

    @api.model
    def _error_field_path(self, field: str, value: Any) -> list[str]:
        field_path = [*(self.env.context.get("parent_fields_hierarchy") or []), field]
        while isinstance(value, list) and value:
            record = value[0]
            if not isinstance(record, dict) or not record.keys() <= REFERENCING_FIELDS:
                break
            subfield = next(iter(record))
            if subfield:
                field_path.append(subfield)
            value = record[subfield]
        return field_path

    @api.model
    def for_model(
        self, model: models.BaseModel, fromtype: type | str = str
    ) -> RecordConverter:
        model = self.env[model._name]
        model_fields = model._fields

        converter_cache: dict[str, Converter | None] = {}

        def get_converter(name: str, field: fields.Field) -> Converter | None:
            if name not in converter_cache:
                converter_cache[name] = self.to_field(field, fromtype)
            return converter_cache[name]

        import_file_context = self.env.context.get("import_file")

        def fn(record: dict, log: Callable) -> dict:
            converted = {}
            for fname, value in record.items():
                if fname in REFERENCING_FIELDS:
                    continue
                field = model_fields.get(fname)
                if field is None:
                    log(
                        fname,
                        self._format_import_error(
                            ValueError,
                            self.env._(
                                "Field '%%(field)s' does not exist on model '%s'"
                            ),
                            model._name,
                        ),
                    )
                    continue
                if not value:
                    converted[fname] = False
                    continue
                converter = get_converter(fname, field)
                if converter is None:
                    log(
                        fname,
                        self._format_import_error(
                            ValueError,
                            self.env._(
                                "Field '%%(field)s' cannot be imported (unsupported field type '%s')"
                            ),
                            field.type,
                        ),
                    )
                    continue
                try:
                    converted[fname], ws = converter(value)
                    for w in ws:
                        if isinstance(w, str):
                            w = OdooImportWarning(w)
                        log(fname, w)
                except (
                    UnicodeEncodeError,
                    UnicodeDecodeError,
                    psycopg.DataError,
                ) as e:
                    log(fname, ValueError(escape_import_message(str(e))))
                except ValueError as e:
                    if import_file_context:
                        error_info = e.args[1] if len(e.args) > 1 else None
                        if isinstance(error_info, dict) and not error_info.get(
                            "field_path"
                        ):
                            error_info["field_path"] = self._error_field_path(
                                fname, value
                            )
                    log(fname, e)
                except AttributeError, TypeError:
                    _logger.exception(
                        "Import converter for field %r failed on a %s value",
                        fname,
                        type(value).__name__,
                    )
                    log(
                        fname,
                        self._format_import_error(
                            ValueError,
                            self.env._(
                                "Field '%%(field)s' could not be imported from a "
                                "value of type '%s'; see the server logs for details"
                            ),
                            type(value).__name__,
                        ),
                    )
            return converted

        return fn

    @api.model
    def to_field(
        self, field: fields.Field, fromtype: type | str = str
    ) -> Converter | None:
        if not isinstance(fromtype, (type, str)):
            raise TypeError(
                f"fromtype must be a type or str, got {type(fromtype).__name__}"
            )
        typename = fromtype.__name__ if isinstance(fromtype, type) else fromtype
        converter = getattr(self, f"_{typename}_to_{field.type}", None)
        if not converter:
            return None
        return functools.partial(converter, field)

    @api.model
    def _str_to_json(self, field: FieldLike, value: str) -> tuple[Any, list]:
        try:
            return json_loads(value), []
        except ValueError:
            msg = self.env._(
                "'%s' does not seem to be a valid JSON for field '%%(field)s'"
            )
            raise self._format_import_error(ValueError, msg, value) from None

    @api.model
    def _property_import_error(
        self, msg: str, value: Any, property_dict: dict
    ) -> Exception:
        return self._format_import_error(
            ValueError,
            msg,
            {"value": value, "label_property": property_dict["string"]},
        )

    @api.model
    def _str_to_properties(
        self, field: FieldLike, value: str | list
    ) -> tuple[list, list]:
        if isinstance(value, str):
            try:
                value = json_loads(value)
            except ValueError:
                msg = self.env._(
                    "Unable to import '%%(field)s' Properties field as a whole, target individual property instead."
                )
                raise self._format_import_error(ValueError, msg) from None

        if not isinstance(value, list):
            msg = self.env._(
                "Unable to import '%%(field)s' Properties field as a whole, target individual property instead."
            )
            raise self._format_import_error(ValueError, msg, {"value": value})

        value = [dict(property_dict) for property_dict in value]

        warnings = []
        for property_dict in value:
            self._check_property_definition(property_dict)

            val = property_dict.get("value")
            if val in (None, "", [], ()):
                continue

            sub_field = FakeField(
                comodel_name=property_dict.get("comodel"),
                name=f"{field.name}.{property_dict['name']}",
            )
            match property_dict["type"]:
                case "selection":
                    coerced, ws = self._property_to_selection(
                        sub_field, val, property_dict
                    )
                case "tags":
                    coerced, ws = self._property_to_tags(val, property_dict)
                case "boolean":
                    coerced, ws = self._property_to_boolean(
                        sub_field, val, property_dict
                    )
                case "many2one" | "many2many":
                    coerced, ws = self._property_to_relational(
                        sub_field, val, property_dict
                    )
                case "integer":
                    coerced, ws = self._property_to_integer(val, property_dict)
                case "float":
                    coerced, ws = self._property_to_float(val, property_dict)
                case _:
                    coerced, ws = val, []
            warnings.extend(ws)
            if coerced is None:
                return None, warnings
            property_dict["value"] = coerced

        return value, warnings

    _PROPERTY_TYPE_KEYS = {
        "selection": ("selection", 2),
        "tags": ("tags", 3),
        "many2one": ("comodel", 0),
        "many2many": ("comodel", 0),
    }

    @api.model
    def _check_property_definition(self, property_dict: dict) -> None:
        if not (property_dict.keys() >= {"name", "type", "string"}) or not isinstance(
            property_dict["type"], str
        ):
            msg = self.env._(
                "'%(value)s' does not seem to be a valid Property value for field '%%(field)s'. Each property need at least 'name', 'type' and 'string' attribute."
            )
            raise self._format_import_error(ValueError, msg, {"value": property_dict})

        required, width = self._PROPERTY_TYPE_KEYS.get(property_dict["type"], (None, 0))
        if required and required not in property_dict:
            msg = self.env._(
                "The '%(label_property)s' property (subfield of '%%(field)s' field) is missing its '%(value)s' definition."
            )
            raise self._property_import_error(msg, required, property_dict)
        if width and not self._is_definition_rows(property_dict[required], width):
            msg = self.env._(
                "The '%(label_property)s' property (subfield of '%%(field)s' field) has a malformed '%(value)s' definition."
            )
            raise self._property_import_error(msg, required, property_dict)
        if required == "comodel" and not self._is_importable_model(
            property_dict[required]
        ):
            msg = self.env._(
                "The '%(label_property)s' property (subfield of '%%(field)s' field) targets unknown model '%(value)s'."
            )
            raise self._property_import_error(
                msg, property_dict[required], property_dict
            )

    @api.model
    def _is_importable_model(self, comodel_name: Any) -> bool:
        return isinstance(comodel_name, str) and comodel_name in self.env

    @staticmethod
    def _is_definition_rows(rows: Any, width: int) -> bool:
        return isinstance(rows, (list, tuple)) and all(
            isinstance(row, (list, tuple)) and len(row) == width for row in rows
        )

    @api.model
    def _property_to_selection(
        self, field: FieldLike, val: Any, property_dict: dict
    ) -> tuple[Any, list]:
        new_val = next(
            (
                sel_val
                for sel_val, sel_label in property_dict["selection"]
                if val in (sel_val, sel_label)
            ),
            None,
        )
        if new_val is not None:
            return new_val, []

        match self._import_field_policy(field):
            case ImportPolicy.SKIP_RECORD:
                return None, []
            case ImportPolicy.SET_EMPTY:
                return False, []
        msg = self.env._(
            "'%(value)s' does not seem to be a valid Selection value for '%(label_property)s' (subfield of '%%(field)s' field)."
        )
        raise self._property_import_error(msg, val, property_dict)

    @api.model
    def _property_to_tags(self, val: Any, property_dict: dict) -> tuple[list, list]:
        tags = val.split(",") if isinstance(val, str) else list(val)
        new_val = []
        for tag in tags:
            val_tag = next(
                (
                    tag_val
                    for tag_val, tag_label, _color in property_dict["tags"]
                    if tag in (tag_val, tag_label)
                ),
                None,
            )
            if val_tag is None:
                msg = self.env._(
                    "'%(value)s' does not seem to be a valid Tag value for '%(label_property)s' (subfield of '%%(field)s' field)."
                )
                raise self._property_import_error(msg, tag, property_dict)
            new_val.append(val_tag)
        return new_val, []

    @api.model
    def _property_to_boolean(
        self, field: FieldLike, val: Any, property_dict: dict
    ) -> tuple[bool | None, list]:
        if isinstance(val, bool):
            return val, []
        try:
            return self._str_to_boolean(field, str(val))
        except ValueError:
            msg = self.env._(
                "Unknown value '%(value)s' for boolean '%(label_property)s' property (subfield of '%%(field)s' field)."
            )
            raise self._property_import_error(msg, val, property_dict) from None

    @api.model
    def _property_to_relational(
        self, field: FieldLike, val: Any, property_dict: dict
    ) -> tuple[Any, list]:
        try:
            [record] = val
        except TypeError, ValueError:
            record = None
        if not isinstance(record, dict):
            msg = self.env._(
                "'%(value)s' is not a valid value for the '%(label_property)s' "
                "relational property (subfield of '%%(field)s' field)."
            )
            raise self._property_import_error(msg, val, property_dict)
        multi = property_dict["type"] == "many2many"
        ids, warnings = self._resolve_reference_ids(field, record, multi=multi)
        if any(id_ is None for id_ in ids):
            if self._import_field_policy(field) is ImportPolicy.SKIP_RECORD:
                return None, warnings
            ids = [id_ for id_ in ids if id_]
        return (ids if multi else (ids[0] if ids else False)), warnings

    @api.model
    def _property_to_integer(self, val: Any, property_dict: dict) -> tuple[int, list]:
        try:
            return int(val), []
        except ValueError, TypeError:
            msg = self.env._(
                "'%(value)s' does not seem to be an integer for field '%(label_property)s' property (subfield of '%%(field)s' field)."
            )
            raise self._property_import_error(msg, val, property_dict) from None

    @api.model
    def _property_to_float(self, val: Any, property_dict: dict) -> tuple[float, list]:
        try:
            return float(val), []
        except ValueError, TypeError:
            msg = self.env._(
                "'%(value)s' does not seem to be an float for field '%(label_property)s' property (subfield of '%%(field)s' field)."
            )
            raise self._property_import_error(msg, val, property_dict) from None

    @api.model
    def _import_memo(self) -> dict:
        return self.env.cr.cache.setdefault(self._name, {})

    @api.model
    def _boolean_value_sets(self) -> tuple[frozenset, frozenset]:
        tnx_cache = self._import_memo()
        cache_key = ("boolean_value_sets",)
        if cache_key not in tnx_cache:
            trues = frozenset(
                word.lower()
                for word in itertools.chain(
                    ["1", "true", "yes"],
                    self._get_boolean_translations("true"),
                    self._get_boolean_translations("yes"),
                )
            )
            falses = frozenset(
                word.lower()
                for word in itertools.chain(
                    ["", "0", "false", "no"],
                    self._get_boolean_translations("false"),
                    self._get_boolean_translations("no"),
                )
            )
            tnx_cache[cache_key] = (trues, falses)
        return tnx_cache[cache_key]

    @api.model
    def _is_falsy_token(self, value: Any) -> bool:
        _trues, falses = self._boolean_value_sets()
        return isinstance(value, str) and value.lower() in falses

    @api.model
    def _str_to_boolean(self, field: FieldLike, value: str) -> tuple[bool | None, list]:
        trues, falses = self._boolean_value_sets()
        value_lower = str(value).lower()
        if value_lower in trues:
            return True, []
        if value_lower in falses:
            return False, []

        if self._import_field_policy(field) is ImportPolicy.SKIP_RECORD:
            return None, []

        raise self._format_import_error(
            ValueError,
            self.env._("Unknown value '%s' for boolean field '%%(field)s'"),
            value,
            {"moreinfo": self.env._("Use '1' for yes and '0' for no")},
        )

    @api.model
    def _str_to_integer(self, field: FieldLike, value: str) -> tuple[int, list]:
        try:
            return int(value), []
        except ValueError:
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "'%s' does not seem to be an integer for field '%%(field)s'"
                ),
                value,
            ) from None

    @api.model
    def _str_to_float(self, field: FieldLike, value: str) -> tuple[float, list]:
        try:
            result = float(value)
            valid = math.isfinite(result)
        except ValueError:
            valid = False
        if not valid:
            raise self._format_import_error(
                ValueError,
                self.env._("'%s' does not seem to be a number for field '%%(field)s'"),
                value,
            )
        return result, []

    _str_to_monetary = _str_to_float

    @api.model
    def _str_id(self, field: FieldLike, value: str) -> tuple[str, list]:
        return value, []

    _str_to_reference = _str_to_char = _str_to_text = _str_to_binary = _str_to_html = (
        _str_id
    )

    @api.model
    def _str_to_date(self, field: FieldLike, value: str) -> tuple[str, list]:
        try:
            if isinstance(value, str) and value[DATE_LENGTH:].strip():
                fields.Datetime.from_string(value)
            parsed_value = fields.Date.from_string(value)
            return fields.Date.to_string(parsed_value), []
        except ValueError:
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "'%s' does not seem to be a valid date for field '%%(field)s'"
                ),
                value,
                {"moreinfo": self.env._("Use the format '%s'", "2012-12-31")},
            ) from None

    @api.model
    def _input_tz(self) -> Any:
        return self.env.tz

    @api.model
    def _parse_import_datetime(self, value: Any) -> tuple[datetime, bool]:
        if isinstance(value, str):
            with contextlib.suppress(ValueError):
                value = datetime.fromisoformat(value)
        tz_aware = getattr(value, "tzinfo", None) is not None
        parsed = fields.Datetime.from_string(value)
        if parsed is None:
            raise ValueError(f"no datetime in {value!r}")
        return parsed, tz_aware

    @api.model
    def _str_to_datetime(self, field: FieldLike, value: str) -> tuple[str, list]:
        try:
            parsed_value, tz_aware = self._parse_import_datetime(value)
        except ValueError:
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "'%s' does not seem to be a valid datetime for field '%%(field)s'"
                ),
                value,
                {"moreinfo": self.env._("Use the format '%s'", "2012-12-31 23:59:59")},
            ) from None

        if tz_aware:
            return fields.Datetime.to_string(parsed_value), []

        dt = parsed_value.replace(tzinfo=self._input_tz())
        return fields.Datetime.to_string(dt.astimezone(utc)), []

    @api.model
    def _get_boolean_translations(self, src: str) -> list[str]:
        tnx_cache = self._import_memo()
        cache_key = ("boolean_translations", src)
        if cache_key in tnx_cache:
            return tnx_cache[cache_key]

        values = OrderedSet()
        for lang, __ in self.env["res.lang"].get_installed():
            translations = code_translations.get_python_translations("base", lang)
            if src in translations:
                values.add(translations[src])

        result = tnx_cache[cache_key] = list(values)
        return result

    @api.model
    def _selection_for_import(self, field: fields.Field) -> tuple[list, dict | None]:
        tnx_cache = self._import_memo()
        cache_key = ("selection", field.model_name, field.name, self.env.lang)
        if cache_key not in tnx_cache:
            selection = field._description_selection(self.with_context(lang=None).env)
            current_lang_labels = (
                dict(field._description_selection(self.env))
                if callable(field.selection)
                else None
            )
            tnx_cache[cache_key] = (selection, current_lang_labels)
        return tnx_cache[cache_key]

    @api.model
    def _selection_import_index(self, field: fields.Field) -> dict[str, Any]:
        tnx_cache = self._import_memo()
        cache_key = ("selection_index", field.model_name, field.name, self.env.lang)
        if cache_key not in tnx_cache:
            selection, current_lang_labels = self._selection_for_import(field)
            index: dict[str, Any] = {}

            def put(token: Any, item: Any) -> None:
                if token is not None and token != "":
                    index.setdefault(str(token).lower(), item)

            valid_items = set()
            for item, label in selection:
                valid_items.add(item)
                put(item, item)
                put(label, item)

            if current_lang_labels is not None:
                for item, label in selection:
                    put(current_lang_labels.get(item, label), item)
            else:
                self.env["ir.model.fields.selection"].flush_model()
                self.env.cr.execute(
                    """
                    SELECT s.value, s.name
                    FROM ir_model_fields_selection s
                    JOIN ir_model_fields f ON s.field_id = f.id
                    WHERE f.model = %s AND f.name = %s
                    ORDER BY s.sequence, s.id
                    """,
                    [field.model_name, field.name],
                )
                for value, name in self.env.cr.fetchall():
                    if value not in valid_items:
                        continue
                    for lang, txt in (name or {}).items():
                        if lang != "en_US" and txt is not None:
                            put(txt, value)
            tnx_cache[cache_key] = index
        return tnx_cache[cache_key]

    @api.model
    def _str_to_selection(self, field: fields.Field, value: str) -> tuple[Any, list]:
        item = self._selection_import_index(field).get(str(value).lower())
        if item is not None:
            return item, []

        match self._import_field_policy(field):
            case ImportPolicy.SKIP_RECORD:
                return None, []
            case ImportPolicy.SET_EMPTY:
                return False, []
        selection, _current_lang_labels = self._selection_for_import(field)
        raise self._format_import_error(
            ValueError,
            self.env._("Value '%s' not found in selection field '%%(field)s'"),
            value,
            {
                "moreinfo": [
                    _label or str(item) for item, _label in selection if _label or item
                ]
            },
        )

    @api.model
    def _possible_values_action(self, field: FieldLike, subfield: str | None) -> dict:
        action = {
            "name": "Possible Values",
            "type": "ir.actions.act_window",
            "target": "new",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "context": {"create": False},
            "help": self.env._("See all possible values"),
        }
        if subfield is None:
            action["res_model"] = field.comodel_name
        elif subfield in ("id", ".id"):
            action["res_model"] = "ir.model.data"
            action["domain"] = [("model", "=", field.comodel_name)]
        return action

    @api.model
    def _reference_cache_entry(
        self, field: FieldLike, subfield: str | None, value: Any
    ) -> tuple[Any, tuple | None]:
        cache = self.env.context.get("import_cache")
        if cache is None or subfield not in (None, ".id") or not isinstance(value, str):
            return None, None
        return cache, (field.comodel_name, subfield, value)

    @api.model
    def db_id_for(
        self,
        field: FieldLike,
        subfield: str | None,
        value: str,
    ) -> tuple[int | bool | None, list]:
        cache, cache_key = self._reference_cache_entry(field, subfield, value)
        if cache is not None:
            if (cached := cache.get(cache_key)) is not None:
                cached_id, cached_warnings = cached
                return cached_id, list(cached_warnings)

        if subfield == ".id":
            lookup = self._db_id_from_dbid(field, value)
        elif subfield == "id":
            lookup = self._db_id_from_xmlid(field, value)
        elif subfield is None:
            lookup = self._db_id_from_name(field, value)
        else:
            raise self._format_import_error(
                ValueError,
                self.env._("Unknown sub-field “%s”"),
                subfield,
            )

        if cache is not None and lookup.id:
            cache[cache_key] = (lookup.id, list(lookup.warnings))

        if (
            lookup.id is None
            and self._import_field_policy(field) is ImportPolicy.REPORT
        ):
            raise self._import_ref_not_found_error(
                field, subfield, lookup.field_type, value, lookup.error_msg
            )
        return lookup.id, lookup.warnings

    @api.model
    def _db_id_from_dbid(self, field: FieldLike, value: str) -> RefLookup:
        field_type = self.env._("database id")
        if self._is_falsy_token(value):
            return RefLookup(False, field_type, "", [])
        try:
            tentative_id = int(value)
        except ValueError:
            raise self._format_import_error(
                ValueError,
                self.env._("Invalid database id '%s' for the field '%%(field)s'"),
                value,
                {"moreinfo": self._possible_values_action(field, ".id")},
            ) from None
        exists = self.env[field.comodel_name].browse(tentative_id).exists()
        return RefLookup((tentative_id if exists else None), field_type, "", [])

    @api.model
    def _db_id_from_xmlid(self, field: FieldLike, value: str) -> RefLookup:
        field_type = self.env._("external id")
        if self._is_falsy_token(value):
            return RefLookup(False, field_type, "", [])
        value = str(value)
        if "." in value:
            xmlid = value
        else:
            xmlid = f"{self.env.context.get('_import_current_module', '')}.{value}"
        flush = self.env.context.get("import_flush", lambda **kw: None)
        flush(xml_id=xmlid)
        id = self._xmlid_to_record_id(xmlid, self.env[field.comodel_name])
        return RefLookup(id, field_type, "", [])

    @api.model
    def _db_id_from_name(self, field: FieldLike, value: str) -> RefLookup:
        field_type = self.env._("name")
        warnings = []
        if value == "":
            return RefLookup(False, field_type, "", warnings)
        RelatedModel = self.env[field.comodel_name]
        flush = self.env.context.get("import_flush", lambda **kw: None)
        flush(model=field.comodel_name)
        ids = RelatedModel.name_search(name=value, operator="=")
        if ids:
            if len(ids) > 1:
                warnings.append(
                    OdooImportWarning(
                        self.env._(
                            'Found multiple matches for value "%(value)s" in field "%%(field)s" (%(match_count)s matches)',
                            value=escape_import_message(str(value)),
                            match_count=len(ids),
                        )
                    )
                )
            id, _name = ids[0]
            return RefLookup(id, field_type, "", warnings)

        name_create_enabled_fields = (
            self.env.context.get("name_create_enabled_fields") or {}
        )
        if name_create_enabled_fields.get(self._import_policy_path(field)):
            try:
                with self.env.cr.savepoint():
                    id, _name = RelatedModel.name_create(name=value)
                return RefLookup(id, field_type, "", warnings)
            except UserError, ValueError, psycopg.Error:
                error_msg = self.env._(
                    "Cannot create new '%s' records from their name alone. Please create those records manually and try importing again.",
                    RelatedModel._description,
                )
                return RefLookup(None, field_type, error_msg, warnings)
        return RefLookup(None, field_type, "", warnings)

    @api.model
    def _import_ref_not_found_error(
        self,
        field: FieldLike,
        subfield: str | None,
        field_type: str,
        value: Any,
        error_msg: str,
    ) -> Exception:
        if error_msg:
            message = self.env._(
                "No matching record found for %(field_type)s '%(value)s' in field '%%(field)s' and the following error was encountered when we attempted to create one: %(error_message)s"
            )
        else:
            message = self.env._(
                "No matching record found for %(field_type)s '%(value)s' in field '%%(field)s'"
            )
        display_value = value[:50] if isinstance(value, str) else value
        error_info_dict = {"moreinfo": self._possible_values_action(field, subfield)}
        if self.env.context.get("import_file"):
            error_info_dict.update({"value": display_value, "field_type": field_type})
            if error_msg:
                error_info_dict["error_message"] = error_msg
        return self._format_import_error(
            ImportReferenceNotFound,
            message,
            {
                "field_type": field_type,
                "value": display_value,
                "error_message": error_msg,
            },
            error_info_dict,
        )

    @api.model
    def _xmlid_to_record_id(self, xmlid: str, model: models.BaseModel) -> int | None:
        import_cache = self.env.context.get("import_cache", {})
        if cached := import_cache.get(xmlid):
            cached_model, res_id = cached
            self._check_xmlid_model(xmlid, cached_model, model)
            return res_id

        module, name = xmlid.split(".", 1)
        self.env.cr.execute(
            SQL(
                """
                SELECT d.model, d.res_id, r.id IS NOT NULL
                FROM ir_model_data d
                LEFT JOIN %s r ON r.id = d.res_id AND d.model = %s
                WHERE d.module = %s AND d.name = %s
                """,
                SQL.identifier(model._table),
                model._name,
                module,
                name,
            )
        )
        row = self.env.cr.fetchone()
        if row is None:
            return None
        res_model, res_id, record_exists = row
        self._check_xmlid_model(xmlid, res_model, model)
        if not record_exists:
            return None
        import_cache[xmlid] = (res_model, res_id)
        return res_id

    @api.model
    def _check_xmlid_model(
        self, xmlid: str, found_model: str, model: models.BaseModel
    ) -> None:
        if found_model == model._name:
            return
        raise self._format_import_error(
            ValueError,
            self.env._(
                "External id '%(xmlid)s' refers to a '%(found_model)s' "
                "record, but field '%%(field)s' expects a "
                "'%(expected_model)s' record"
            ),
            {
                "xmlid": xmlid,
                "found_model": found_model,
                "expected_model": model._name,
            },
        )

    @api.model
    def _referencing_subfield(self, record: dict) -> str | None:
        fieldset = set(record)
        if fieldset - REFERENCING_FIELDS:
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "Can not create Many-To-One records indirectly, import the field separately"
                ),
            )
        if not fieldset:
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "Missing a reference (name, external id or database id) for field '%%(field)s'"
                ),
            )
        if len(fieldset) > 1:
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "Ambiguous specification for field '%%(field)s', only provide one of name, external id or database id"
                ),
            )

        [subfield] = fieldset
        return subfield

    @api.model
    def _split_references(self, raw: str) -> list[str]:
        if not isinstance(raw, str):
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "Field '%%(field)s' expects its references as comma-separated "
                    "text, got a value of type '%s'"
                ),
                type(raw).__name__,
            )
        return [
            stripped for reference in raw.split(",") if (stripped := reference.strip())
        ]

    @api.model
    def _single_reference(self, raw: Any) -> Any:
        return raw.strip() if isinstance(raw, str) else raw

    @api.model
    def _single_reference_record(self, values: Any) -> dict:
        if not isinstance(values, list) or len(values) != 1:
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "Field '%%(field)s' expects a single reference per record, got '%s'"
                ),
                values,
            )
        record = values[0]
        if not isinstance(record, dict):
            raise self._format_import_error(
                ValueError,
                self.env._("Field '%%(field)s' expects a reference record, got '%s'"),
                record,
            )
        return record

    @api.model
    def _sub_records(self, values: Any) -> list[dict]:
        if not isinstance(values, list) or not all(
            isinstance(record, dict) for record in values
        ):
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "Field '%%(field)s' expects a list of sub-records, got '%s'"
                ),
                values,
            )
        return values

    @api.model
    def _resolve_reference_ids(
        self, field: FieldLike, record: dict, *, multi: bool
    ) -> tuple[list[int | None], list]:
        subfield = self._referencing_subfield(record)
        raw = record[subfield]
        references = (
            self._split_references(raw) if multi else [self._single_reference(raw)]
        )
        ids = []
        warnings = []
        for reference in references:
            id_, ws = self.db_id_for(field, subfield, reference)
            ids.append(id_)
            warnings.extend(ws)
        return ids, warnings

    @api.model
    def _str_to_many2one(
        self, field: FieldLike, values: list[dict]
    ) -> tuple[int | bool | None, list]:
        record = self._single_reference_record(values)
        ids, warnings = self._resolve_reference_ids(field, record, multi=False)
        id_ = ids[0]
        if id_ is None and self._import_field_policy(field) is ImportPolicy.SET_EMPTY:
            return False, warnings
        return id_, warnings

    _str_to_many2one_reference = _str_to_integer

    @api.model
    def _str_to_many2many(
        self, field: FieldLike, value: list[dict]
    ) -> tuple[list | None, list]:
        record = self._single_reference_record(value)
        ids, warnings = self._resolve_reference_ids(field, record, multi=True)

        if any(id is None for id in ids) and (
            self._import_field_policy(field) is ImportPolicy.SKIP_RECORD
        ):
            return None, warnings

        ids = [id for id in ids if id]
        if self.env.context.get("update_many2many"):
            return [Command.link(id) for id in ids], warnings
        else:
            return [Command.set(ids)], warnings

    @api.model
    def _attribute_to_subfield(
        self, exception: Exception, comodel_name: str, subfield: str
    ) -> None:
        field = self.env[comodel_name]._fields.get(subfield)
        label = escape_import_message(field.string if field else subfield)
        arg0 = exception.args[0].replace("%(field)s", f"%(field)s/{label}")
        exception.args = (arg0, *exception.args[1:])

    @api.model
    def _nested_converter(
        self, field: FieldLike, hierarchy: list[str]
    ) -> tuple[RecordConverter, set[str]]:
        cache = self.env.context.get("import_cache")
        key = ("o2m_converter", tuple(hierarchy), field.comodel_name)
        if cache is not None and (cached := cache.get(key)) is not None:
            return cached

        pair = (
            self.with_context(parent_fields_hierarchy=list(hierarchy)).for_model(
                self.env[field.comodel_name]
            ),
            self._nested_skip_subfields(hierarchy),
        )
        if cache is not None:
            cache[key] = pair
        return pair

    @api.model
    def _str_to_one2many(
        self, field: FieldLike, records: list[dict]
    ) -> tuple[list | None, list]:
        commands = []
        warnings = []

        records = self._sub_records(records)
        if len(records) == 1 and set(records[0]) <= REFERENCING_FIELDS:
            record = records[0]
            subfield = self._referencing_subfield(record)
            records = (
                {subfield: item} for item in self._split_references(record[subfield])
            )

        parent_fields_hierarchy = self.env.context.get(
            "parent_fields_hierarchy", []
        ) + [field.name]

        def log(f: str, exception: Exception | Warning) -> None:
            if not isinstance(exception, Warning):
                self._attribute_to_subfield(exception, field.comodel_name, f)
                error_info = len(exception.args) > 1 and exception.args[1]
                if isinstance(error_info, dict) and not error_info.get("field_path"):
                    error_info["field_path"] = [*parent_fields_hierarchy, f]
                raise exception
            warnings.append(exception)

        convert, skipping_subfields = self._nested_converter(
            field, parent_fields_hierarchy
        )

        for record in records:
            id = None
            refs = only_ref_fields(record)
            writable = convert(exclude_ref_fields(record), log)
            if any(writable.get(f, False) is None for f in skipping_subfields):
                return None, warnings
            if refs:
                subfield = self._referencing_subfield(refs)
                try:
                    id, w2 = self.db_id_for(field, subfield, record[subfield])
                    warnings.extend(w2)
                except ImportReferenceNotFound:
                    if subfield != "id":
                        raise
                    writable["id"] = record["id"]

            if id:
                commands.append(Command.link(id))
                if writable:
                    commands.append(Command.update(id, writable))
            else:
                commands.append(Command.create(writable))

        return commands, warnings
