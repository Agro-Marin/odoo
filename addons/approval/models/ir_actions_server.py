from odoo import models

from . import approval_trace as trace


class IrActionsServer(models.Model):
    _inherit = "ir.actions.server"

    def run(self):
        """Consult approval bindings before running, on the server.

        web_studio gated a server action only in the browser: the client asked for
        approval before executing, so any RPC caller ran the action unchecked. The
        gate here holds for every caller, with the records the action targets as
        its subject, and the caller's elevation measured on this environment before
        `run` itself switches to sudo.
        """
        Binding = self.env["approval.binding"]
        if not self or not Binding._enabled():
            return super().run()
        result = False
        for action in self:
            bindings = Binding._bindings_for_action(action.id)
            records = action._get_records_targeted(action) if bindings else None
            trace.BINDING.event(
                "action_run",
                action=action.id,
                bindings=bindings.ids,
                records=records.ids if records else None,
            )
            if not bindings or not records:
                result = super(IrActionsServer, action).run()
                continue
            result = Binding._gate(
                records,
                bindings,
                action.name,
                lambda runnable, action=action: super(
                    IrActionsServer,
                    action.with_context(
                        active_model=runnable._name,
                        active_ids=runnable.ids,
                        active_id=runnable[:1].id,
                    ),
                ).run(),
            )
        return result
