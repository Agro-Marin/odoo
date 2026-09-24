from odoo import models

from . import approval_trace as trace


class IrAccessObligation(models.AbstractModel):
    _inherit = "ir.access.obligation"

    def _at_door(self, records, verb, call):
        Binding = self.env["approval.binding"]
        own, configured = Binding._split_verb_bindings(records._name, verb)
        if not own and not configured:
            return super()._at_door(records, verb, call)
        trace.BINDING.event(
            "verb_door",
            model=records._name,
            verb=verb,
            records=records.ids,
            own=own.ids,
            configured=configured.ids,
        )
        run = call
        if configured:

            def run(runnable, call=call):
                return Binding._gate(
                    runnable,
                    configured,
                    verb,
                    lambda ready: Binding._run_admitted(ready, verb, call),
                )

        if own:
            return own._hold_document_at_door(records, verb, run)
        return run(records)

    def _at_checkpoint(self, records, verb):
        Binding = self.env["approval.binding"]
        own, configured = Binding._split_verb_bindings(records._name, verb)
        if configured:
            Binding._enforce_at_checkpoint(records, configured, verb)
        if own:
            own._hold_document_at_checkpoint(records, verb)
        return super()._at_checkpoint(records, verb)
