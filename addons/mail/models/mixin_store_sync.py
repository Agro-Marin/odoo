from collections import defaultdict
from typing import Any

from odoo import api, models
from odoo.api import ValuesType

from odoo.addons.mail.tools.discuss import Store, StoreFieldSpec


class MixinStoreSync(models.AbstractModel):
    _name = "mixin.store.sync"
    _inherit = ["mixin.bus.listener"]
    _description = "Broadcast the store fields that a write changed"

    def _sync_field_names(self) -> defaultdict[str | None, list[StoreFieldSpec]]:
        return defaultdict(list)

    def _sync_diff_extra_fields(
        self, record: models.Model, diff: list[StoreFieldSpec]
    ) -> list[StoreFieldSpec]:
        return []

    @api.model
    def _get_store_field_name(self, field_description: StoreFieldSpec) -> str:
        if isinstance(field_description, Store.Attr):
            return field_description.field_name
        return field_description

    def _get_store_field_value(
        self, record: models.Model, field_description: StoreFieldSpec
    ) -> Any:
        if isinstance(field_description, Store.Attr):
            if field_description.predicate and not field_description.predicate(record):
                return None
            if isinstance(field_description, Store.Relation):
                return field_description._get_value(record).records
            return field_description._get_value(record)
        return record[field_description]

    def _get_write_sync_field_names(
        self, vals: ValuesType
    ) -> dict[str | None, list[StoreFieldSpec]]:
        vals_keys = set(vals)

        def is_affected(field_description: StoreFieldSpec) -> bool:
            fname = self._get_store_field_name(field_description)
            if fname not in self._fields:
                return True
            seen = set()
            stack = [fname]
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                if cur in vals_keys or cur in ("write_date", "create_date"):
                    return True
                cur_field = self._fields.get(cur)
                if cur_field is None:
                    continue
                stack.extend(
                    dep.split(".", 1)[0] for dep in self.pool.field_depends[cur_field]
                )
            return False

        return {
            subchannel: affected
            for subchannel, field_descriptions in self._sync_field_names().items()
            if (affected := [fd for fd in field_descriptions if is_affected(fd)])
        }

    def _get_sync_values(
        self, record: models.Model, sync_field_names: dict
    ) -> dict[str | None, dict]:
        return {
            subchannel: {
                self._get_store_field_name(field_description): (
                    self._get_store_field_value(record, field_description),
                    field_description,
                )
                for field_description in field_descriptions
            }
            for subchannel, field_descriptions in sync_field_names.items()
        }

    def _prepare_sync_snapshot(
        self, vals: ValuesType, targets: models.Model | None = None
    ) -> tuple[dict, dict]:
        targets = self if targets is None else targets
        sync_field_names = self._get_write_sync_field_names(vals)
        return sync_field_names, {
            record: self._get_sync_values(record, sync_field_names)
            for record in targets
        }

    def _notify_sync_diffs(self, sync_field_names: dict, old_vals: dict) -> None:
        for record, record_old_vals in old_vals.items():
            self._notify_sync_diff(record, sync_field_names, record_old_vals)

    def _notify_sync_diff(
        self, record: models.Model, sync_field_names: dict, old_vals: dict
    ) -> None:
        for subchannel, values in self._get_sync_values(
            record, sync_field_names
        ).items():
            diff = [
                field_description
                for field_name, (value, field_description) in values.items()
                if value != old_vals[subchannel][field_name][0]
            ]
            if not diff:
                continue
            diff += self._sync_diff_extra_fields(record, diff)
            Store(bus_channel=record._bus_channel(), bus_subchannel=subchannel).add(
                record, diff
            ).bus_send()
