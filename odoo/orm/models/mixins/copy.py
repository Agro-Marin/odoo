"""Record duplication mixin for BaseModel: copy, copy_data, copy_translations."""

import logging
import typing
from collections import defaultdict
from typing import Self

from ..._typing import ValuesType
from ...primitives import MAGIC_COLUMNS, Command
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Collection

_logger = logging.getLogger("odoo.models")


class CopyMixin(_ModelStubs):
    """Mixin providing record duplication operations."""

    __slots__ = ()

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        """Copy each record's field values.

        :param default: field values to override in the copied records
        :return: list of dicts of field values
        """
        vals_list = []
        default = dict(default or {})
        # avoid recursion through already copied records in case of circular relationship
        if "__copy_data_seen" not in self.env.context:
            self = self.with_context(__copy_data_seen=defaultdict(set))

        # build a black list of fields that should not be copied
        blacklist = set(MAGIC_COLUMNS + ["parent_path"])
        whitelist = {
            name for name, field in self._fields.items() if not field.inherited
        }

        def blacklist_given_fields(model):
            # blacklist the fields that are given by inheritance
            for parent_model, parent_field in model._inherits.items():
                blacklist.add(parent_field)
                if parent_field in default:
                    # all the fields of 'parent_model' are given by the record:
                    # default[parent_field], except the ones redefined in self
                    blacklist.update(set(self.env[parent_model]._fields) - whitelist)
                else:
                    blacklist_given_fields(self.env[parent_model])

        blacklist_given_fields(self)

        fields_to_copy = {
            name: field
            for name, field in self._fields.items()
            if field.copy and name not in default and name not in blacklist
        }

        for record in self:
            seen_map = self.env.context["__copy_data_seen"]
            if record.id in seen_map[record._name]:
                vals_list.append(None)
                continue
            seen_map[record._name].add(record.id)

            vals = default.copy()

            for name, field in fields_to_copy.items():
                if field.type == "one2many":
                    # duplicate following the order of the ids because we'll rely on
                    # it later for copying translations in copy_translation()!
                    lines = record[name].sorted(key="id").copy_data()
                    # the lines are duplicated using the wrong (old) parent, but then are
                    # reassigned to the correct one thanks to the (Command.CREATE, 0, ...)
                    vals[name] = [Command.create(line) for line in lines if line]
                elif field.type == "many2many":
                    # copy only links that we can read, otherwise the write will fail
                    vals[name] = [
                        Command.set(record[name]._filtered_access("read").ids)
                    ]
                else:
                    vals[name] = field.convert_to_write(record[name], record)
            vals_list.append(vals)
        return vals_list

    def copy_translations(self, new: Self, excluded: Collection[str] = ()) -> None:
        """Recursively copy the translations from original to new record

        :param self: the original record
        :param new: the new record (copy of the original one)
        :param excluded: a container of user-provided field names
        """
        old = self
        # avoid recursion through already copied records in case of circular relationship
        if "__copy_translations_seen" not in old.env.context:
            old = old.with_context(__copy_translations_seen=defaultdict(set))
        seen_map = old.env.context["__copy_translations_seen"]
        if old.id in seen_map[old._name]:
            return
        seen_map[old._name].add(old.id)
        valid_langs = {code for code, _ in self.env["res.lang"].get_installed()} | {
            "en_US"
        }

        for name, field in old._fields.items():
            if not field.copy:
                continue

            if field.inherited and field.related.split(".")[0] in excluded:
                # inherited fields that come from a user-provided parent record
                # must not copy translations, as the parent record is not a copy
                # of the old parent record
                continue

            if field.type == "one2many" and field.name not in excluded:
                # we must recursively copy the translations for o2m; here we
                # rely on the order of the ids to match the translations as
                # foreseen in copy_data()
                old_lines = old[name].sorted(key="id")
                new_lines = new[name].sorted(key="id")
                if len(old_lines) != len(new_lines):
                    # copy_data() drops o2m lines skipped by its recursion
                    # guard (circular relationships), so old and new lines can
                    # no longer be matched positionally: a dropped MIDDLE line
                    # would silently shift every following pair and copy
                    # translations onto the wrong records. Skip the field
                    # instead of misaligning.
                    _logger.debug(
                        "copy_translations: skipping one2many field %r on %s: "
                        "%d source line(s) but %d copied line(s) "
                        "(copy_data recursion guard dropped lines)",
                        name,
                        old._name,
                        len(old_lines),
                        len(new_lines),
                    )
                    continue
                for old_line, new_line in zip(old_lines, new_lines, strict=True):
                    # don't pass excluded as it is not about those lines
                    old_line.copy_translations(new_line)

            elif field.translate and field.store and name not in excluded and old[name]:
                # for translatable fields we copy their translations
                old_stored_translations = field._get_stored_translations(old)
                if not old_stored_translations:
                    continue
                lang = self.env.lang or "en_US"
                if field.translate is True:
                    new.update_field_translations(
                        name,
                        {
                            k: v
                            for k, v in old_stored_translations.items()
                            if k in valid_langs and k != lang
                        },
                    )
                else:
                    old_translations = {
                        k: old_stored_translations.get(f"_{k}", v)
                        for k, v in old_stored_translations.items()
                        if k in valid_langs
                    }
                    # Source term to diff against: prefer the record's own
                    # language, then en_US. If neither is present there is no
                    # base term, so skip the field rather than raise KeyError.
                    source_term = old_translations.pop(lang, None)
                    if source_term is None:
                        source_term = old_translations.get("en_US")
                    if source_term is None:
                        continue
                    # {from_lang_term: {lang: to_lang_term}
                    translation_dictionary = field.get_translation_dictionary(
                        source_term,
                        old_translations,
                    )
                    # {lang: {old_term: new_term}}
                    translations = defaultdict(dict)
                    for (
                        from_lang_term,
                        to_lang_terms,
                    ) in translation_dictionary.items():
                        for lang, to_lang_term in to_lang_terms.items():
                            translations[lang][from_lang_term] = to_lang_term
                    new.update_field_translations(name, translations)

    def copy(self, default: ValuesType | None = None) -> Self:
        """Duplicate record ``self`` updating it with default values.

        :param default: field values to override in the copied records,
               e.g. ``{'field_name': overridden_value, ...}``
        :returns: new records
        """
        vals_list = self.with_context(active_test=False).copy_data(default)
        # copy_data returns None for records already in the recursion guard's
        # seen-map (duplicate ids, or pre-populated __copy_data_seen). Drop
        # those with their originals so create() never sees None and the
        # strict-zips below stay aligned.
        pairs = [
            (rec, vals)
            for rec, vals in zip(self, vals_list, strict=True)
            if vals is not None
        ]
        if not pairs:
            return self.browse()
        new_records = self.create([vals for _, vals in pairs])
        for (old_record, _), new_record in zip(pairs, new_records, strict=True):
            old_record.copy_translations(new_record, excluded=default or ())
        return new_records
