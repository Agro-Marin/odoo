import logging
import typing
from collections import defaultdict
from typing import Self

from ..._typing import ValuesType
from ...primitives import MAGIC_COLUMNS, Command
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection

_logger = logging.getLogger("odoo.models")


class CopyMixin(_ModelStubs):
    __slots__ = ()

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        if len(set(self._ids)) != len(self._ids):
            raise ValueError(
                f"Cannot copy {self._name} records: the same record appears "
                f"more than once in {self}. Deduplicate the recordset first "
                f"(e.g. `records.browse(unique(records._ids))`); copying it "
                f"twice over would yield a single copy."
            )

        vals_list = []
        default = dict(default or {})
        if "__copy_data_seen" not in self.env.context:
            self = self.with_context(__copy_data_seen=defaultdict(set))

        blacklist = set(MAGIC_COLUMNS + ["parent_path"])
        whitelist = {
            name for name, field in self._fields.items() if not field.inherited
        }

        def blacklist_given_fields(model):
            for parent_model, parent_field in model._inherits.items():
                blacklist.add(parent_field)
                if parent_field in default:
                    blacklist.update(set(self.env[parent_model]._fields) - whitelist)
                else:
                    blacklist_given_fields(self.env[parent_model])

        blacklist_given_fields(self)

        fields_to_copy = {
            name: field
            for name, field in self._fields.items()
            if field.copy and name not in default and name not in blacklist
        }

        # One shared map for the whole operation, carried through the context.
        seen_map = self.env.context["__copy_data_seen"]

        for record in self:
            if record.id in seen_map[record._name]:
                vals_list.append(None)
                continue
            seen_map[record._name].add(record.id)

            vals = default.copy()

            for name, field in fields_to_copy.items():
                if field.type == "one2many":
                    # Drop the already-copied lines *before* recursing rather
                    # than after: they would come back as `None` entries that
                    # this method then filters out anyway, but on the way there
                    # they pass through the child model's own `copy_data`, whose
                    # overrides overwhelmingly assume a dict. Same result, minus
                    # the trap. (Reachable whenever two copied relations overlap,
                    # or a self-referential one2many closes a cycle.)
                    lines = record[name].sorted(key="id")
                    lines = lines.filtered(
                        lambda line: line.id not in seen_map[line._name]
                    )
                    vals[name] = [
                        Command.create(line) for line in lines.copy_data() if line
                    ]
                elif field.type == "many2many":
                    vals[name] = [
                        Command.set(record[name]._filtered_access("read").ids)
                    ]
                else:
                    vals[name] = field.convert_to_write(record[name], record)
            vals_list.append(vals)
        return vals_list

    def copy_translations(self, new: Self, excluded: Collection[str] = ()) -> None:
        old = self
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

            if (
                field.inherited
                and field.related is not None
                and field.related.split(".")[0] in excluded
            ):
                continue

            if field.type == "one2many" and field.name not in excluded:
                old_lines = old[name].sorted(key="id")
                new_lines = new[name].sorted(key="id")
                if len(old_lines) != len(new_lines):
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
                    old_line.copy_translations(new_line)

            elif field.translate and field.store and name not in excluded and old[name]:
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
                    source_term = old_translations.pop(lang, None)
                    if source_term is None:
                        source_term = old_translations.get("en_US")
                    if source_term is None:
                        continue
                    translation_dictionary = field.get_translation_dictionary(
                        source_term,
                        old_translations,
                    )
                    translations = defaultdict(dict)
                    for (
                        from_lang_term,
                        to_lang_terms,
                    ) in translation_dictionary.items():
                        for term_lang, to_lang_term in to_lang_terms.items():
                            translations[term_lang][from_lang_term] = to_lang_term
                    new.update_field_translations(name, translations)

    def _copy_translations_of_renamed_field(
        self,
        new: Self,
        field_name: str,
        rename: Callable[[Self, str], str],
    ) -> None:
        field = self._fields[field_name]
        assert field.translate is True and field.store, (
            f"{field} is not a stored translate=True field"
        )
        if new[field_name] != rename(self, self[field_name]):
            # ``field_name`` came from a caller-supplied default, not from the
            # ``copy_data`` rename: leave it alone.
            return
        stored_translations = field._get_stored_translations(self)
        if not stored_translations:
            return
        valid_langs = {code for code, _name in self.env["res.lang"].get_installed()}
        valid_langs.add("en_US")
        # NB: a ``translate=True`` field keeps one cache per language, so the
        # whole dict has to go through ``_update_cache``, which dispatches it.
        # ``env.cache.update_raw`` would store it as the *current* language's
        # value, and the record would then read back a dict instead of a name.
        field._update_cache(
            new,
            {
                lang: rename(self.with_context(lang=lang), term)
                for lang, term in stored_translations.items()
                if lang in valid_langs
            },
            dirty=True,
        )

    def copy(self, default: ValuesType | None = None) -> Self:
        vals_list = self.with_context(active_test=False).copy_data(default)
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
