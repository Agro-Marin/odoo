from odoo import api, models
from odoo.fields import Domain
from odoo.libs.debug_log import DebugLog
from odoo.libs.sql import escape_psql

_debug = DebugLog(__name__)


class StockPickingTypeSequence(models.Model):
    _inherit = "stock.picking.type"

    def _prepare_sequence_vals(self):
        self.check_singleton()
        warehouse = self.warehouse_id
        if not warehouse:
            return {
                "name": self.env._("Sequence %(code)s", code=self.sequence_code),
                "prefix": self.sequence_code,
                "padding": 5,
                "company_id": self.company_id.id,
            }
        code = warehouse._normalize_code(warehouse.code)
        return {
            "name": self.env._(
                "%(warehouse)s Sequence %(code)s",
                warehouse=warehouse.name,
                code=self.sequence_code,
            ),
            "prefix": "%s/%s/" % (code, self.sequence_code),
            "padding": 5,
            "company_id": self.company_id.id,
        }

    @_debug.perf.timed
    def _update_reference_sequences(self, only=None):
        missing = self.browse()
        for picking_type in self:
            if not picking_type.sequence_code:
                continue
            if not picking_type.sequence_id:
                missing |= picking_type
                continue
            wanted = picking_type._prepare_sequence_vals()
            if only is not None:
                wanted = {name: value for name, value in wanted.items() if name in only}
            sequence = picking_type.sequence_id.sudo()
            changed = {
                name: value
                for name, value in wanted.items()
                if sequence._fields[name].convert_to_write(sequence[name], sequence)
                != value
            }
            if changed:
                if _debug.lifecycle.enabled:
                    _debug.lifecycle(
                        "sequence_updated",
                        picking_type=picking_type.id,
                        sequence=sequence.id,
                        keys=sorted(changed),
                    )
                sequence.write(changed)
        if missing:
            _debug.lifecycle("reference_sequences_created", picking_types=missing)
            sequences = (
                self.env["ir.sequence"]
                .sudo()
                .create(
                    [picking_type._prepare_sequence_vals() for picking_type in missing]
                )
            )
            for picking_type, sequence in zip(missing, sequences, strict=True):
                picking_type.sequence_id = sequence.id

    @api.model
    def _remove_orphaned_sequences(self, sequences):
        if not sequences:
            return
        still_referenced = (
            self.with_context(active_test=False)
            .search([("sequence_id", "in", sequences.ids)])
            .sequence_id
        )
        if _debug.lifecycle.enabled:
            _debug.lifecycle(
                "orphaned_sequences_removed",
                removed=sequences - still_referenced,
                kept=still_referenced,
            )
        (sequences - still_referenced).sudo().unlink()

    def _get_domain_sequence_scope(self):
        self.check_singleton()
        return Domain("company_id", "=", self.company_id.id) & Domain(
            "warehouse_id", "=", self.warehouse_id.id or False
        )

    def _get_clashing_picking_type(self):
        self.check_singleton()
        domain = self._get_domain_sequence_scope() & Domain(
            "sequence_code", "=", self.sequence_code
        )
        if self._origin.id:
            domain &= Domain("id", "!=", self._origin.id)
        return (
            self.env["stock.picking.type"]
            .with_context(active_test=False)
            .search(domain, limit=1)
        )

    def _get_unique_sequence_code(self):
        self.check_singleton()
        pattern = escape_psql(self.sequence_code)
        taken = set(
            self.env["stock.picking.type"]
            .with_context(active_test=False)
            .search(
                self._get_domain_sequence_scope()
                & Domain("sequence_code", "=like", f"{pattern}%")
            )
            .mapped("sequence_code")
        )
        for index in range(2, len(taken) + 3):
            candidate = f"{self.sequence_code}{index}"
            if candidate not in taken:
                return candidate
        return self.sequence_code
