import functools
import itertools
import logging
import math
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, NamedTuple

import psycopg

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.libs.datetime import utc
from odoo.libs.json import loads as json_loads
from odoo.tools import SQL, OrderedSet
from odoo.tools.translate import LazyTranslate, _, code_translations

_logger = logging.getLogger(__name__)
_lt = LazyTranslate(__name__)

REFERENCING_FIELDS = frozenset({None, "id", ".id"})

DATE_LENGTH = 10


def only_ref_fields(record: dict[str | None, Any]) -> dict[str | None, Any]:
    return {k: v for k, v in record.items() if k in REFERENCING_FIELDS}


def exclude_ref_fields(record: dict[str | None, Any]) -> dict[str | None, Any]:
    return {k: v for k, v in record.items() if k not in REFERENCING_FIELDS}


def escape_import_message(text: str) -> str:
    """Escape ``%`` so ``text`` survives the second ``%``-formatting pass that
    ``odoo.orm.models.mixins.load._convert_records`` applies to every import
    message. Only the ``%(field)s`` placeholder is meant to reach that pass, so
    any interpolated data has to be escaped here first.
    """
    return text.replace("%", "%%")


BOOLEAN_TRANSLATIONS = (_lt("yes"), _lt("no"), _lt("true"), _lt("false"))


class FakeField(NamedTuple):
    comodel_name: str
    name: str


type FieldLike = fields.Field | FakeField
type Converter = Callable[[Any], tuple[Any, list]]
type RecordConverter = Callable[[dict, Callable], dict]


class RefLookup(NamedTuple):
    """Outcome of resolving a single relational reference (see ``db_id_for``).

    ``id`` is the resolved database id, ``False`` for an empty reference, or
    ``None`` when nothing matched. ``field_type`` / ``error_msg`` feed the
    "no matching record" message on the unresolved path.
    """

    id: int | bool | None
    field_type: str
    error_msg: str
    warnings: list


class OdooImportWarning(Warning):
    """Warning propagated up the stack during import."""

    pass


