from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools import frozendict

from . import approval_trace as trace


class ApprovalAuthorityLimit(models.Model):
    _name = "approval.authority.limit"
    _description = "Approval Authority Limit"
    _order = "grant_id, model_id, verb, amount_max"
    _access_anchors = frozendict(
        {
            "company": "grant_id.company_ids",
            "owner": "user_id",
        }
    )

    grant_id = fields.Many2one(
        comodel_name="res.users.grant",
        string="Authority",
        index=True,
        required=True,
        ondelete="cascade",
        help="The grant the limit qualifies: the limit holds while the grant does, "
        "in the companies the grant is scoped to.",
    )
    user_id = fields.Many2one(related="grant_id.user_id")
    model_id = fields.Many2one(
        comodel_name="ir.model",
        string="Document",
        required=True,
        ondelete="cascade",
    )
    model_name = fields.Char(related="model_id.model")
    verb = fields.Char(
        required=True,
        help="A verb the document declares with an amount (confirm, post...).",
    )
    amount_max = fields.Monetary(
        string="Up To",
        currency_field="currency_id",
        required=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )

    @api.constrains("model_id", "verb")
    def _check_verb(self) -> None:
        for limit in self:
            verb = self.env.registry.model_verbs.get(limit.model_name, {}).get(
                limit.verb
            )
            if verb is None or not verb.amount:
                trace.REFUSAL.event(
                    "limit_on_verb_without_amount",
                    limit=limit.id,
                    model=limit.model_name,
                    verb=limit.verb,
                )
                raise ValidationError(
                    self.env._(
                        "%(model)s declares no verb %(verb)s with an amount, so no "
                        "limit can qualify it.",
                        model=limit.model_name,
                        verb=limit.verb,
                    )
                )

    @api.model
    def _get_user_limits(self, users, model_name: str, verb: str, request) -> dict:
        """The highest live limit each of `users` holds, in the request's currency.

        A limit holds while its grant does, in the companies the grant is scoped to;
        an unscoped grant's limit holds everywhere.
        """
        if not users:
            return {}
        company = request.company_id
        grants = self.env["res.users.grant"]._live_domain()
        limits = self.with_privilege(
            "approval.privilege_walk_authority",
            reason="an approval step walks to the approver whose limit covers it",
        ).search(
            Domain("user_id", "in", users.ids)
            & Domain("model_name", "=", model_name)
            & Domain("verb", "=", verb)
            & Domain("grant_id", "any", grants)
        )
        date = (request.date or request.date_confirmed or fields.Datetime.now()).date()
        highest: dict[int, float] = {}
        for limit in limits:
            grant = limit.grant_id
            if grant.scoped and company not in grant.company_ids:
                continue
            amount = limit.currency_id._convert(
                limit.amount_max,
                request.currency_id or limit.currency_id,
                company or self.env.company,
                date,
            )
            user_id = limit.user_id.id
            highest[user_id] = max(highest.get(user_id, amount), amount)
        trace.ROUTING.event(
            "authority_limits",
            request=request.id,
            model=model_name,
            verb=verb,
            limits=sorted(highest.items()),
        )
        return highest
