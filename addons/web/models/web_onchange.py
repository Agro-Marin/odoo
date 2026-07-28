"""Web onchange and form-processing operations on the base model.

Provides ``onchange`` (the webclient's onchange RPC entry point) and
``web_override_translations``.
"""

import itertools
import logging
from typing import Any

from odoo import models
from odoo.api import NewId
from odoo.fields import Command
from odoo.tools import OrderedSet, unique

from .record_snapshot import RecordSnapshot

_logger = logging.getLogger(__name__)


class Base(models.AbstractModel):
    _inherit = "base"

    def onchange(
        self, values: dict, field_names: list[str], fields_spec: dict
    ) -> dict[str, Any]:
        """
        Perform an onchange on the given fields, and return the result.

        :param values: dictionary mapping field names to values on the form view,
            giving the current state of modification
        :param field_names: names of the modified fields
        :param fields_spec: dictionary specifying the fields in the view,
            just like the one used by :meth:`web_read`; it is used to format
            the resulting values

        When creating a record from scratch, the client should call this with an
        empty list as ``field_names``. In that case, the method first adds
        default values to ``values``, computes the remaining fields, applies
        onchange methods to them, and return all the fields in ``fields_spec``.

        The result is a dictionary with two optional keys. The key ``"value"``
        returns field values that should be modified on the caller.
        The corresponding value is a dict mapping field names to their value,
        in the format of :meth:`web_read`, except for x2many fields, where the
        value is a list of commands to be applied on the caller's field value.

        The key ``"warning"`` provides a warning message to the caller. The
        corresponding value is a dictionary like::

            {
                "title": "Be careful!",  # subject of message
                "message": "Blah blah blah.",  # full warning message
                "type": "dialog",  # how to display the warning
            }

        """
        self.env.flush_all()

        env = self.env
        first_call = not field_names

        if not (self and self._name == "res.users"):
            self.check_access("write" if self else "create")

        unknown_names = [fname for fname in field_names if fname not in self._fields]
        if unknown_names:
            _logger.warning(
                "onchange on %s: ignoring unknown changed field(s) %s",
                self._name,
                unknown_names,
            )
            field_names = [fname for fname in field_names if fname in self._fields]
            if not field_names:
                return {}

        fields_spec = self._screen_fields_spec(fields_spec)

        if first_call:
            stale_names = [
                fname for fname in values if fname != "id" and fname not in self._fields
            ]
            if stale_names:
                _logger.warning(
                    "onchange on %s: ignoring unknown field(s) %s from values",
                    self._name,
                    stale_names,
                )
                for fname in stale_names:
                    del values[fname]
            field_names = [fname for fname in values if fname != "id"]
            missing_names = [fname for fname in fields_spec if fname not in values]
            defaults = self.default_get(missing_names)
            for field_name in missing_names:
                if field_name in defaults:
                    values[field_name] = defaults[field_name]
                    field_names.append(field_name)
                else:
                    field = self._fields[field_name]
                    if not field.compute or self.pool.field_depends[field]:
                        values[field_name] = False

        self.fetch(fields_spec.keys())
        for field_name, field_spec in fields_spec.items():
            field = self._fields[field_name]
            if field.type not in ("one2many", "many2many"):
                continue
            sub_fields_spec = field_spec.get("fields") or {}
            if sub_fields_spec and values.get(field_name):
                line_ids = OrderedSet(self[field_name].ids)
                for cmd in values[field_name]:
                    if cmd[0] in (Command.UPDATE, Command.LINK):
                        line_ids.add(cmd[1])
                    elif cmd[0] == Command.SET:
                        line_ids.update(cmd[2])
                lines = self[field_name].browse(line_ids)
                lines.fetch(sub_fields_spec.keys())
                new_lines = lines.browse(map(NewId, line_ids))
                for sub_field_name in sub_fields_spec:
                    sub_field = lines._fields[sub_field_name]
                    for new_line, line in zip(new_lines, lines, strict=True):
                        line_value = sub_field.convert_to_cache(
                            line[sub_field_name], new_line, validate=False
                        )
                        sub_field._update_cache(new_line, line_value)

        initial_values = dict(values)
        changed_values = {
            fname: initial_values.pop(fname)
            for fname in field_names
            if fname in initial_values
        }

        for parent_name in self._inherits.values():
            if not initial_values.get(parent_name, True):
                initial_values.pop(parent_name)

        if self:
            cache_values = {fname: self[fname] for fname in fields_spec}
            record = self.new(cache_values, origin=self)
            record._update_cache(initial_values)
        else:
            initial_values.update(dict.fromkeys(field_names, False))
            record = self.new(initial_values)

        for field_name in initial_values:
            field = self._fields.get(field_name)
            if field and field.inherited:
                parent_name, related_field_name = field.related.split(".", 1)
                if parent := record[parent_name]:
                    parent._update_cache({related_field_name: record[field_name]})

        snapshot0 = RecordSnapshot(record, fields_spec, fetch=(not first_call))

        record._update_cache(changed_values)

        for field_name in field_names:
            snapshot0.fetch(field_name)

        todo = (
            list(unique(itertools.chain(field_names, fields_spec)))
            if first_call
            else list(field_names)
        )
        done = set()

        protected = [
            field
            for mod_field in [self._fields[fname] for fname in field_names]
            for field in self.pool.field_computed.get(mod_field) or [mod_field]
        ]
        with self.env.protecting(protected, record):
            record.modified(list(self._fields) if first_call else todo)
            for field_name in todo:
                field = self._fields[field_name]
                if field.inherited:
                    parent = record[field.related.split(".")[0]]
                    parent[field_name] = record[field_name]

        result = {"warnings": OrderedSet()}

        while todo:
            visited_onchanges = set()
            for field_name in todo:
                record._apply_onchange_methods(field_name, result, visited_onchanges)
                visited_onchanges.update(record._onchange_methods.get(field_name, ()))
                done.add(field_name)

            if not env.context.get("recursive_onchanges", True):
                break

            todo = [
                field_name
                for field_name in fields_spec
                if field_name not in done and snapshot0.has_changed(field_name)
            ]

        snapshot1 = RecordSnapshot(record, fields_spec)
        result["value"] = snapshot1.diff(snapshot0, force=first_call)

        warnings = result.pop("warnings")
        if len(warnings) == 1:
            title, message, type_ = warnings.pop()
            if not type_:
                type_ = "dialog"
            result["warning"] = {
                "title": title,
                "message": message,
                "type": type_,
            }
        elif len(warnings) > 1:
            title = self.env._("Warnings")
            message = "\n\n".join(
                [
                    warn_title + "\n\n" + warn_message
                    for warn_title, warn_message, warn_type in warnings
                ]
            )
            result["warning"] = {
                "title": title,
                "message": message,
                "type": "dialog",
            }

        return result

    def _screen_fields_spec(
        self, fields_spec: dict, _dropped: list[str] | None = None
    ) -> dict:
        """Return *fields_spec* with unknown field names dropped, recursively.

        A stale/cached view (e.g. a module upgrade removed a field) can send a
        web spec referencing that field at ANY nesting level. This applies the
        single unknown-field policy of the web boundary — degrade gracefully,
        warn, keep serving the valid fields — the same way ``read()`` (and thus
        ``web_read``) tolerates unknown names. Consumed by :meth:`onchange` and
        :meth:`web_search_read`.

        Recurses into relational sub-specs (``fields`` of many2one/x2many);
        ``reference``/``many2one_reference`` sub-specs cannot be screened
        statically (comodel unknown until the value is read) and ``properties``
        sub-keys are property names, not model fields — both pass through
        untouched. All dropped names are collected and logged in ONE warning
        per request. The input dicts are never mutated.
        """
        top_call = _dropped is None
        if top_call:
            _dropped = []
        screened = {}
        for field_name, field_spec in fields_spec.items():
            field = self._fields.get(field_name)
            if field is None:
                _dropped.append(f"{self._name}.{field_name}")
                continue
            if (
                field.type in ("many2one", "one2many", "many2many")
                and isinstance(field_spec, dict)
                and isinstance(field_spec.get("fields"), dict)
            ):
                field_spec = dict(
                    field_spec,
                    fields=self.env[field.comodel_name]._screen_fields_spec(
                        field_spec["fields"], _dropped
                    ),
                )
            screened[field_name] = field_spec
        if top_call and _dropped:
            _logger.warning(
                "%s: ignoring unknown field(s) %s from web fields specification"
                " (stale client view?)",
                self._name,
                _dropped,
            )
        return screened

    def web_override_translations(self, values: dict[str, str]) -> None:
        """
        Override all the modal translations of the given fields with the
        provided value for each field.

        :param values: dictionary of the translations to apply for each field name
            ex: ``{ "field_name": "new_value" }``
        """
        self.ensure_one()
        for field_name, value in values.items():
            field = self._fields.get(field_name)
            if field and field.translate is True:
                translations = {
                    lang: False for lang, _ in self.env["res.lang"].get_installed()
                }
                translations["en_US"] = value
                translations[self.env.lang or "en_US"] = value
                self.update_field_translations(field_name, translations)