class ImportReferenceNotFound(ValueError):
    """A relational reference matched no record.

    Distinguished from a reference that resolved to something *invalid* (a
    malformed database id, an external id belonging to another model) so that
    ``_str_to_one2many`` can create the missing sub-record for the former
    without also masking the latter.
    """


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
        return error_type(error_msg % error_params, error_args)

    @api.model
    def _import_policy_path(self, field: FieldLike) -> str:
        """Full slash-path of ``field`` including its one2many parents.

        This matches the keys the import UI stores in ``import_skip_records`` /
        ``import_set_empty_fields`` (e.g. ``child_ids/state`` for a selection
        nested under a one2many). At the top level it is just ``field.name``.
        """
        return "/".join(
            self.env.context.get("parent_fields_hierarchy", []) + [field.name]
        )

    @api.model
    def _import_policy_lists(self) -> tuple[Sequence[str], Sequence[str]]:
        """Return the ``(skip_records, set_empty_fields)`` policy paths.

        Both are empty unless ``import_file`` is set. The policies are choices
        made in the import UI, which always sets that key alongside them; a bare
        ``load()`` call passing one on its own used to be honoured here but not
        by the record-level check in ``load()``, and the two disagreeing
        silently dropped data. Gating in one place keeps them in step.
        """
        context = self.env.context
        if not context.get("import_file"):
            return (), ()
        return (
            context.get("import_skip_records") or (),
            context.get("import_set_empty_fields") or (),
        )

    @api.model
    def _import_field_policy(self, field: FieldLike) -> tuple[bool, bool]:
        """Return ``(skip_record, set_empty)`` for ``field``, keyed off the
        field's full slash-path (:meth:`_import_policy_path`).
        """
        path = self._import_policy_path(field)
        skip_records, set_empty_fields = self._import_policy_lists()
        return path in skip_records, path in set_empty_fields

    @api.model
    def _nested_skip_subfields(self, hierarchy: list[str]) -> set[str]:
        """Return the immediate sub-field names under ``hierarchy`` that
        ``import_skip_records`` marks as "skip the record".

        A skipped *nested* field (e.g. ``child_ids/state``) leaves its ``None``
        sentinel inside the one2many payload, where the record-level check in
        ``load()`` -- which only ever sees top-level keys -- can never find it.
        The sub-record's converter therefore reports the skip upward, by
        propagating ``None`` as the whole one2many's converted value, and
        ``load()`` finds it under ``child_ids``. Only the sub-fields named in the
        policy count: a ``None`` from some other cause (an unparseable boolean)
        must stay an error rather than silently drop the record.

        Deeper paths are folded onto their first segment, so a nested one2many
        that propagated its own ``None`` is recognized in turn.
        """
        skip_records, _set_empty = self._import_policy_lists()
        prefix = "/".join(hierarchy) + "/"
        return {
            path[len(prefix) :].partition("/")[0]
            for path in skip_records
            if path.startswith(prefix)
        }

    @api.model
    def _error_field_path(self, field: str, value: Any) -> list[str]:
        """Rebuild the full field path for import-error attribution in the UI.

        Prepends the ``parent_fields_hierarchy`` context key (built by
        ``_str_to_one2many``) and appends the referencing sub-field a relational
        value was addressed by, so that a failed ``value/id`` cell reports
        ``['value', 'id']`` rather than just ``['value']``.

        The descent stops as soon as the value is not a reference record. It
        used to walk into the first key of *any* sub-record dict, which for a
        Properties value picked up its ``name`` metadata key and reported it as
        the failing field. A one2many does not need the guesswork either: its
        sub-field errors carry their own path, attached by
        :meth:`_str_to_one2many`'s ``log``, the only place that knows which
        sub-field actually failed.

        :param str field: field the value is imported into.
        :param value: the raw value, descended into while it references records.
        """
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
        """Return a record-level converter for ``model``: a callable taking a
        record-ish dict (values of type ``fromtype``) and a ``log`` callback, and
        returning a dict matching what :meth:`odoo.models.Model.write` expects.

        :param model: :class:`odoo.models.Model` for the conversion base
        :rtype: RecordConverter
        """
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
                        error_info = len(e.args) > 1 and e.args[1]
                        if error_info and not error_info.get("field_path"):
                            error_info["field_path"] = self._error_field_path(
                                fname, value
                            )
                    log(fname, e)
                except AttributeError, TypeError:
                    _logger.warning(
                        "Import converter for field %r rejected a %s value",
                        fname,
                        type(value).__name__,
                        exc_info=True,
                    )
                    log(
                        fname,
                        self._format_import_error(
                            ValueError,
                            self.env._(
                                "Field '%%(field)s' cannot import a value of type "
                                "'%s'; provide it as text"
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
        """Return the converter for ``field`` from ``fromtype``, or ``None`` if
        none matches.

        Looks up a method named ``_$fromtype_to_$field.type``. A converter takes
        a value (a ``fromtype`` or composite of it) and returns
        ``(write_value, warnings)``, or raises ``ValueError`` on a
        validation/conversion failure.

        The ``ValueError`` first arg is a mandatory unicode, translated,
        user-visible message; it may carry a ``field`` placeholder for the
        field's user-facing name. An optional second arg is a mapping merged into
        the error dict returned to the client. A converter making assumptions
        about the data may instead append an :class:`~.OdooImportWarning` to its
        returned warnings.

        :param field: field object to generate a value for
        :type field: FieldLike
        :param fromtype: source type to convert from
        :type fromtype: type | str
        :rtype: Converter | None
        """
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
        """Build the per-subproperty import error shared by the Properties
        coercion arms, injecting ``value`` and the property label.
        """
        return self._format_import_error(
            ValueError,
            msg,
            {"value": value, "label_property": property_dict["string"]},
        )

    @api.model
    def _str_to_properties(
        self, field: FieldLike, value: str | list
    ) -> tuple[list, list]:
        """Coerce an imported Properties field value into write-ready form.

        :param field: the Properties field being imported into.
        :param value: the full JSON payload as a string, or the list of
            per-property definition dicts to convert.
        :rtype: tuple[list, list]
        """
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
            if not (property_dict.keys() >= {"name", "type", "string"}):
                msg = self.env._(
                    "'%(value)s' does not seem to be a valid Property value for field '%%(field)s'. Each property need at least 'name', 'type' and 'string' attribute."
                )
                raise self._format_import_error(
                    ValueError, msg, {"value": property_dict}
                )

            val = property_dict.get("value")
            if val in (None, "", [], ()):
                continue

            match property_dict["type"]:
                case "selection":
                    coerced, ws = self._property_to_selection(val, property_dict)
                case "tags":
                    coerced, ws = self._property_to_tags(val, property_dict)
                case "boolean":
                    coerced, ws = self._property_to_boolean(field, val, property_dict)
                case "many2one" | "many2many":
                    coerced, ws = self._property_to_relational(
                        field, property_dict["type"], property_dict
                    )
                case "integer":
                    coerced, ws = self._property_to_integer(val, property_dict)
                case "float":
                    coerced, ws = self._property_to_float(val, property_dict)
                case _:
                    coerced, ws = val, []
            property_dict["value"] = coerced
            warnings.extend(ws)

        return value, warnings

    @api.model
    def _property_to_selection(self, val: Any, property_dict: dict) -> tuple[Any, list]:
        """Resolve a Properties ``selection`` sub-value from its label or its
        technical value; raise on an unknown value.
        """
        new_val = next(
            (
                sel_val
                for sel_val, sel_label in property_dict["selection"]
                if val in (sel_val, sel_label)
            ),
            None,
        )
        if new_val is None:
            msg = self.env._(
                "'%(value)s' does not seem to be a valid Selection value for '%(label_property)s' (subfield of '%%(field)s' field)."
            )
            raise self._property_import_error(msg, val, property_dict)
        return new_val, []

    @api.model
    def _property_to_tags(self, val: Any, property_dict: dict) -> tuple[list, list]:
        """Resolve a Properties ``tags`` sub-value (comma-separated labels or
        technical values) to a list of tag ids; raise on any unknown tag.
        """
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
    ) -> tuple[bool, list]:
        """Coerce a Properties ``boolean`` sub-value, reusing the field boolean
        parser for string tokens; raise on an unrecognized token.
        """
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
        self, field: FieldLike, property_type: str, property_dict: dict
    ) -> tuple[Any, list]:
        """Resolve a Properties ``many2one`` / ``many2many`` sub-value to ids via
        the shared reference resolver. Returns a single id for m2o, a list for
        m2m, plus any resolution warnings.
        """
        try:
            [record] = property_dict["value"]
        except TypeError, ValueError:
            msg = self.env._(
                "'%(value)s' is not a valid value for the '%(label_property)s' "
                "relational property (subfield of '%%(field)s' field)."
            )
            raise self._property_import_error(
                msg, property_dict["value"], property_dict
            ) from None
        fake_field = FakeField(
            comodel_name=property_dict["comodel"],
            name=f"{field.name}.{property_dict['name']}",
        )
        multi = property_type == "many2many"
        ids, warnings = self._resolve_reference_ids(fake_field, record, multi=multi)
        return (ids if multi else ids[0]), warnings

    @api.model
    def _property_to_integer(self, val: Any, property_dict: dict) -> tuple[int, list]:
        """Coerce a Properties ``integer`` sub-value; raise on a non-integer."""
        try:
            return int(val), []
        except ValueError:
            msg = self.env._(
                "'%(value)s' does not seem to be an integer for field '%(label_property)s' property (subfield of '%%(field)s' field)."
            )
            raise self._property_import_error(msg, val, property_dict) from None

    @api.model
    def _property_to_float(self, val: Any, property_dict: dict) -> tuple[float, list]:
        """Coerce a Properties ``float`` sub-value; raise on a non-number."""
        try:
            return float(val), []
        except ValueError:
            msg = self.env._(
                "'%(value)s' does not seem to be an float for field '%(label_property)s' property (subfield of '%%(field)s' field)."
            )
            raise self._property_import_error(msg, val, property_dict) from None

    @api.model
    def _import_memo(self) -> dict:
        """Per-cursor memo shared by the import-time lookups that are worth
        computing once (boolean tokens, selection indexes).

        Every key is a tuple whose first element names the lookup. The four
        memoizers used to share this dict with key shapes that had nothing in
        common -- a bare ``"boolean_value_sets"`` string next to raw translation
        sources next to 4-tuples -- so nothing but reading all of them told you
        which namespace a key belonged to, and tests reached in by literal key.
        Cleared by cursor lifetime; clear it wholesale to force a rebuild.
        """
        return self.env.cr.cache.setdefault(self._name, {})

    @api.model
    def _boolean_value_sets(self) -> tuple[frozenset, frozenset]:
        """Return ``(trues, falses)``: the lowercased literal and translated
        tokens accepted as boolean ``True`` / ``False`` on import.

        Memoized per cursor to avoid rebuilding the sets for every boolean and
        every relational-by-id cell (:meth:`db_id_for`) of an import.
        """
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
        """Whether ``value`` is a recognized falsy/empty token ("", "0",
        "false", "no", plus their translations).

        Lets the relational-by-id / by-xmlid resolvers treat an empty cell as "no
        reference" without the full boolean parser. The non-``str`` guard lives
        here: a non-string value is not a falsy token, so it falls through to
        normal resolution instead of raising ``AttributeError`` on
        ``value.lower()``.
        """
        _trues, falses = self._boolean_value_sets()
        return isinstance(value, str) and value.lower() in falses

    @api.model
    def _str_to_boolean(self, field: FieldLike, value: str) -> tuple[bool | None, list]:
        """Convert an import cell to a boolean.

        Returns ``None`` only for a cell ``import_skip_records`` covers -- the
        record-skip sentinel every converter shares. An unrecognized token
        raises, like every other ``_str_to_*``.

        It used to return ``None`` *and* an error smuggled through the warnings
        list, which made ``None`` mean both "skip this record" and "this cell is
        broken", and, by bypassing the ``except ValueError`` arm of
        :meth:`for_model`, made a boolean the one field type whose error reached
        the client with no ``field_path`` to highlight.
        """
        trues, falses = self._boolean_value_sets()
        value_lower = str(value).lower()
        if value_lower in trues:
            return True, []
        if value_lower in falses:
            return False, []

        skip_record, _set_empty = self._import_field_policy(field)
        if skip_record:
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
        """Convert an import cell to a date.

        A cell carrying a time part is parsed as a datetime purely to reject a
        tail that is not a valid time ("2012-12-31 nope"); the result is
        deliberately discarded. The stored date is the literal one in the cell,
        ``value[:DATE_LENGTH]`` -- taking ``.date()`` off that datetime instead
        would shift the calendar day for any offset-bearing cell, which is wrong
        for a field that has no time zone to be shifted into.
        """
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
        """Parse ``value`` into ``(naive_utc_datetime, was_tz_aware)``.

        ``fields.Datetime.from_string`` normalizes an offset away, so whether the
        cell carried one is only knowable while parsing. That answer used to be
        recovered by parsing every cell a second time with ``fromisoformat``
        purely to inspect ``tzinfo``; parsing once and reporting both keeps the
        accepted formats identical -- ISO first, then ``from_string``'s
        ``DATETIME_FORMAT`` fallback and its non-string handling.

        An already-aware ``datetime`` object reports as aware too. The old
        re-parse could not see one (it was guarded by ``isinstance(value, str)``),
        so such a value was treated as naive and had the input time zone applied
        on top of an instant that already knew its own.
        """
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                pass
            else:
                if parsed.tzinfo is not None:
                    return parsed.astimezone(utc).replace(tzinfo=None), True
                return parsed, False
        tzinfo = getattr(value, "tzinfo", None)
        return fields.Datetime.from_string(value), tzinfo is not None

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
        """Return ``(untranslated_selection, current_lang_labels)`` for a
        selection ``field``, memoized per cursor for the life of an import.

        Reading these once per import rather than per cell avoids rebuilding the
        whole field description dict (and re-invoking a callable ``selection``) on
        every cell. ``current_lang_labels`` is the ``{item: label}`` map in the
        current language, built only for callable selections (static ones are
        translated in bulk by :meth:`_selection_import_index`).
        """
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
        """Return a memoized ``{normalized_token: item}`` index for a selection
        ``field``: every accepted spelling of a value -- technical key, label,
        and every translated label -- lowercased, mapped to the selection item to
        store. Memoized per cursor, like :meth:`_selection_for_import`.

        Built with one query for the whole field, replacing a per-item scan that
        issued up to *n* queries per import batch (~600 for ``res.partner.tz``).
        ``setdefault`` keeps the earliest item on a token collision, preserving
        the old scan's "first match wins" order.
        """
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

        skip_record, set_empty = self._import_field_policy(field)
        if skip_record:
            return None, []
        elif set_empty:
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
        """Build the "Possible Values" act_window offered as ``moreinfo`` when a
        reference cannot be resolved. Only consumed on an error, so kept off the
        ``db_id_for`` success path.
        """
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
        """Return ``(cache, key)`` for memoizing a resolved reference, or
        ``(None, None)`` when the reference must not be cached.

        Resolving a reference by name costs a full ``name_search`` (~13 queries
        per cell on ``res.partner``) and by database id an ``exists()``, and an
        import repeats the same references across rows -- 100 rows pointing at
        one parent issued 1308 queries. The results are memoized in the
        per-``load()`` ``import_cache`` LRU, which already holds the external-id
        lookups (keyed by plain xmlid strings, so the tuple keys used here
        cannot collide).

        Only *successful* resolutions are cached, by the caller: a miss may be
        resolved by a record the same import creates later, so caching it would
        make row order change the outcome. The ``id`` sub-field is resolved (and
        cached) by :meth:`_xmlid_to_record_id` instead, which must stay on the
        uncached path here so its ``import_flush`` still runs.
        """
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
    ) -> tuple[int | None, list]:
        """Find a database id for reference ``value`` in ``subfield`` of ``field``.

        :param field: relational field for which references are provided
        :param subfield: ``None`` for a name_search, ``id`` for an external id,
                         ``.id`` for a database id
        :param value: reference value to match to a record
        :return: a pair of the matched id (if any) and the warnings
        :rtype: tuple[int | None, list]
        """
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
                self.env._("Unknown sub-field “%s”", subfield),
            )

        if cache is not None and lookup.id:
            cache[cache_key] = (lookup.id, lookup.warnings)

        skip_record, set_empty = self._import_field_policy(field)
        if lookup.id is None and not set_empty and not skip_record:
            raise self._import_ref_not_found_error(
                field, subfield, lookup.field_type, value, lookup.error_msg
            )
        return lookup.id, lookup.warnings

    @api.model
    def _db_id_from_dbid(self, field: FieldLike, value: str) -> RefLookup:
        """Resolve a ``.id`` (raw database id) reference.

        :return: a :class:`RefLookup`; ``id`` is the int id when the record
            exists, ``False`` for an empty reference, ``None`` when no record
            matches.
        """
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
        """Resolve an ``id`` (external id) reference.

        :return: a :class:`RefLookup`; ``id`` is ``False`` for an empty
            reference, else the resolved id or ``None``.
        """
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
        """Resolve a name reference via ``name_search`` (creating the record with
        ``name_create`` when the field opts in via ``name_create_enabled_fields``).

        The ``name_create`` attempt runs in its own savepoint. A failing one can
        raise ``psycopg.Error``, which aborts the transaction, so the rollback
        is what makes the "cannot create from name alone" message recoverable at
        all -- reporting it on a dead cursor only turned the next statement into
        ``InFailedSqlTransaction``. Rolling back the caller's whole-import
        savepoint (passed down as ``import_savepoint``) did contain it, but
        discarded every record converted so far, and left direct callers of
        :meth:`db_id_for`, which have no such context key, on the dead cursor.

        That savepoint also subsumes the explicit ``flush_all()`` this used to
        run per created record: it flushes on entry (so earlier rows persist
        into the outer transaction and survive the rollback) and again before
        ``RELEASE`` (so the new record lands inside the savepoint), turning a
        flush failure into a rollback instead of an escape mid-block.

        :return: a :class:`RefLookup`; ``error_msg`` is non-empty only when an
            enabled ``name_create`` failed, and ``warnings`` carries the
            "multiple matches" notice when relevant.
        """
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
                        _(
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
        if name_create_enabled_fields.get(field.name):
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
        """Build the "no matching record" import error for a reference that did
        not resolve (and could not be created on the fly).
        """
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
        """Return the record id corresponding to the given external id,
        provided that the record actually exists; otherwise return ``None``.
        """
        import_cache = self.env.context.get("import_cache", {})
        result = import_cache.get(xmlid)

        if not result:
            module, name = xmlid.split(".", 1)
            query = SQL(
                """
                SELECT d.model, d.res_id
                FROM ir_model_data d
                JOIN %s r ON d.res_id = r.id
                WHERE d.module = %s AND d.name = %s
                """,
                SQL.identifier(model._table),
                module,
                name,
            )
            self.env.cr.execute(query)
            result = self.env.cr.fetchone()

        if result:
            res_model, res_id = import_cache[xmlid] = result
            if res_model != model._name:
                raise self._format_import_error(
                    ValueError,
                    self.env._(
                        "External id '%(xmlid)s' refers to a '%(found_model)s' "
                        "record, but field '%%(field)s' expects a "
                        "'%(expected_model)s' record"
                    ),
                    {
                        "xmlid": xmlid,
                        "found_model": res_model,
                        "expected_model": model._name,
                    },
                )
            return res_id
        return None

    @api.model
    def _referencing_subfield(self, record: dict) -> str | None:
        """Return the single referencing subfield of ``record``.

        Raise if the record holds a non-referencing subfield, none, or more than
        one (an ambiguous reference).

        :rtype: str | None
        """
        fieldset = set(record)
        if fieldset - REFERENCING_FIELDS:
            raise ValueError(
                self.env._(
                    "Can not create Many-To-One records indirectly, import the field separately"
                )
            )
        if not fieldset:
            raise ValueError(
                self.env._(
                    "Missing a reference (name, external id or database id) for field '%(field)s'"
                )
            )
        if len(fieldset) > 1:
            raise ValueError(
                self.env._(
                    "Ambiguous specification for field '%(field)s', only provide one of name, external id or database id"
                )
            )

        [subfield] = fieldset
        return subfield

    @staticmethod
    def _split_references(raw: str) -> list[str]:
        """Split a comma-separated relational cell into individual references,
        dropping blank segments and the whitespace around each separator.

        A blank segment is not a reference: without this, a trailing or doubled
        comma ("tag1," / "tag1,,tag2") resolves to ``False`` and leaks into the
        ``Command`` payload, which fails at write time with a raw column type
        error, or silently creates an empty one2many record. Whitespace around a
        comma is separator noise too ("tag1, tag2"), and base_import only strips
        float and date cells, so it would otherwise reach ``name_search`` intact
        and fail the record.
        """
        return [
            stripped for reference in raw.split(",") if (stripped := reference.strip())
        ]

    @api.model
    def _single_reference_record(self, values: Any) -> dict:
        """Return the one referencing record ``values`` must hold.

        The extractor yields exactly one reference record per many2one /
        many2many cell, but ``load()`` is a public API and a malformed payload
        reached the bare ``[record] = values`` unpacking, surfacing
        "too many values to unpack (expected 1, got 2)" to the user as the
        import message.
        """
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
    def _resolve_reference_ids(
        self, field: FieldLike, record: dict, *, multi: bool
    ) -> tuple[list[int | None], list]:
        """Resolve a reference record to a list of database ids plus warnings.

        Shared by the many2one / many2many converters and the Properties
        relational coercion.

        :param field: relational (or :class:`FakeField`) field being resolved.
        :param record: a single referencing record, e.g. ``{None: 'ref1,ref2'}``
            or ``{'id': 'module.xmlid'}``.
        :param multi: split the raw value on commas (x2many); otherwise treat it
            as a single reference (m2o).
        :return: ``(ids, warnings)``; ``ids`` may contain ``None`` for
            references that did not resolve.
        """
        subfield = self._referencing_subfield(record)
        raw = record[subfield]
        references = self._split_references(raw) if multi else [raw]
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
    ) -> tuple[int | None, list]:
        record = self._single_reference_record(values)
        ids, warnings = self._resolve_reference_ids(field, record, multi=False)
        return ids[0], warnings

    _str_to_many2one_reference = _str_to_integer

    @api.model
    def _str_to_many2many(
        self, field: FieldLike, value: list[dict]
    ) -> tuple[list | None, list]:
        record = self._single_reference_record(value)
        ids, warnings = self._resolve_reference_ids(field, record, multi=True)

        skip_record, set_empty = self._import_field_policy(field)
        if any(id is None for id in ids) and skip_record and not set_empty:
            return None, warnings

        ids = [id for id in ids if id]
        if self.env.context.get("update_many2many"):
            return [Command.link(id) for id in ids], warnings
        else:
            return [Command.set(ids)], warnings

    @api.model
    def _str_to_one2many(
        self, field: FieldLike, records: list[dict]
    ) -> tuple[list | None, list]:
        name_create_enabled_fields = (
            self.env.context.get("name_create_enabled_fields") or {}
        )
        prefix = field.name + "/"
        relative_name_create_enabled_fields = {
            k.removeprefix(prefix): v
            for k, v in name_create_enabled_fields.items()
            if k.startswith(prefix)
        }
        commands = []
        warnings = []

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
                f_field = self.env[field.comodel_name]._fields.get(f)
                current_field_name = f_field.string if f_field else f
                arg0 = exception.args[0].replace(
                    "%(field)s", "%(field)s/" + current_field_name
                )
                exception.args = (arg0, *exception.args[1:])
                error_info = len(exception.args) > 1 and exception.args[1]
                if isinstance(error_info, dict) and not error_info.get("field_path"):
                    error_info["field_path"] = [*parent_fields_hierarchy, f]
                raise exception
            warnings.append(exception)

        convert = self.with_context(
            name_create_enabled_fields=relative_name_create_enabled_fields,
            parent_fields_hierarchy=parent_fields_hierarchy,
        ).for_model(self.env[field.comodel_name])

        skipping_subfields = self._nested_skip_subfields(parent_fields_hierarchy)

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
