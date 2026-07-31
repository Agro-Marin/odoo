from odoo import api, models
from odoo.fields import Domain


class IrEmbeddedActions(models.Model):
    """Embedded action enforcing documents pinning access rights."""

    _inherit = "ir.embedded.actions"

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> IrEmbeddedActions:
        """Create embedded actions after checking documents pinning rights."""
        records = super().create(vals_list)
        records._check_documents_can_pin()
        return records

    def write(self, vals: dict) -> bool:
        """Write embedded actions after checking documents pinning rights."""
        self._check_documents_can_pin()
        ret = super().write(vals)
        self._check_documents_can_pin()
        return ret

    def _check_documents_can_pin(self) -> None:
        """Check that the current user can edit/create the embedded action."""
        to_check = self.filtered(
            lambda a: (
                a.parent_action_id
                == self.env.ref("documents.document_action", raise_if_not_found=False)
                and a.parent_res_model == "documents.document"
            ),
        )
        if to_check:
            folders = self.env["documents.document"].browse(
                to_check.mapped("parent_res_id")
            )
            folders.check_access("write")

    @api.model
    def _get_documents_embed_base_domain(self) -> list:
        return [
            ("parent_action_id", "=", self.env.ref("documents.document_action").id),
            ("action_id.type", "=", "ir.actions.server"),
            ("parent_res_model", "=", "documents.document"),
        ]

    @api.autovacuum
    def _gc_documents_obsolete(self) -> tuple[int, bool]:
        """Drop embedded actions that can never be executed (child actions).

        ``restrict_to_user_groups=False`` is the whole point: obsolescence is a
        property of the action, not of whoever happens to be running the
        vacuum. With the group clause left in, an action restricted to a group
        the vacuum user lacks looked non-embeddable, and every folder that had
        it pinned lost that pin -- silently, permanently, and only on the
        databases where the vacuum ran as someone without the group.

        Reports the autovacuum ``(removed, maybe more)`` contract so a backlog
        is drained across runs rather than in one unbounded delete.
        """
        embeddable = self.env["ir.actions.server"]._search(
            self.env["documents.document"]._get_embeddable_server_action_domain(
                restrict_to_user_groups=False
            )
        )
        limit = 1000
        obsolete = self.search(
            Domain.AND(
                [
                    self._get_documents_embed_base_domain(),
                    [("action_id", "not in", embeddable)],
                ]
            ),
            limit=limit,
        )
        removed = len(obsolete)
        obsolete.unlink()
        return removed, removed == limit
