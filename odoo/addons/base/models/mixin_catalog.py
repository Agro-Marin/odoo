from odoo import fields, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)

SOURCE_LANG = "en_US"

assert SOURCE_LANG.replace("_", "").isalnum(), "SOURCE_LANG must be an alphanumeric tag"
_NAME_SOURCE_SQL = f"(name->>'{SOURCE_LANG}')"


def name_uniq_index(*scope, message=None, nulls_distinct=False, where=None):
    columns = ", ".join([_NAME_SOURCE_SQL, *scope])
    nulls = "" if nulls_distinct else " NULLS NOT DISTINCT"
    predicate = f" WHERE {where}" if where else ""
    return models.UniqueIndex(
        f"({columns}){nulls}{predicate}",
        message or "A record with this name already exists in this catalog.",
    )


def no_name_uniq_index():
    return models.UniqueIndex(lambda registry: "")


class MixinCatalog(models.AbstractModel):
    _name = "mixin.catalog"
    _description = "Catalog Entry (unique translated name, archivable)"

    name = fields.Char(
        translate=True,
        required=True,
    )
    active = fields.Boolean(default=True)

    _name_src_uniq = name_uniq_index()

    def _get_copy_name(self, name):
        return self.env._("%s (copy)", name)

    def _is_name_unique(self):
        return bool(self._name_src_uniq.get_definition(self.env.registry))

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        if (default and "name" in default) or not self._is_name_unique():
            _debug.logic(
                "copy_name_kept",
                model=self._name,
                records=self.ids,
                reason="default_name"
                if default and "name" in default
                else "not_unique",
            )
            return vals_list
        _debug.logic("copy_name_suffixed", model=self._name, records=self.ids)
        return [
            dict(vals, name=record._get_copy_name(record.name))
            for record, vals in zip(self, vals_list, strict=True)
        ]

    def copy_translations(self, new, excluded=()):
        name = self._fields["name"]
        if (
            not self._is_name_unique()
            or name.translate is not True
            or not name.store
            or new.name != self._get_copy_name(self.name)
        ):
            super().copy_translations(new, excluded=excluded)
            return
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record._get_copy_name(term)
        )
