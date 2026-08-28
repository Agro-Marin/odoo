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
        self.env.flush_all()

        env = self.env
        first_call = not field_names

        if not (self and self._name == "res.users"):
            self.check_access("write" if self else "create")

        field_names = self._onchange_get_known_field_names(field_names)
        if not first_call and not field_names:
            return {}

        fields_spec = self._screen_fields_spec(fields_spec)

        if first_call:
            field_names = self._onchange_update_default_values(values, fields_spec)

        self._onchange_update_x2many_cache(values, fields_spec)

        record, changed_values = self._onchange_prepare_record(
            values, field_names, fields_spec
        )

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

        warning = self._onchange_get_warning(result.pop("warnings"))
        if warning:
            result["warning"] = warning

        return result

    def _onchange_get_known_field_names(self, field_names: list[str]) -> list[str]:
        """`field_names` minus the ones this model does not carry, with a warning."""
        unknown_names = [fname for fname in field_names if fname not in self._fields]
        if not unknown_names:
            return field_names
        _logger.warning(
            "onchange on %s: ignoring unknown changed field(s) %s",
            self._name,
            unknown_names,
        )
        return [fname for fname in field_names if fname in self._fields]

    def _onchange_update_default_values(
        self, values: dict, fields_spec: dict
    ) -> list[str]:
        """Seed `values` from `default_get` on the first call; return what changed."""
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
        return field_names

    def _onchange_update_x2many_cache(self, values: dict, fields_spec: dict) -> None:
        """Prime the cache of the x2many lines `values` touches, as new records."""
        self.fetch(fields_spec.keys())
        for field_name, field_spec in fields_spec.items():
            field = self._fields[field_name]
            if field.type not in ("one2many", "many2many"):
                continue
            sub_fields_spec = field_spec.get("fields") or {}
            if not (sub_fields_spec and values.get(field_name)):
                continue
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

    def _onchange_prepare_record(
        self, values: dict, field_names: list[str], fields_spec: dict
    ) -> tuple[Any, dict]:
        """The virtual record the onchange methods run on, and the changed values."""
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

        return record, changed_values

    def _onchange_get_warning(self, warnings: OrderedSet) -> dict[str, str] | None:
        """The single dialog the collected onchange warnings add up to."""
        if not warnings:
            return None
        if len(warnings) == 1:
            title, message, type_ = warnings.pop()
            return {
                "title": title,
                "message": message,
                "type": type_ or "dialog",
            }
        return {
            "title": self.env._("Warnings"),
            "message": "\n\n".join(
                [
                    warn_title + "\n\n" + warn_message
                    for warn_title, warn_message, warn_type in warnings
                ]
            ),
            "type": "dialog",
        }

    def _screen_fields_spec(
        self, fields_spec: dict, _dropped: list[str] | None = None
    ) -> dict:
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
