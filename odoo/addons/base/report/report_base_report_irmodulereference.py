import logging
from collections import defaultdict
from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from odoo import api, models

if TYPE_CHECKING:
    from odoo.addons.base.models.ir_model import IrModel
    from odoo.addons.base.models.ir_module import IrModuleModule

_logger = logging.getLogger(__name__)


class ReportBaseReport_Irmodulereference(models.AbstractModel):
    """Values for the per-module technical guide (models and fields a module adds)."""

    _name = "report.base.report_irmodulereference"
    _description = "Module Reference Report (base)"

    # ------------------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------------------

    def _get_models_by_module(self, modules: IrModuleModule) -> dict[str, IrModel]:
        """Map each module name to the ``ir.model`` records it declares.

        One search for the whole recordset rather than one per module, and
        ``exists()`` because ``res_id`` carries no foreign key.

        :param recordset modules: ``ir.module.module`` records to report on
        :return: ``{module name: ir.model recordset ordered by model name}``
        :rtype: dict
        """
        data = (
            self.env["ir.model.data"]
            .sudo()
            .search(
                [("model", "=", "ir.model"), ("module", "in", modules.mapped("name"))]
            )
        )
        ids_by_module = defaultdict(list)
        for record in data:
            ids_by_module[record.module].append(record.res_id)

        model_records = self.env["ir.model"]
        return {
            module.name: model_records.browse(ids_by_module[module.name])
            .exists()
            .sorted("model")
            for module in modules
        }

    def _get_field_names_by_model(
        self, modules: IrModuleModule
    ) -> dict[str, dict[str, set[str]]]:
        """Map each module to the field names it declares, grouped by model.

        Attribution follows the ``ir.model.fields`` **record** each external ID
        points at, never the external ID's own spelling. Matching the spelling is
        what the LIKE pattern this replaces did, and ``_`` is a single-character
        wildcard in SQL, so ``field_res_users_%`` also matched
        ``field_res_users_settings_embedded_action__action_id`` and reported
        ``action_id`` as a field the module adds to ``res.users``.

        A field record may carry an external ID in more than one module, so the
        pairing is read off ``ir.model.data`` rows and not off the field records.

        :param recordset modules: ``ir.module.module`` records to report on
        :return: ``{module name: {model name: {field names}}}``
        :rtype: dict
        """
        data = (
            self.env["ir.model.data"]
            .sudo()
            .search(
                [
                    ("model", "=", "ir.model.fields"),
                    ("module", "in", modules.mapped("name")),
                ]
            )
        )
        live_fields = self.env["ir.model.fields"].browse(data.mapped("res_id")).exists()
        spec_by_id = {field.id: (field.model, field.name) for field in live_fields}

        names: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for record in data:
            if spec := spec_by_id.get(record.res_id):
                model_name, field_name = spec
                names[record.module][model_name].add(field_name)
        return names

    def _get_field_descriptions(
        self, model_name: str, field_names: Collection[str]
    ) -> list[dict[str, Any]]:
        """Describe ``field_names`` of ``model_name``, or return an empty list.

        Empty for the two cases that otherwise abort the whole document:

        * the model has an ``ir.model`` row but no class in the registry, which is
          what a module installed in the database and then dropped from the addons
          path leaves behind;
        * ``fields_get`` raises. Field descriptions are evaluated lazily, so a
          mixin whose ``domain=`` callable reaches a hook only a concrete host
          implements raises here: ``mixin.order.line.fields`` and
          ``mixin.sql.report`` both do.

        :param str model_name: model to describe
        :param field_names: field names to keep; empty means describe nothing
        :return: one flat dict per field, ordered by field name
        :rtype: list
        """
        if not field_names:
            # fields_get() treats a falsy `allfields` as "every field".
            return []
        model = self.env.get(model_name)
        if model is None:
            return []
        try:
            descriptions = model.fields_get(field_names)
        except Exception:
            _logger.warning(
                "Cannot describe the fields of %s; reporting it without them.",
                model_name,
                exc_info=True,
            )
            return []
        return [
            {
                "name": name,
                "string": description.get("string", name),
                "type": description.get("type", ""),
                "required": description.get("required", False),
                "readonly": description.get("readonly", False),
                "help": description.get("help", ""),
            }
            for name, description in sorted(descriptions.items())
        ]

    @api.model
    def _get_report_values(
        self, docids: list[int] | None, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        modules = self.env["ir.module.module"].browse(docids)
        models_by_module = self._get_models_by_module(modules)
        names_by_module = self._get_field_names_by_model(modules)

        objects_by_module = {}
        for module in modules:
            field_names = names_by_module.get(module.name, {})
            objects_by_module[module.name] = [
                {
                    "model": record.model,
                    "name": record.name,
                    "fields": self._get_field_descriptions(
                        record.model, field_names.get(record.model, ())
                    ),
                }
                for record in models_by_module[module.name]
            ]

        return {
            "doc_ids": docids,
            "doc_model": "ir.module.module",
            "docs": modules,
            "objects_by_module": objects_by_module,
        }
