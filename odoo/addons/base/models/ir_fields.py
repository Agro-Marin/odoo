import functools
import itertools
import math
from collections.abc import Callable
from datetime import datetime
from typing import Any, NamedTuple

import psycopg

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.libs.datetime import utc
from odoo.libs.json import loads as json_loads
from odoo.tools import SQL, OrderedSet
from odoo.tools.translate import LazyTranslate, _, code_translations

_lt = LazyTranslate(__name__)

REFERENCING_FIELDS = {None, "id", ".id"}

# Length of an ISO date prefix "YYYY-MM-DD". Local literal rather than
# ``odoo.tools.misc.DATE_LENGTH``: importing that at base-bootstrap triggers an
# ir_model circular import.
DATE_LENGTH = 10


def only_ref_fields(record: dict[str | None, Any]) -> dict[str | None, Any]:
    return {k: v for k, v in record.items() if k in REFERENCING_FIELDS}


def exclude_ref_fields(record: dict[str | None, Any]) -> dict[str | None, Any]:
    return {k: v for k, v in record.items() if k not in REFERENCING_FIELDS}


# these lazy translations promise translations for ['yes', 'no', 'true', 'false']
BOOLEAN_TRANSLATIONS = (_lt("yes"), _lt("no"), _lt("true"), _lt("false"))


class FakeField(NamedTuple):
    comodel_name: str
    name: str


# ``FieldLike``: a real ORM field or the ``FakeField`` stand-in used for
# per-subproperty relational coercion. ``Converter`` (from ``to_field``): maps a
# ``fromtype`` value to ``(write_value, warnings)`` or raises ``ValueError``.
# ``RecordConverter`` (from ``for_model``): maps a record-ish dict and a
# ``log(field, exception)`` callback to a dict of converted write() values.
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


