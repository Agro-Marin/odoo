from typing import Any

from odoo import api, models
from odoo.exceptions import UserError
from odoo.libs.json import dumps as json_dumps
from odoo.tools.cache_version import versioned
from odoo.tools.translate import LazyTranslate

from .web_read_group_helpers import AND

_lt = LazyTranslate(__name__)
SEARCH_PANEL_ERROR_MESSAGE = _lt("Too many items to display.")


class Base(models.AbstractModel):
    _inherit = "base"

    def _search_panel_get_field(self, field_name: str) -> Any:
        field = self._fields.get(field_name)
        if field is None:
            raise UserError(
                self.env._(
                    "Unknown field %(field)s on model %(model)s",
                    field=field_name,
                    model=self._name,
                )
            )
        return field

    @api.model
    @api.readonly
    @versioned
    def search_panel_select_range(
        self, field_name: str, **kwargs: Any
    ) -> dict[str, Any]:
        field = self._search_panel_get_field(field_name)
        supported_types = ["many2one", "selection"]
        if field.type not in supported_types:
            types = dict(
                self.env["ir.model.fields"]
                ._fields["ttype"]
                ._description_selection(self.env)
            )
            raise UserError(
                self.env._(
                    "Only types %(supported_types)s are supported for category (found type %(field_type)s)",
                    supported_types=", ".join(types[t] for t in supported_types),
                    field_type=types[field.type],
                )
            )

        model_domain = kwargs.get("search_domain", [])
        extra_domain = AND(
            [
                kwargs.get("category_domain", []),
                kwargs.get("filter_domain", []),
            ]
        )

        if field.type == "selection":
            return {
                "parent_field": False,
                "values": self._search_panel_get_selection_range(
                    field_name,
                    model_domain=model_domain,
                    extra_domain=extra_domain,
                    **kwargs,
                ),
            }

        Comodel = self.env[field.comodel_name].with_context(hierarchical_naming=False)
        field_names = ["display_name"]
        hierarchize = kwargs.get("hierarchize", True)
        parent_name = False
        if hierarchize and Comodel._parent_name in Comodel._fields:
            parent_name = Comodel._parent_name
            field_names.append(parent_name)

            def get_parent_id(record):
                value = record[parent_name]
                return value and value[0]

        else:
            hierarchize = False

        comodel_domain = kwargs.get("comodel_domain", [])
        enable_counters = kwargs.get("enable_counters")
        expand = kwargs.get("expand")
        limit = kwargs.get("limit")

        if enable_counters or not expand:
            domain_image = self._search_panel_get_field_image(
                field_name,
                model_domain=model_domain,
                extra_domain=extra_domain,
                only_counters=expand,
                set_limit=limit and not (expand or hierarchize or comodel_domain),
                **kwargs,
            )

        if not (expand or hierarchize or comodel_domain):
            values = list(domain_image.values())
            if limit and len(values) == limit:
                return {"error_msg": str(SEARCH_PANEL_ERROR_MESSAGE)}
            return {
                "parent_field": parent_name,
                "values": values,
            }

        if not expand:
            image_element_ids = list(domain_image.keys())
            if hierarchize:
                condition = [("id", "parent_of", image_element_ids)]
            else:
                condition = [("id", "in", image_element_ids)]
            comodel_domain = AND([comodel_domain, condition])
        comodel_records = Comodel.search_read(comodel_domain, field_names, limit=limit)

        if hierarchize:
            ids = (
                [rec["id"] for rec in comodel_records] if expand else image_element_ids
            )
            comodel_records = self._search_panel_sanitize_parent_hierarchy(
                comodel_records, parent_name, ids
            )

        if limit and len(comodel_records) == limit:
            return {"error_msg": str(SEARCH_PANEL_ERROR_MESSAGE)}

        field_range = {}
        for record in comodel_records:
            record_id = record["id"]
            values = {
                "id": record_id,
                "display_name": record["display_name"],
            }
            if hierarchize:
                values[parent_name] = get_parent_id(record)
            if enable_counters:
                image_element = domain_image.get(record_id)
                values["__count"] = image_element["__count"] if image_element else 0
            field_range[record_id] = values

        if hierarchize and enable_counters:
            self._search_panel_rollup_counters_global(field_range, parent_name)

        return {
            "parent_field": parent_name,
            "values": list(field_range.values()),
        }

    @api.model
    @api.readonly
    @versioned
    def search_panel_select_multi_range(
        self, field_name: str, **kwargs: Any
    ) -> dict[str, Any]:
        field = self._search_panel_get_field(field_name)
        supported_types = ["many2one", "many2many", "selection"]
        if field.type not in supported_types:
            raise UserError(
                self.env._(
                    "Only types %(supported_types)s are supported for filter (found type %(field_type)s)",
                    supported_types=", ".join(supported_types),
                    field_type=field.type,
                )
            )

        model_domain = kwargs.get("search_domain", [])
        extra_domain = AND(
            [
                kwargs.get("category_domain", []),
                kwargs.get("filter_domain", []),
            ]
        )

        if field.type == "selection":
            return {
                "values": self._search_panel_get_selection_range(
                    field_name,
                    model_domain=model_domain,
                    extra_domain=extra_domain,
                    **kwargs,
                )
            }

        Comodel = self.env[field.comodel_name].with_context(hierarchical_naming=False)
        field_names = ["display_name"]
        group_by = kwargs.get("group_by")
        limit = kwargs.get("limit")
        if group_by:
            group_by_field = Comodel._fields[group_by]

            field_names.append(group_by)

            if group_by_field.type == "many2one":

                def group_id_name(value):
                    return value or (False, self.env._("Not Set"))

            elif group_by_field.type == "selection":
                desc = Comodel.fields_get([group_by])[group_by]
                group_by_selection = dict(desc["selection"])
                group_by_selection[False] = self.env._("Not Set")

                def group_id_name(value):
                    return value, group_by_selection.get(value, value)

            else:

                def group_id_name(value):
                    return (value, value) if value else (False, self.env._("Not Set"))

        comodel_domain = kwargs.get("comodel_domain", [])
        enable_counters = kwargs.get("enable_counters")
        expand = kwargs.get("expand")

        if field.type == "many2many":
            if not expand:
                domain_image = self._search_panel_get_domain_image(
                    field_name, model_domain, limit=limit
                )
                image_element_ids = list(domain_image.keys())
                comodel_domain = AND(
                    [
                        comodel_domain,
                        [("id", "in", image_element_ids)],
                    ]
                )

            comodel_records = Comodel.search_read(
                comodel_domain, field_names, limit=limit
            )
            if limit and len(comodel_records) == limit:
                return {"error_msg": str(SEARCH_PANEL_ERROR_MESSAGE)}

            group_domain = kwargs.get("group_domain")

            count_image = None
            if enable_counters and not (group_by and group_domain):
                count_domain = AND([model_domain, extra_domain])
                count_image = self._search_panel_get_domain_image(
                    field_name,
                    count_domain,
                    set_count=True,
                )

            group_count_images = {}
            if enable_counters and count_image is None:
                for record in comodel_records:
                    group_key = json_dumps(group_id_name(record[group_by])[0])
                    if group_key not in group_count_images:
                        count_domain = AND(
                            [
                                model_domain,
                                extra_domain,
                                group_domain.get(group_key, []),
                            ]
                        )
                        group_count_images[group_key] = (
                            self._search_panel_get_domain_image(
                                field_name, count_domain, set_count=True
                            )
                        )

            field_range = []
            for record in comodel_records:
                record_id = record["id"]
                values = {
                    "id": record_id,
                    "display_name": record["display_name"],
                }
                if group_by:
                    group_id, group_name = group_id_name(record[group_by])
                    values["group_id"] = group_id
                    values["group_name"] = group_name

                if enable_counters:
                    image = (
                        count_image
                        if count_image is not None
                        else group_count_images[json_dumps(group_id)]
                    )
                    image_element = image.get(record_id)
                    values["__count"] = image_element["__count"] if image_element else 0
                field_range.append(values)

            return {
                "values": field_range,
            }

        if field.type == "many2one":
            if enable_counters or not expand:
                extra_domain = AND(
                    [
                        extra_domain,
                        kwargs.get("group_domain", []),
                    ]
                )
                domain_image = self._search_panel_get_field_image(
                    field_name,
                    model_domain=model_domain,
                    extra_domain=extra_domain,
                    only_counters=expand,
                    set_limit=limit and not (expand or group_by or comodel_domain),
                    **kwargs,
                )

            if not (expand or group_by or comodel_domain):
                values = list(domain_image.values())
                if limit and len(values) == limit:
                    return {"error_msg": str(SEARCH_PANEL_ERROR_MESSAGE)}
                return {
                    "values": values,
                }

            if not expand:
                image_element_ids = list(domain_image.keys())
                comodel_domain = AND(
                    [
                        comodel_domain,
                        [("id", "in", image_element_ids)],
                    ]
                )
            comodel_records = Comodel.search_read(
                comodel_domain, field_names, limit=limit
            )
            if limit and len(comodel_records) == limit:
                return {"error_msg": str(SEARCH_PANEL_ERROR_MESSAGE)}

            field_range = []
            for record in comodel_records:
                record_id = record["id"]
                values = {
                    "id": record_id,
                    "display_name": record["display_name"],
                }

                if group_by:
                    group_id, group_name = group_id_name(record[group_by])
                    values["group_id"] = group_id
                    values["group_name"] = group_name

                if enable_counters:
                    image_element = domain_image.get(record_id)
                    values["__count"] = image_element["__count"] if image_element else 0

                field_range.append(values)

            return {
                "values": field_range,
            }
        raise ValueError(
            f"Unsupported field type {field.type!r} for search panel multi-range"
        )