class IrFieldsConverter(models.AbstractModel):
    _name = "ir.fields.converter"
    _description = "Fields Converter"

    # The import savepoint (rolls back a failed ``name_create``) rides in the
    # ``import_savepoint`` context key rather than as a converter parameter: the
    # uniform ``converter(value)`` dispatch gives every converter one signature,
    # yet only ``db_id_for`` needs it. Same mechanism as ``import_flush`` /
    # ``import_cache``.

    @api.model
    def _format_import_error(
        self,
        error_type: type[Exception],
        error_msg: str,
        error_params: str | dict[str, Any] | tuple = (),
        error_args: dict[str, Any] | None = None,
    ) -> Exception:
        # sanitize params so the import system's later %-formatting is safe
        def sanitize(p: Any) -> Any:
            return p.replace("%", "%%") if isinstance(p, str) else p

        if error_params:
            match error_params:
                case str():
                    error_params = sanitize(error_params)
                case dict():
                    error_params = {k: sanitize(v) for k, v in error_params.items()}
                case tuple():
                    error_params = tuple(sanitize(v) for v in error_params)
        # ``error_args`` is passed as the second arg even when ``None`` on
        # purpose: ``BaseModel.load._log`` keys off ``len(e.args) > 1`` to attach
        # the human ``field_name``, so a 1-arg exception would drop it. Don't
        # "simplify" this away.
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
    def _import_field_policy(self, field: FieldLike) -> tuple[bool, bool]:
        """Return ``(skip_record, set_empty)`` for ``field`` from the import
        context, keyed off the field's full slash-path
        (:meth:`_import_policy_path`). The ``import_skip_records`` /
        ``import_set_empty_fields`` lists are only ever populated alongside
        ``import_file`` (see ``base_import``), so no extra guard is needed.
        """
        path = self._import_policy_path(field)
        ctx = self.env.context
        return (
            path in ctx.get("import_skip_records", []),
            path in ctx.get("import_set_empty_fields", []),
        )

    @api.model
    def _error_field_path(self, field: str, value: str | list) -> list[str]:
        """Rebuild the full field path for import-error attribution in the UI.

        Prepends the ``parent_fields_hierarchy`` context key (built by
        ``_str_to_one2many``) and descends into nested one2many values so the
        error binds to the deepest imported field, e.g. ``['partner_id', 'type']``.

        :param str field: field the value is imported into.
        :param str | list value: the raw value, or, for a one2many, a list of
            per-record dicts to descend into.
        """
        field_path = [field]
        if parent_fields_hierarchy := self.env.context.get("parent_fields_hierarchy"):
            field_path = parent_fields_hierarchy + field_path

        field_path_value = value
        while isinstance(field_path_value, list):
            # An empty sub-list carries no further field to attribute the error
            # to; stop rather than IndexError on ``field_path_value[0]``.
            if not field_path_value:
                break
            key = next(iter(field_path_value[0].keys()))
            if key:
                field_path.append(key)
            field_path_value = field_path_value[0][key]
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
        # make sure model is new api
        model = self.env[model._name]
        fields = model._fields

        # Resolve converters lazily and memoize per field name: only columns
        # actually present in the imported records pay for a ``to_field`` lookup.
        # Matters for one2many imports, where ``for_model`` is (re)built once per
        # parent row over the whole comodel field set.
        converter_cache: dict[str, Converter | None] = {}

        def get_converter(name: str) -> Converter | None:
            if name not in converter_cache:
                field = fields.get(name)
                converter_cache[name] = (
                    self.to_field(field, fromtype) if field is not None else None
                )
            return converter_cache[name]

        def fn(record: dict, log: Callable) -> dict:
            converted = {}
            import_file_context = self.env.context.get("import_file")
            for field, value in record.items():
                if field in REFERENCING_FIELDS:
                    continue
                if not value:
                    converted[field] = False
                    continue
                converter = get_converter(field)
                if converter is None:
                    # A field whose type has no ``_str_to_<type>`` method (e.g.
                    # ``properties_definition``), or one absent from the model.
                    # Log a per-field error rather than let ``None(value)`` raise
                    # a TypeError that aborts the entire ``load()`` (IFLD-07).
                    field_obj = fields.get(field)
                    log(
                        field,
                        self._format_import_error(
                            ValueError,
                            self.env._(
                                "Field '%%(field)s' cannot be imported (unsupported field type '%s')"
                            ),
                            field_obj.type if field_obj is not None else "unknown",
                        ),
                    )
                    continue
                try:
                    converted[field], ws = converter(value)
                    for w in ws:
                        if isinstance(w, str):
                            # wrap in OdooImportWarning for uniform handling
                            w = OdooImportWarning(w)
                        log(field, w)
                except (UnicodeEncodeError, UnicodeDecodeError) as e:
                    log(field, ValueError(str(e)))
                except psycopg.DataError as e:
                    # psycopg3 rejects bad bytes (e.g. NUL 0x00) client-side at
                    # adaptation time as DataError (psycopg2 raised ValueError).
                    # No server round-trip, so the cursor is intact; surface it as
                    # a per-field import error.
                    log(field, ValueError(str(e)))
                except ValueError as e:
                    if import_file_context:
                        # A matching error carries a dict as its second arg. E.g.:
                        # ("Value X cannot be found for field Y at row 1", {
                        #   'more_info': {},
                        #   'value': 'X',
                        #   'field': 'Y',
                        #   'field_path': ['child_id', 'Y'],  # a LIST; the web
                        #       client joins it with '/' (import_model.js)
                        # })  # noqa: ERA001, RUF100
                        # Add the field path so the UI can bind the error to the
                        # right header-field couple. Only the deepest child is
                        # raised, so set it only if not already present.
                        error_info = len(e.args) > 1 and e.args[1]
                        if error_info and not error_info.get(
                            "field_path"
                        ):  # only the deepest child in error
                            error_info["field_path"] = self._error_field_path(
                                field, value
                            )
                    log(field, e)
            return converted

        return fn

    @api.model
    def to_field(
        self, field: FieldLike, fromtype: type | str = str
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
        # a string value imports all properties at once (the technical value)
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

        # Coerce onto shallow copies: a caller passing property dicts (not a JSON
        # string) must not see its input mutated in place. Converters must have no
        # visible side effects on their args.
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
            # An empty cell means "no value": skip coercion so it isn't rejected
            # as an invalid selection/tag nor unpacked as an empty m2o/m2m.
            # Matches None / "" / [] / () but not falsy 0 / False.
            if val in (None, "", [], ()):
                continue

            # Coerce the sub-value per property type; each arm returns
            # ``(coerced_value, warnings)``. An unrecognized type is left as-is.
            match property_dict["type"]:
                case "selection":
                    coerced, ws = self._property_to_selection(val, property_dict)
                case "tags":
                    coerced, ws = self._property_to_tags(val, property_dict)
                case "boolean":
                    coerced, ws = self._property_to_boolean(field, val, property_dict)
                case "many2one" | "many2many":
                    coerced, ws = self._property_to_relational(
                        property_dict["type"], property_dict
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
        new_val, bool_warnings = self._str_to_boolean(field, str(val))
        if bool_warnings:
            msg = self.env._(
                "Unknown value '%(value)s' for boolean '%(label_property)s' property (subfield of '%%(field)s' field)."
            )
            raise self._property_import_error(msg, val, property_dict)
        return new_val, []

    @api.model
    def _property_to_relational(
        self, property_type: str, property_dict: dict
    ) -> tuple[Any, list]:
        """Resolve a Properties ``many2one`` / ``many2many`` sub-value to ids via
        the shared reference resolver. Returns a single id for m2o, a list for
        m2m, plus any resolution warnings.
        """
        [record] = property_dict["value"]
        fake_field = FakeField(
            comodel_name=property_dict["comodel"],
            name=property_dict["string"],
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
    def _boolean_value_sets(self) -> tuple[frozenset, frozenset]:
        """Return ``(trues, falses)``: the lowercased literal and translated
        tokens accepted as boolean ``True`` / ``False`` on import.

        Memoized per cursor to avoid rebuilding the sets for every boolean and
        every relational-by-id cell (:meth:`db_id_for`) of an import.
        """
        tnx_cache = self.env.cr.cache.setdefault(self._name, {})
        cache_key = "boolean_value_sets"
        if cache_key not in tnx_cache:
            # potentially broken casefolding? What about locales?
            trues = frozenset(
                word.lower()
                for word in itertools.chain(
                    ["1", "true", "yes"],  # don't use potentially translated values
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
        trues, falses = self._boolean_value_sets()
        value_lower = value.lower()
        if value_lower in trues:
            return True, []
        if value_lower in falses:
            return False, []

        skip_record, _set_empty = self._import_field_policy(field)
        if skip_record:
            return None, []

        # Return ``None`` (not ``True``) on unknown input: a caller that
        # logs-but-continues must not coerce garbage to ``True``. The warning
        # still aborts the row on the normal path, and ``_str_to_properties``
        # checks the warning list.
        return None, [
            self._format_import_error(
                ValueError,
                self.env._("Unknown value '%s' for boolean field '%%(field)s'"),
                value,
                {"moreinfo": self.env._("Use '1' for yes and '0' for no")},
            )
        ]

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
            # Reject non-finite input: ``float()`` parses "nan" / "inf" (and
            # overflowing exponents like "1e400" -> inf), but those can't be
            # stored in a numeric column and would surface as a cryptic ``write()``
            # failure instead of a clean, field-attributed import error here.
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
            # ``fields.Date.from_string`` slices to ``value[:DATE_LENGTH]`` and
            # would silently accept trailing garbage ("2012-12-31xxx"); reject it
            # so corrupt input fails loudly. But a trailing time component is
            # common and valid ("2012-12-31 00:00:00", "2012-12-31T23:59:59"), so
            # require the whole string to parse as a datetime before dropping it.
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
    def _str_to_datetime(self, field: FieldLike, value: str) -> tuple[str, list]:
        try:
            parsed_value = fields.Datetime.from_string(value)
        except ValueError:
            raise self._format_import_error(
                ValueError,
                self.env._(
                    "'%s' does not seem to be a valid datetime for field '%%(field)s'"
                ),
                value,
                {"moreinfo": self.env._("Use the format '%s'", "2012-12-31 23:59:59")},
            ) from None

        # ``Datetime.from_string`` already converts an offset-bearing ISO string
        # (e.g. Luxon's ``toISO()`` "2026-03-19T16:09:18-06:00") to naive UTC.
        # Re-stamping the input tz then would double-apply the offset and store
        # the wrong instant, so only apply the input tz when the source was naive.
        if isinstance(value, str) and self._iso_value_is_tz_aware(value):
            return fields.Datetime.to_string(parsed_value), []

        input_tz = self._input_tz()  # Apply input tz to the parsed naive datetime
        dt = parsed_value.replace(tzinfo=input_tz)
        # And convert to UTC before reformatting for writing
        return fields.Datetime.to_string(dt.astimezone(utc)), []

    @api.model
    def _iso_value_is_tz_aware(self, value: str) -> bool:
        """Return whether an ISO datetime string carries timezone information
        (an offset or ``Z``).
        """
        try:
            return datetime.fromisoformat(value).tzinfo is not None
        except ValueError:
            return False

    @api.model
    def _get_boolean_translations(self, src: str) -> list[str]:
        # Cache translations so they aren't reloaded on every row of the file
        tnx_cache = self.env.cr.cache.setdefault(self._name, {})
        if src in tnx_cache:
            return tnx_cache[src]

        values = OrderedSet()
        for lang, __ in self.env["res.lang"].get_installed():
            translations = code_translations.get_python_translations("base", lang)
            if src in translations:
                values.add(translations[src])

        result = tnx_cache[src] = list(values)
        return result

    @api.model
    def _selection_for_import(self, field: FieldLike) -> tuple[list, dict | None]:
        """Return ``(untranslated_selection, current_lang_labels)`` for a
        selection ``field``, memoized per cursor for the life of an import.

        Reading these once per import rather than per cell avoids rebuilding the
        whole field description dict (and re-invoking a callable ``selection``) on
        every cell. ``current_lang_labels`` is the ``{item: label}`` map in the
        current language, built only for callable selections (static ones are
        translated in bulk by :meth:`_selection_import_index`).
        """
        tnx_cache = self.env.cr.cache.setdefault(self._name, {})
        cache_key = ("import_selection", field.model_name, field.name, self.env.lang)
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
    def _selection_import_index(self, field: FieldLike) -> dict[str, Any]:
        """Return a memoized ``{normalized_token: item}`` index for a selection
        ``field``: every accepted spelling of a value -- technical key, label,
        and every translated label -- lowercased, mapped to the selection item to
        store. Memoized per cursor, like :meth:`_selection_for_import`.

        Built with one query for the whole field, replacing a per-item scan that
        issued up to *n* queries per import batch (~600 for ``res.partner.tz``).
        ``setdefault`` keeps the earliest item on a token collision, preserving
        the old scan's "first match wins" order.
        """
        tnx_cache = self.env.cr.cache.setdefault(self._name, {})
        cache_key = (
            "import_selection_index",
            field.model_name,
            field.name,
            self.env.lang,
        )
        if cache_key not in tnx_cache:
            selection, current_lang_labels = self._selection_for_import(field)
            index: dict[str, Any] = {}

            def put(token: Any, item: Any) -> None:
                # Skip only ``None`` / empty string; keep falsy-but-valid keys
                # such as ``0`` / ``False``.
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
                # One query for the whole field: pull every translated label of
                # every selection row, keyed by its technical ``value``.
                self.env["ir.model.fields.selection"].flush_model()
                self.env.cr.execute(
                    """
                    SELECT s.value, s.name
                    FROM ir_model_fields_selection s
                    JOIN ir_model_fields f ON s.field_id = f.id
                    WHERE f.model = %s AND f.name = %s
                    """,
                    [field.model_name, field.name],
                )
                for value, name in self.env.cr.fetchall():
                    # Ignore stale rows no longer in the current selection, so a
                    # token never resolves to a removed item.
                    if value not in valid_items:
                        continue
                    for lang, txt in (name or {}).items():
                        if lang != "en_US" and txt is not None:
                            put(txt, value)
            tnx_cache[cache_key] = index
        return tnx_cache[cache_key]

    @api.model
    def _str_to_selection(self, field: FieldLike, value: str) -> tuple[Any, list]:
        # Case-insensitive lookup against the prebuilt index. ``None`` is the
        # miss sentinel (no selection item is ever ``None``), so a valid but
        # falsy item such as ``False`` still resolves.
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
        if subfield == ".id":
            lookup = self._db_id_from_dbid(field, value)
        elif subfield == "id":
            lookup = self._db_id_from_xmlid(field, value)
        elif subfield is None:
            lookup = self._db_id_from_name(field, value)
        else:
            # ``ValueError`` (not bare ``Exception``) so ``for_model``'s ``fn``
            # catches it and reports a per-field error instead of aborting the
            # whole ``load()``.
            raise self._format_import_error(
                ValueError,
                self.env._("Unknown sub-field “%s”", subfield),
            )

        # ``lookup.id``: ``False`` for an empty reference (returned as-is), int
        # when resolved, ``None`` when unresolved. An unresolved reference is an
        # import error unless the field's policy skips the record / sets empty.
        skip_record = set_empty = False
        if self.env.context.get("import_file"):
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
        # Skip only on a recognized falsy token; an unknown value must fall
        # through to the ``int(value)`` parse, not be treated as empty (IFLD-03).
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
        # Skip only on a recognized falsy token; an unknown value must be resolved
        # as an external id below (IFLD-03).
        if self._is_falsy_token(value):
            return RefLookup(False, field_type, "", [])
        # An external id is textual by definition. Coerce so a non-string cell
        # (e.g. an integer via ``db_id_for``) resolves to "no match" -- a clean
        # import error -- instead of raising ``TypeError`` on ``"." in value``
        # and aborting the whole ``load()`` (IFLD-14).
        value = str(value)
        if "." in value:
            xmlid = value
        else:
            xmlid = f"{self.env.context.get('_import_current_module', '')}.{value}"
        # ``flush`` (from ``BaseModel.load``) forces creation of records batched
        # earlier in the same import so their external id resolves here.
        flush = self.env.context.get("import_flush", lambda **kw: None)
        flush(xml_id=xmlid)
        id = self._xmlid_to_record_id(xmlid, self.env[field.comodel_name])
        return RefLookup(id, field_type, "", [])

    @api.model
    def _db_id_from_name(self, field: FieldLike, value: str) -> RefLookup:
        """Resolve a name reference via ``name_search`` (creating the record with
        ``name_create`` when the field opts in via ``name_create_enabled_fields``).

        :return: a :class:`RefLookup`; ``error_msg`` is non-empty only when an
            enabled ``name_create`` failed, and ``warnings`` carries the
            "multiple matches" notice when relevant.
        """
        field_type = self.env._("name")
        warnings = []
        if value == "":
            return RefLookup(False, field_type, "", warnings)
        RelatedModel = self.env[field.comodel_name]
        # ``flush`` (from ``BaseModel.load``) forces creation of records batched
        # earlier in the same import so a name_search can find them.
        flush = self.env.context.get("import_flush", lambda **kw: None)
        flush(model=field.comodel_name)
        ids = RelatedModel.name_search(name=value, operator="=")
        if ids:
            if len(ids) > 1:
                warnings.append(
                    OdooImportWarning(
                        _(
                            'Found multiple matches for value "%(value)s" in field "%%(field)s" (%(match_count)s matches)',
                            value=str(value).replace("%", "%%"),
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
                id, _name = RelatedModel.name_create(name=value)
                RelatedModel.env.flush_all()
                return RefLookup(id, field_type, "", warnings)
            except UserError, ValueError, psycopg.Error:
                # Only recoverable refusals become the "cannot create from name
                # alone" message: user-facing ORM errors (``UserError`` covers its
                # ``ValidationError`` / ``AccessError`` subclasses), conversion
                # errors, and database errors. A programming error in a
                # ``name_create`` override (e.g. ``TypeError``) now propagates
                # rather than being masked (IFLD-16; mirrors the ``safe_write``
                # narrowing in ir_model_fields_selection.py, SEL-C4).
                # ``import_savepoint`` is set by ``BaseModel.load``; guard so a
                # caller reaching here without it fails with the import error, not
                # ``AttributeError`` on ``None.rollback()``.
                savepoint = self.env.context.get("import_savepoint")
                if savepoint is not None:
                    savepoint.rollback()
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
        # Truncate to 50 chars for display only; a dedicated local avoids
        # mutating the source ``value`` in place (IFLD-06).
        display_value = value[:50] if isinstance(value, str) else value
        error_info_dict = {"moreinfo": self._possible_values_action(field, subfield)}
        if self.env.context.get("import_file"):
            error_info_dict.update({"value": display_value, "field_type": field_type})
            if error_msg:
                error_info_dict["error_message"] = error_msg
        return self._format_import_error(
            ValueError,
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
                raise ValueError(
                    f"Invalid external ID {xmlid}: expected model {model._name!r}, found {res_model!r}"
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
        # Can import by display_name, external id or database id
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

        # only one field left possible, unpack
        [subfield] = fieldset
        return subfield

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
        references = raw.split(",") if multi else [raw]
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
        # Should only be one record, unpack
        [record] = values
        ids, warnings = self._resolve_reference_ids(field, record, multi=False)
        return ids[0], warnings

    # A many2one_reference stores a raw integer id, so it converts like an
    # integer field (alias, as with ``_str_to_monetary = _str_to_float``).
    _str_to_many2one_reference = _str_to_integer

    @api.model
    def _str_to_many2many(
        self, field: FieldLike, value: list[dict]
    ) -> tuple[list | None, list]:
        [record] = value
        ids, warnings = self._resolve_reference_ids(field, record, multi=True)

        skip_record, set_empty = self._import_field_policy(field)
        has_unresolved = any(id is None for id in ids)
        if set_empty and has_unresolved:
            ids = [id for id in ids if id]
        elif skip_record and has_unresolved:
            return None, warnings

        if self.env.context.get("update_many2many"):
            return [Command.link(id) for id in ids], warnings
        else:
            return [Command.set(ids)], warnings

    @api.model
    def _str_to_one2many(
        self, field: FieldLike, records: list[dict]
    ) -> tuple[list, list]:
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
            # only one row with only ref field, field=ref1,ref2,ref3 as in
            # m2o/m2m
            record = records[0]
            subfield = self._referencing_subfield(record)
            # transform [{subfield:ref1,ref2,ref3}] into
            # [{subfield:ref1},{subfield:ref2},{subfield:ref3}]
            records = ({subfield: item} for item in record[subfield].split(","))

        def log(f: str, exception: Exception | Warning) -> None:
            if not isinstance(exception, Warning):
                # ``f`` may name a field absent from the comodel (IFLD-07);
                # fall back to the raw name instead of raising ``KeyError``, which
                # would escape ``fn``'s ``ValueError``-only handling and abort the
                # whole ``load()`` (IFLD-15).
                f_field = self.env[field.comodel_name]._fields.get(f)
                current_field_name = f_field.string if f_field else f
                arg0 = exception.args[0].replace(
                    "%(field)s", "%(field)s/" + current_field_name
                )
                exception.args = (arg0, *exception.args[1:])
                raise exception
            warnings.append(exception)

        # Complete the field hierarchy path
        # E.g. For "parent/child/subchild", field hierarchy path for "subchild" is ['parent', 'child']
        parent_fields_hierarchy = self.env.context.get(
            "parent_fields_hierarchy", []
        ) + [field.name]

        convert = self.with_context(
            name_create_enabled_fields=relative_name_create_enabled_fields,
            parent_fields_hierarchy=parent_fields_hierarchy,
        ).for_model(self.env[field.comodel_name])

        for record in records:
            id = None
            refs = only_ref_fields(record)
            writable = convert(exclude_ref_fields(record), log)
            if refs:
                subfield = self._referencing_subfield(refs)
                try:
                    id, w2 = self.db_id_for(field, subfield, record[subfield])
                    warnings.extend(w2)
                except ValueError:
                    if subfield != "id":
                        raise
                    writable["id"] = record["id"]

            if id:
                commands.extend((Command.link(id), Command.update(id, writable)))
            else:
                commands.append(Command.create(writable))

        return commands, warnings
