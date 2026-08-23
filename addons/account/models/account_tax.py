import ast
import math
from collections import defaultdict, deque

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.libs.numbers import float_is_zero, float_round
from odoo.tools import SQL, frozendict, groupby


def _group_everything_together(base_line, tax_data):
    return True


def _group_by_tax(base_line, tax_data):
    return str(tax_data["tax"].id) if tax_data else None


class AccountTaxGroup(models.Model):
    _inherit = "account.tax.group"

    tax_payable_account_id = fields.Many2one(
        comodel_name="account.account",
        check_company=True,
        string="Tax Payable Account",
        help="Tax current account used as a counterpart to the Tax Closing Entry when in favor of the authorities.",
    )
    tax_receivable_account_id = fields.Many2one(
        comodel_name="account.account",
        check_company=True,
        string="Tax Receivable Account",
        help="Tax current account used as a counterpart to the Tax Closing Entry when in favor of the company.",
    )
    advance_tax_payment_account_id = fields.Many2one(
        comodel_name="account.account",
        check_company=True,
        string="Tax Advance Account",
        help="Downpayments posted on this account will be considered by the Tax Closing Entry.",
    )


class AccountTax(models.Model):
    _inherit = "account.tax"


    fiscal_position_ids = fields.Many2many(
        comodel_name="account.fiscal.position",
        relation="account_fiscal_position_account_tax_rel",
        column1="account_tax_id",
        column2="account_fiscal_position_id",
    )
    original_tax_ids = fields.Many2many(
        comodel_name="account.tax",
        relation="account_tax_alternatives",
        column1="dest_tax_id",
        column2="src_tax_id",
        string="Replaces",
        domain="""[
            ('type_tax_use', '=', type_tax_use),
            ('is_domestic', '=', True),
        ]""",
        ondelete="cascade",
        help="List of taxes to replace when applying any of the stipulated fiscal positions.",
    )
    replacing_tax_ids = fields.Many2many(
        comodel_name="account.tax",
        relation="account_tax_alternatives",
        column1="src_tax_id",
        column2="dest_tax_id",
        readonly=True,
        string="Replaced by",
    )
    display_alternative_taxes_field = fields.Boolean(
        compute="_compute_display_alternative_taxes_field"
    )
    is_domestic = fields.Boolean(
        compute="_compute_is_domestic", store=True, precompute=True
    )
    analytic = fields.Boolean(
        string="Include in Analytic Cost",
        help="If set, the amount computed by this tax will be assigned to the same analytic account as the invoice line (if any)",
    )
    hide_tax_exigibility = fields.Boolean(
        string="Hide Use Cash Basis Option",
        related="company_id.tax_exigibility",
        readonly=True,
    )
    tax_exigibility = fields.Selection(
        [
            ("on_invoice", "Based on Invoice"),
            ("on_payment", "Based on Payment"),
        ],
        string="Tax Exigibility",
        default="on_invoice",
        help="Based on Invoice: the tax is due as soon as the invoice is validated.\n"
        "Based on Payment: the tax is due as soon as the payment of the invoice is received.",
    )
    cash_basis_transition_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cash Basis Transition Account",
        check_company=True,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
        help="Account used to transition the tax amount for cash basis taxes. It will contain the tax amount as long as the original invoice has not been reconciled ; at reconciliation, this amount cancelled on this account and put on the regular tax account.",
    )
    is_used = fields.Boolean(string="Tax used", compute="_compute_is_used")
    repartition_lines_str = fields.Char(
        string="Repartition Lines",
        tracking=True,
        compute="_compute_repartition_lines_str",
    )
    invoice_legal_notes = fields.Html(
        string="Legal Notes",
        translate=True,
        help="Legal mentions that have to be printed on the invoices.",
    )

    @api.constrains("tax_exigibility", "cash_basis_transition_account_id")
    def _constrains_cash_basis_transition_account(self):
        for record in self:
            if (
                record.tax_exigibility == "on_payment"
                and not record.cash_basis_transition_account_id.reconcile
                and not self.env.context.get("chart_template_load")
            ):
                raise ValidationError(
                    self.env._(
                        "The cash basis transition account needs to allow reconciliation."
                    )
                )

    @api.model
    @api.readonly
    def name_search(self, name="", domain=None, operator="ilike", limit=100):
        domain = Domain(domain or Domain.TRUE)
        if "search_default_domestictax" in self.env.context:
            domain &= Domain("fiscal_position_ids", "=", False) | Domain(
                "fiscal_position_ids.is_domestic", "=", True
            )
        if fp_id := self.env.context.get("dynamic_fiscal_position_id"):
            domain &= Domain("fiscal_position_ids", "in", [False, int(fp_id)])
        if self.env.context.get("hide_original_tax_ids") and fp_id:
            domain &= Domain("replacing_tax_ids", "not any", domain) | Domain.custom(
                to_sql=lambda model, alias, query: SQL(
                    "EXISTS (SELECT 1 FROM %s WHERE %s = %s AND %s = %s)",
                    SQL.identifier("account_tax_alternatives"),
                    SQL.identifier("src_tax_id"),
                    SQL.identifier(alias, "id"),
                    SQL.identifier("dest_tax_id"),
                    SQL.identifier(alias, "id"),
                ),
            )
        return super().name_search(name, domain, operator, limit)

    def _get_used_tax_ids(self, tax_ids):
        # Modules that hold taxes on their own records extend this. Return the subset
        # of `tax_ids` this layer can see in use; do NOT modify `tax_ids` itself --
        # every caller in the chain still needs the full candidate set.
        return set()

    @api.depends(
        "company_id", "company_id.domestic_fiscal_position_id", "fiscal_position_ids"
    )
    def _compute_is_domestic(self):
        for tax in self:
            tax.is_domestic = (
                not tax.fiscal_position_ids
                or tax.company_id.domestic_fiscal_position_id in tax.fiscal_position_ids
            )

    @api.depends(
        "fiscal_position_ids",
        "original_tax_ids",
        "company_id.domestic_fiscal_position_id",
    )
    def _compute_display_alternative_taxes_field(self):
        for tax in self:
            tax.display_alternative_taxes_field = (
                tax.original_tax_ids
                or (
                    tax.fiscal_position_ids
                    and tax.fiscal_position_ids._origin
                    != tax.company_id.domestic_fiscal_position_id
                )
            )

    def _compute_is_used(self):
        used_taxes = set()

        if self.ids:
            self.env["account.move.line"].flush_model(["tax_ids"])
            used_taxes.update(
                id_
                for [id_] in self.env.execute_query(
                    SQL(
                        """
                        SELECT id
                        FROM account_tax
                        WHERE EXISTS(
                            SELECT 1
                            FROM account_move_line_account_tax_rel AS line
                            WHERE account_tax.id = line.account_tax_id
                        )
                        AND id = ANY(%s)
                        """,
                        list(self.ids),
                    )
                )
            )
            taxes_to_compute = set(self.ids) - used_taxes

            if taxes_to_compute:
                self.env["account.reconcile.model.line"].flush_model(["tax_ids"])
                used_taxes.update(
                    id_
                    for [id_] in self.env.execute_query(
                        SQL(
                            """
                            SELECT id
                            FROM account_tax
                            WHERE EXISTS(
                                SELECT 1
                                FROM account_reconcile_model_line_account_tax_rel AS reco
                                WHERE account_tax.id = reco.account_tax_id
                            )
                            AND id = ANY(%s)
                            """,
                            list(taxes_to_compute),
                        )
                    )
                )
                taxes_to_compute -= used_taxes

            if taxes_to_compute:
                used_taxes.update(self._get_used_tax_ids(taxes_to_compute))

        for tax in self:
            tax.is_used = tax._origin.id in used_taxes

    @api.ondelete(at_uninstall=False)
    def unlink_except_tax_used(self):
        self.invalidate_recordset(["is_used"])
        if any(self.mapped("is_used")):
            raise ValidationError(
                self.env._(
                    "You cannot delete taxes that are currently in use. Consider archiving them instead."
                )
            )

    @api.model
    def _import_retrieve_tax_from_invoice_predictive(self, tax_values):
        if "payment_state_before_switch" not in self.env["account.move"]._fields:
            return None

        invoice_predictive = tax_values.get("invoice_predictive")
        if not invoice_predictive:
            return None

        def search_predictive(values):
            domain = values["static_domain"]
            predicted_tax_ids = self.env["account.move.line"]._predict_specific_tax(
                move=invoice_predictive["invoice"],
                name=invoice_predictive["name"],
                partner=invoice_predictive["partner"],
                amount_type=tax_values["amount_type"],
                amount=tax_values["amount"],
                type_tax_use=tax_values["type_tax_use"],
            )
            return (
                self.env["account.tax"]
                .browse(predicted_tax_ids)
                .filtered_domain(domain)[:1]
            )

        return {
            "criteria": [
                {
                    "search_method": search_predictive,
                    "cache_key": frozendict(invoice_predictive),
                }
            ],
        }

    @api.model
    def _import_retrieve_tax_from_price_include_exclude(self, tax_values):
        price_include = tax_values.get("price_include")
        fiscal_position = tax_values.get("fiscal_position")

        fpos_domain = Domain.TRUE
        if fiscal_position:
            fpos_domain = Domain("fiscal_position_ids", "=", fiscal_position.id)
            if fiscal_position.is_domestic:
                fpos_domain |= Domain("fiscal_position_ids", "=", False)

        criteria = []
        for wanted in (False, True):
            if (wanted and price_include is False) or (not wanted and price_include):
                continue
            include_domain = Domain("price_include", "=", wanted)
            if fiscal_position:
                criteria.append({"domain": include_domain & fpos_domain})
            criteria.append({"domain": include_domain})

        return {"criteria": criteria}

    @api.model
    def _import_retrieve_tax(self, search_plan, company, tax_values_list):
        cache = self.env.cr.cache.setdefault("retrieved_tax_map", {}).setdefault(
            company.id, {}
        )

        static_domain = Domain(self._check_company_domain(company))
        for tax_values in tax_values_list:
            tax_domain = (
                Domain("amount_type", "=", tax_values["amount_type"])
                & Domain("type_tax_use", "=", tax_values["type_tax_use"])
                & Domain("amount", "=", tax_values["amount"])
            )
            if "invoice_predictive" in tax_values:
                tax_domain &= Domain(
                    "country_id",
                    "=",
                    tax_values["invoice_predictive"]["invoice"].tax_country_id.id,
                )
            orders = ["sequence", "id"]
            if name := tax_values.get("name"):
                tax_domain &= Domain("name", "=", name)
            if tax_exigibility := tax_values.get("tax_exigibility"):
                tax_domain &= Domain("tax_exigibility", "=", tax_exigibility)
            if (
                ubl_cii_tax_category_code := tax_values.get("ubl_cii_tax_category_code")
            ) and "ubl_cii_tax_category_code" in self._fields:
                tax_domain &= Domain(
                    "ubl_cii_tax_category_code",
                    "in",
                    (ubl_cii_tax_category_code, False),
                )
                orders.insert(0, "ubl_cii_tax_category_code")

            for plan in search_plan:
                tax = None
                plan_values = plan(tax_values)
                if not plan_values:
                    continue

                for criteria in plan_values["criteria"]:
                    domain = criteria.get("domain")
                    search_method = criteria.get("search_method")
                    if domain:
                        domain = tax_domain & Domain(domain)
                        cache_key = repr(domain.optimize(self.env["account.tax"]))
                    else:
                        cache_key = criteria.get("cache_key")
                        if cache_key:
                            cache_key = (cache_key, str(tax_domain))

                    if cache_key and cache_key in cache:
                        if tax := cache[cache_key]:
                            tax_values["tax"] = tax
                            break
                        continue

                    if domain:
                        full_domain = static_domain & Domain(domain)
                        tax = self.search(full_domain, order=",".join(orders), limit=1)
                    elif search_method:
                        tax = search_method(
                            {
                                **criteria,
                                "static_domain": tax_domain & static_domain,
                            }
                        )

                    if cache_key:
                        cache[cache_key] = tax
                    if tax:
                        tax_values["tax"] = tax
                        break

                if tax:
                    break

    @api.depends(
        "repartition_line_ids.account_id",
        "repartition_line_ids.sequence",
        "repartition_line_ids.factor_percent",
        "repartition_line_ids.use_in_tax_closing",
        "repartition_line_ids.tag_ids",
        "invoice_repartition_line_ids",
        "refund_repartition_line_ids",
    )
    def _compute_repartition_lines_str(self):
        for tax in self:
            repartition_line_info = {}
            invoice_sequence = 0
            refund_sequence = 0
            for repartition_line in tax.repartition_line_ids.sorted(
                key=lambda r: (r.document_type, r.sequence)
            ):
                sequence = (
                    (invoice_sequence := invoice_sequence + 1)
                    if repartition_line.document_type == "invoice"
                    else (refund_sequence := refund_sequence + 1)
                )
                repartition_line_info[(repartition_line.document_type, sequence)] = {
                    "factor_percent": repartition_line.factor_percent,
                    "account": repartition_line.account_id.id or None,
                    "tax_grids": repartition_line.tag_ids.mapped("name") or None,
                    "use_in_tax_closing": bool(repartition_line.use_in_tax_closing),
                }
            tax.repartition_lines_str = str(repartition_line_info)

    def _repartition_line_field_label(self, key):
        return {
            "factor_percent": self.env._("Factor Percent"),
            "account": self.env._("Account"),
            "tax_grids": self.env._("Tax Grids"),
            "use_in_tax_closing": self.env._("Use in tax closing"),
        }.get(key, key)

    def _repartition_line_field_value(self, key, value):
        if value is None:
            return self.env._("None")
        if isinstance(value, bool):
            return self.env._("True") if value else self.env._("False")
        if key == "account" and isinstance(value, int):
            return self.env["account.account"].browse(value).display_name
        return value

    def _prepare_repartition_lines_log_body(self, old_values_str, new_values_str):
        self.ensure_one()
        old_line_values_dict = ast.literal_eval(old_values_str or "{}")
        new_line_values_dict = ast.literal_eval(new_values_str)

        modified_lines = [
            (line, old_line_values_dict[line], new_line_values_dict[line])
            for line in old_line_values_dict.keys() & new_line_values_dict.keys()
        ]
        added_and_deleted_lines = [
            (line, self.env._("Removed"), old_line_values_dict[line])
            if line in old_line_values_dict
            else (line, self.env._("New"), new_line_values_dict[line])
            for line in old_line_values_dict.keys() ^ new_line_values_dict.keys()
        ]

        fragments = []
        for (document_type, sequence), old_value, new_value in modified_lines:
            diff_keys = [
                key
                for key in old_value
                if key in new_value and old_value[key] != new_value[key]
            ]
            if diff_keys:
                body = Markup(
                    "<b>{type}</b> {rep} {seq}:<ul class='mb-0 ps-4'>{changes}</ul>"
                ).format(
                    type=document_type.capitalize(),
                    rep=self.env._("repartition line"),
                    seq=sequence,
                    changes=Markup().join(
                        [
                            Markup("""
                            <li>
                                <span class='o-mail-Message-trackingOld me-1 px-1 text-muted fw-bold'>{old}</span>
                                <i class='o-mail-Message-trackingSeparator fa-solid fa-right-long mx-1 text-600'/>
                                <span class='o-mail-Message-trackingNew me-1 fw-bold text-info'>{new}</span>
                                <span class='o-mail-Message-trackingField ms-1 fst-italic text-muted'>({diff})</span>
                            </li>
                        """).format(
                                old=self._repartition_line_field_value(
                                    diff_key, old_value[diff_key]
                                ),
                                new=self._repartition_line_field_value(
                                    diff_key, new_value[diff_key]
                                ),
                                diff=self._repartition_line_field_label(diff_key),
                            )
                            for diff_key in diff_keys
                        ]
                    ),
                )
                fragments.append(body)

        for (document_type, sequence), operation, value in added_and_deleted_lines:
            body = Markup(
                "<b>{op} {type}</b> {rep} {seq}:<ul class='mb-0 ps-4'>{changes}</ul>"
            ).format(
                op=operation,
                type=document_type.capitalize(),
                rep=self.env._("repartition line"),
                seq=sequence,
                changes=Markup().join(
                    [
                        Markup("""
                        <li>
                            <span class='o-mail-Message-trackingNew me-1 fw-bold text-info'>{value}</span>
                            <span class='o-mail-Message-trackingField ms-1 fst-italic text-muted'>({diff})</span>
                        </li>
                    """).format(
                            value=self._repartition_line_field_value(key, value[key]),
                            diff=self._repartition_line_field_label(key),
                        )
                        for key in value
                    ]
                ),
            )
            fragments.append(body)

        return Markup().join(fragments)

    def _message_log_batch(self, bodies, **kwargs):
        tracking_values = kwargs.get("tracking_values") or {}
        snapshot_field_id = (
            self.env["ir.model.fields"]._get("account.tax", "repartition_lines_str").id
        )

        loggable_ids = []
        kept_per_id = dict(tracking_values)
        repartition_bodies = {}
        for tax in self:
            if not tax.is_used:
                kept_per_id.pop(tax.id, None)
                continue

            kept = []
            fragments = []
            for command in tracking_values.get(tax.id) or []:
                if command[2]["field_id"] == snapshot_field_id:
                    fragments.append(
                        tax._prepare_repartition_lines_log_body(
                            command[2]["old_value_char"],
                            command[2]["new_value_char"],
                        )
                    )
                else:
                    kept.append(command)
            kept_per_id[tax.id] = kept
            if body := Markup().join(fragments):
                repartition_bodies[tax.id] = body

            if kept or bodies.get(tax.id) or tax.id in repartition_bodies:
                loggable_ids.append(tax.id)

        if not loggable_ids:
            return self.env["mail.message"]
        return super(AccountTax, self.browse(loggable_ids))._message_log_batch(
            {
                id_: self._concat_log_bodies(
                    bodies.get(id_), repartition_bodies.get(id_)
                )
                for id_ in loggable_ids
            },
            **{**kwargs, "tracking_values": kept_per_id},
        )

    @api.model
    def _concat_log_bodies(self, *bodies):
        present = [body for body in bodies if body]
        if not present:
            return ""
        if len(present) == 1:
            return present[0]
        return Markup().join(Markup(body) for body in present)

    def _default_repartition_lines(self, document_type):
        return [
            Command.create(
                {
                    "document_type": document_type,
                    "repartition_type": repartition_type,
                    "tag_ids": [],
                }
            )
            for repartition_type in ("base", "tax")
        ]

    @api.depends("company_id")
    def _compute_invoice_repartition_line_ids(self):
        for tax in self:
            if not tax.invoice_repartition_line_ids:
                tax.invoice_repartition_line_ids = tax._default_repartition_lines(
                    "invoice"
                )

    @api.depends("company_id")
    def _compute_refund_repartition_line_ids(self):
        for tax in self:
            if not tax.refund_repartition_line_ids:
                tax.refund_repartition_line_ids = tax._default_repartition_lines(
                    "refund"
                )

    @api.constrains("company_id")
    def _check_company_consistency(self):
        if self.env.context.get("from_account_tax_creation") is True:
            return
        for company, taxes in groupby(self, lambda tax: tax.company_id):
            if self.env["account.move.line"].search_count(
                [
                    "|",
                    ("tax_line_id", "in", [tax.id for tax in taxes]),
                    ("tax_ids", "in", [tax.id for tax in taxes]),
                    "!",
                    ("company_id", "child_of", company.id),
                ],
                limit=1,
            ):
                raise UserError(
                    self.env._(
                        "You can't change the company of your tax since there are some journal items linked to it."
                    )
                )

    @api.model
    def _prepare_base_line_for_taxes_computation(self, record, **kwargs):
        base_line = super()._prepare_base_line_for_taxes_computation(record, **kwargs)
        if base_line["account_id"] is False:
            base_line["account_id"] = self._get_base_line_field_value_from_record(
                record, "account_id", kwargs, self.env["account.account"]
            )
        return base_line

    @api.model
    def _prepare_tax_line_for_taxes_computation(self, record, **kwargs):
        def load(field, fallback):
            return self._get_base_line_field_value_from_record(
                record, field, kwargs, fallback
            )

        currency = (
            load("currency_id", None)
            or load("company_currency_id", None)
            or load("company_id", self.env["res.company"]).currency_id
            or self.env["res.currency"]
        )

        return {
            **kwargs,
            "record": record,
            "id": load("id", 0),
            "tax_repartition_line_id": load(
                "tax_repartition_line_id", self.env["account.tax.repartition.line"]
            ),
            "group_tax_id": load("group_tax_id", self.env["account.tax"]),
            "tax_ids": load("tax_ids", self.env["account.tax"]),
            "tax_tag_ids": load("tax_tag_ids", self.env["account.account.tag"]),
            "currency_id": currency,
            "partner_id": load("partner_id", self.env["res.partner"]),
            "account_id": load("account_id", self.env["account.account"]),
            "analytic_distribution": load("analytic_distribution", None),
            "sign": load("sign", 1.0),
            "amount_currency": load("amount_currency", 0.0),
            "balance": load("balance", 0.0),
        }

    @api.model
    def _prepare_base_line_grouping_key(self, base_line):
        return {
            "partner_id": base_line["partner_id"].id,
            "currency_id": base_line["currency_id"].id,
            "analytic_distribution": base_line["analytic_distribution"],
            "account_id": base_line["account_id"].id,
            "tax_ids": [Command.set(base_line["tax_ids"].ids)],
        }

    def _prepare_base_line_tax_repartition_grouping_key(
        self, base_line, base_line_grouping_key, tax_data, tax_rep_data
    ):
        tax = tax_data["tax"]
        tax_rep = tax_rep_data["tax_rep"]
        return {
            **base_line_grouping_key,
            "tax_repartition_line_id": tax_rep.id,
            "partner_id": base_line["partner_id"].id,
            "currency_id": base_line["currency_id"].id,
            "group_tax_id": tax_data["group"].id,
            "analytic_distribution": (
                base_line_grouping_key["analytic_distribution"]
                if tax.analytic or not tax_rep.use_in_tax_closing
                else False
            ),
            "account_id": tax_rep_data["account"].id
            or base_line_grouping_key["account_id"],
            "tax_ids": [Command.set(tax_rep_data["taxes"].ids)],
            "tax_tag_ids": [Command.set(tax_rep_data["tax_tags"].ids)],
            "__keep_zero_line": False,
        }

    def _prepare_tax_line_repartition_grouping_key(self, tax_line):
        return {
            "tax_repartition_line_id": tax_line["tax_repartition_line_id"].id,
            "partner_id": tax_line["partner_id"].id,
            "currency_id": tax_line["currency_id"].id,
            "group_tax_id": tax_line["group_tax_id"].id,
            "analytic_distribution": tax_line["analytic_distribution"],
            "account_id": tax_line["account_id"].id,
            "tax_ids": [Command.set(tax_line["tax_ids"].ids)],
            "tax_tag_ids": [Command.set(tax_line["tax_tag_ids"].ids)],
        }

    def _get_repartition_lines_by_kind(self, is_refund, cache=None):
        self.ensure_one()
        key = (self, is_refund)
        if cache is not None and key in cache:
            return cache[key]

        lines = (
            self.refund_repartition_line_ids
            if is_refund
            else self.invoice_repartition_line_ids
        )
        by_kind = {
            "base": lines.filtered(lambda x: x.repartition_type == "base"),
            "tax": lines.filtered(
                lambda x: x.repartition_type == "tax" and x.factor >= 0.0
            ),
            "reverse_charge": lines.filtered(
                lambda x: x.repartition_type == "tax" and x.factor < 0.0
            ),
        }
        if cache is not None:
            cache[key] = by_kind
        return by_kind

    def _add_accounting_data_to_base_line_tax_details(
        self,
        base_line,
        company,
        include_caba_tags=False,
        repartition_cache=None,
        rounded=True,
    ):
        is_refund = base_line["is_refund"]
        product = base_line["product_id"]

        taxes_data = base_line["tax_details"]["taxes_data"]
        base_line["tax_tag_ids"] = self.env["account.account.tag"]
        product_tags = self.env["account.account.tag"]
        if product:
            product_tags = product.sudo().account_tag_ids
            base_line["tax_tag_ids"] |= product_tags

        for tax_data in taxes_data:
            tax = tax_data["tax"]
            reps_by_kind = tax._get_repartition_lines_by_kind(
                is_refund, repartition_cache
            )

            if not tax_data["is_reverse_charge"] and (
                include_caba_tags or tax.tax_exigibility == "on_invoice"
            ):
                base_line["tax_tag_ids"] |= reps_by_kind["base"].tag_ids

            if tax_data["is_reverse_charge"]:
                tax_reps = reps_by_kind["reverse_charge"]
                tax_rep_sign = -1.0
            else:
                tax_reps = reps_by_kind["tax"]
                tax_rep_sign = 1.0

            self._add_tax_repartition_amounts(
                base_line,
                tax_data,
                tax_reps,
                tax_rep_sign,
                company,
                include_caba_tags=include_caba_tags,
                rounded=rounded,
            )

        self._add_tax_repartition_tags_and_grouping_keys(
            base_line,
            product_tags,
            include_caba_tags=include_caba_tags,
            repartition_cache=repartition_cache,
        )

    def _add_tax_repartition_amounts(
        self,
        base_line,
        tax_data,
        tax_reps,
        tax_rep_sign,
        company,
        include_caba_tags=False,
        rounded=True,
    ):
        # `rounded` says whether _round_base_lines_tax_details has already run over
        # `tax_data`. It has to be told: before that pass tax_amount still holds the
        # foreign-currency figure the computation produced, and the rounded
        # *_currency keys do not exist at all.
        currency = base_line["currency_id"]
        company_currency = company.currency_id
        amount_prefix = "" if rounded else "raw_"
        tax_amount_currency = tax_data[f"{amount_prefix}tax_amount_currency"]
        tax_amount = tax_data[f"{amount_prefix}tax_amount"]

        total_tax_rep_amounts = {"tax_amount_currency": 0.0, "tax_amount": 0.0}
        tax_reps_data = tax_data["tax_reps_data"] = []
        for tax_rep in tax_reps:
            tax_rep_data = {
                "tax_rep": tax_rep,
                "tax_amount_currency": currency.round(
                    tax_amount_currency * tax_rep.factor * tax_rep_sign
                ),
                "tax_amount": company_currency.round(
                    tax_amount * tax_rep.factor * tax_rep_sign
                ),
                "account": tax_rep._get_aml_target_tax_account(
                    force_caba_exigibility=include_caba_tags
                )
                or base_line["account_id"],
            }
            total_tax_rep_amounts["tax_amount_currency"] += tax_rep_data[
                "tax_amount_currency"
            ]
            total_tax_rep_amounts["tax_amount"] += tax_rep_data["tax_amount"]
            tax_reps_data.append(tax_rep_data)

        sorted_tax_reps_data = sorted(
            tax_reps_data,
            key=lambda tax_rep: (
                -abs(tax_rep["tax_amount_currency"]),
                -abs(tax_rep["tax_amount"]),
            ),
        )
        for delta_suffix, delta_currency in (
            ("_currency", currency),
            ("", company_currency),
        ):
            field = f"tax_amount{delta_suffix}"
            # Round the target before measuring the delta. On the unrounded path it is
            # a raw figure, and the gap between a value and its own rounding is by
            # definition under half a unit -- distributing that at unit precision can
            # only yield 0 or +/-1 unit, so at the exact half it drags a correctly
            # rounded seed a unit off. Rounded targets are already at this precision,
            # so this is a no-op for them.
            target_amount = delta_currency.round(tax_data[f"{amount_prefix}{field}"])
            target_factors = [
                {"factor": tax_rep_data[field], "tax_rep_data": tax_rep_data}
                for tax_rep_data in sorted_tax_reps_data
            ]
            amounts_to_distribute = self._distribute_delta_amount_smoothly(
                precision_digits=delta_currency.decimal_places,
                delta_amount=target_amount - total_tax_rep_amounts[field],
                target_factors=target_factors,
            )
            for target_factor, amount_to_distribute in zip(
                target_factors, amounts_to_distribute, strict=True
            ):
                target_factor["tax_rep_data"][field] += amount_to_distribute

    def _add_tax_repartition_tags_and_grouping_keys(
        self, base_line, product_tags, include_caba_tags=False, repartition_cache=None
    ):
        is_refund = base_line["is_refund"]
        subsequent_tags_per_tax = defaultdict(lambda: self.env["account.account.tag"])
        base_line_grouping_key = self._prepare_base_line_grouping_key(base_line)
        for tax_data in reversed(base_line["tax_details"]["taxes_data"]):
            tax = tax_data["tax"]
            keeps_caba_tags = include_caba_tags or tax.tax_exigibility == "on_invoice"

            for tax_rep_data in tax_data["tax_reps_data"]:
                tax_rep = tax_rep_data["tax_rep"]

                tax_rep_data["taxes"] = tax_data["taxes"]
                tax_rep_data["tax_tags"] = product_tags
                if keeps_caba_tags:
                    tax_rep_data["tax_tags"] |= tax_rep.tag_ids
                if tax.include_base_amount:
                    for other_tax, tags in subsequent_tags_per_tax.items():
                        if tax != other_tax:
                            tax_rep_data["tax_tags"] |= tags

                tax_rep_data["grouping_key"] = (
                    self._prepare_base_line_tax_repartition_grouping_key(
                        base_line,
                        base_line_grouping_key,
                        tax_data,
                        tax_rep_data,
                    )
                )

            if tax.is_base_affected and keeps_caba_tags:
                subsequent_tags_per_tax[tax] |= tax._get_repartition_lines_by_kind(
                    is_refund, repartition_cache
                )["base"].tag_ids

    def _add_accounting_data_in_base_lines_tax_details(
        self, base_lines, company, include_caba_tags=False, rounded=True
    ):
        repartition_cache = {}
        for base_line in base_lines:
            self._add_accounting_data_to_base_line_tax_details(
                base_line,
                company,
                include_caba_tags=include_caba_tags,
                repartition_cache=repartition_cache,
                rounded=rounded,
            )


    @api.model
    def _prepare_tax_lines(self, base_lines, company, tax_lines=None):
        tax_lines_mapping, base_lines_to_update = self._aggregate_tax_lines_by_key(
            base_lines
        )
        tax_lines_mapping = self._drop_zero_tax_lines(tax_lines_mapping, company)

        tax_lines_to_update = []
        tax_lines_to_delete = []
        for tax_line in tax_lines or []:
            grouping_key = frozendict(
                self._prepare_tax_line_repartition_grouping_key(tax_line)
            )
            if grouping_key in tax_lines_mapping:
                amounts = tax_lines_mapping.pop(grouping_key)
                tax_lines_to_update.append((tax_line, grouping_key, amounts))
            else:
                tax_lines_to_delete.append(tax_line)
        tax_lines_to_add = [
            {**grouping_key, **values}
            for grouping_key, values in tax_lines_mapping.items()
        ]

        return {
            "tax_lines_to_add": tax_lines_to_add,
            "tax_lines_to_delete": tax_lines_to_delete,
            "tax_lines_to_update": tax_lines_to_update,
            "base_lines_to_update": base_lines_to_update,
        }


    @api.model
    def _make_undiscountable_filter(self, exclude_function=None):
        def dispatch_exclude_function(base_line, tax_data):
            return not tax_data["tax"]._can_be_discounted() or (
                exclude_function is not None and exclude_function(base_line, tax_data)
            )

        return dispatch_exclude_function

    @api.model
    def _aggregate_tax_lines_by_key(self, base_lines):
        tax_lines_mapping = defaultdict(
            lambda: {
                "tax_base_amount": 0.0,
                "amount_currency": 0.0,
                "balance": 0.0,
            }
        )

        base_lines_to_update = []
        for base_line in base_lines:
            sign = base_line["sign"]
            tax_details = base_line["tax_details"]
            base_lines_to_update.append(
                (
                    base_line,
                    {
                        "tax_tag_ids": [Command.set(base_line["tax_tag_ids"].ids)],
                        "amount_currency": sign
                        * (
                            tax_details["total_excluded_currency"]
                            + tax_details["delta_total_excluded_currency"]
                        ),
                        "balance": sign
                        * (
                            tax_details["total_excluded"]
                            + tax_details["delta_total_excluded"]
                        ),
                    },
                )
            )
            for tax_data in tax_details["taxes_data"]:
                tax = tax_data["tax"]
                for tax_rep_data in tax_data["tax_reps_data"]:
                    grouping_key = frozendict(tax_rep_data["grouping_key"])
                    tax_line = tax_lines_mapping[grouping_key]
                    tax_line["name"] = base_line.get("manual_tax_line_name", tax.name)
                    tax_line["tax_base_amount"] += sign * tax_data["base_amount"]
                    tax_line["amount_currency"] += (
                        sign * tax_rep_data["tax_amount_currency"]
                    )
                    tax_line["balance"] += sign * tax_rep_data["tax_amount"]
        return tax_lines_mapping, base_lines_to_update

    @api.model
    def _drop_zero_tax_lines(self, tax_lines_mapping, company):
        return {
            frozendict(
                {
                    grouping_k: k[grouping_k]
                    for grouping_k in k
                    if not grouping_k.startswith("__")
                }
            ): v
            for k, v in tax_lines_mapping.items()
            if (
                k["__keep_zero_line"]
                or (
                    not self.env["res.currency"]
                    .browse(k["currency_id"])
                    .is_zero(v["amount_currency"])
                    or not company.currency_id.is_zero(v["balance"])
                )
            )
        }

    def _can_be_discounted(self):
        self.ensure_one()
        return self.amount_type not in ("fixed", "code")

    @api.model
    def _merge_tax_details(self, tax_details_1, tax_details_2):
        results = {
            f"{prefix}{field}{suffix}": tax_details_1[f"{prefix}{field}{suffix}"]
            + tax_details_2[f"{prefix}{field}{suffix}"]
            for prefix in ("raw_", "")
            for field in ("total_excluded", "total_included")
            for suffix in ("_currency", "")
        }
        for suffix in ("_currency", ""):
            field = f"delta_total_excluded{suffix}"
            results[field] = tax_details_1[field] + tax_details_2[field]

        agg_taxes_data = {}
        for tax_details in (tax_details_1, tax_details_2):
            for tax_data in tax_details["taxes_data"]:
                tax = tax_data["tax"]
                if tax in agg_taxes_data:
                    agg_tax_data = agg_taxes_data[tax]
                    for prefix in ("raw_", ""):
                        for suffix in ("_currency", ""):
                            for field in ("base_amount", "tax_amount"):
                                field_with_prefix = f"{prefix}{field}{suffix}"
                                agg_tax_data[field_with_prefix] += tax_data[
                                    field_with_prefix
                                ]
                else:
                    agg_taxes_data[tax] = dict(tax_data)
        results["taxes_data"] = list(agg_taxes_data.values())

        taxes_in_2 = {tax_data["tax"] for tax_data in tax_details_2["taxes_data"]}
        taxes_only_in_1 = {
            tax_data["tax"]
            for tax_data in tax_details_1["taxes_data"]
            if tax_data["tax"] not in taxes_in_2
        }
        for tax_data in results["taxes_data"]:
            if tax_data["tax"] in taxes_only_in_1:
                for suffix in ("_currency", ""):
                    for prefix in ("raw_", ""):
                        tax_data[f"{prefix}base_amount{suffix}"] += tax_details_2[
                            f"{prefix}total_excluded{suffix}"
                        ]
                    tax_data[f"base_amount{suffix}"] += tax_details_2[
                        f"delta_total_excluded{suffix}"
                    ]

        return results

    @api.model
    def _fix_base_lines_tax_details_on_manual_tax_amounts(
        self, base_lines, company, filter_function=None
    ):
        for base_line in base_lines:
            tax_details = base_line["tax_details"]
            taxes_data = tax_details["taxes_data"]
            if not taxes_data:
                continue

            base_line["manual_total_excluded_currency"] = (
                tax_details["total_excluded_currency"]
                + tax_details["delta_total_excluded_currency"]
            )
            base_line["manual_total_excluded"] = (
                tax_details["total_excluded"] + tax_details["delta_total_excluded"]
            )
            base_line["manual_tax_amounts"] = {}
            for tax_data in taxes_data:
                if tax_data["is_reverse_charge"]:
                    continue
                tax = tax_data["tax"]
                tax_id_str = str(tax.id)
                base_line["manual_tax_amounts"][tax_id_str] = {}
                if filter_function and not filter_function(base_line, tax_data):
                    continue

                base_line["manual_tax_amounts"][tax_id_str] = {
                    "tax_amount_currency": tax_data["tax_amount_currency"],
                    "tax_amount": tax_data["tax_amount"],
                    "base_amount_currency": tax_data["base_amount_currency"],
                    "base_amount": tax_data["base_amount"],
                }

    @api.model
    def _split_tax_data(self, base_line, tax_data, company, target_factors):
        currency = base_line["currency_id"]

        factors = self._normalize_target_factors(target_factors)

        new_taxes_data = [None] * len(factors)

        for index, factor in factors:
            new_taxes_data[index] = {
                **tax_data,
                "raw_tax_amount_currency": factor * tax_data["raw_tax_amount_currency"],
                "raw_tax_amount": factor * tax_data["raw_tax_amount"],
                "raw_base_amount_currency": factor
                * tax_data["raw_base_amount_currency"],
                "raw_base_amount": factor * tax_data["raw_base_amount"],
            }

        new_target_factors = [
            {
                "factor": target_factor["factor"],
                "tax_data": new_tax_data,
            }
            for new_tax_data, target_factor in zip(
                new_taxes_data, target_factors, strict=True
            )
        ]

        for delta_currency_indicator, delta_currency in (
            ("_currency", currency),
            ("", company.currency_id),
        ):
            for prefix in ("tax", "base"):
                field = f"{prefix}_amount{delta_currency_indicator}"
                amounts_to_distribute = self._distribute_delta_amount_smoothly(
                    precision_digits=delta_currency.decimal_places,
                    delta_amount=tax_data[field],
                    target_factors=new_target_factors,
                )
                for target_factor, amount_to_distribute in zip(
                    new_target_factors, amounts_to_distribute, strict=True
                ):
                    new_tax_data = target_factor["tax_data"]
                    new_tax_data[field] = amount_to_distribute
        return new_taxes_data

    @api.model
    def _split_tax_details(self, base_line, company, target_factors):
        currency = base_line["currency_id"]
        tax_details = base_line["tax_details"]

        factors = self._normalize_target_factors(target_factors)

        new_tax_details_list = [None] * len(factors)

        for index, factor in factors:
            new_tax_details_list[index] = {
                "raw_total_excluded_currency": factor
                * tax_details["raw_total_excluded_currency"],
                "raw_total_excluded": factor * tax_details["raw_total_excluded"],
                "raw_total_included_currency": factor
                * tax_details["raw_total_included_currency"],
                "raw_total_included": factor * tax_details["raw_total_included"],
                "delta_total_excluded_currency": 0.0,
                "delta_total_excluded": 0.0,
                "taxes_data": [],
            }

        for tax_data in tax_details["taxes_data"]:
            new_taxes_data = self._split_tax_data(
                base_line, tax_data, company, target_factors
            )
            for new_tax_details, new_tax_data in zip(
                new_tax_details_list, new_taxes_data, strict=True
            ):
                new_tax_details["taxes_data"].append(new_tax_data)

        for delta_currency_indicator, delta_currency in (
            ("_currency", currency),
            ("", company.currency_id),
        ):
            new_target_factors = [
                {
                    "factor": new_tax_details[
                        f"raw_total_excluded{delta_currency_indicator}"
                    ],
                    "tax_details": new_tax_details,
                }
                for new_tax_details in new_tax_details_list
            ]
            field = f"total_excluded{delta_currency_indicator}"
            delta_amount = tax_details[field]
            amounts_to_distribute = self._distribute_delta_amount_smoothly(
                precision_digits=delta_currency.decimal_places,
                delta_amount=delta_amount,
                target_factors=new_target_factors,
            )
            for target_factor, amount_to_distribute in zip(
                new_target_factors, amounts_to_distribute, strict=True
            ):
                new_tax_details = target_factor["tax_details"]
                new_tax_details[field] = amount_to_distribute

        for new_tax_details in new_tax_details_list:
            for delta_currency_indicator in ("_currency", ""):
                new_tax_details[f"total_included{delta_currency_indicator}"] = (
                    new_tax_details[f"total_excluded{delta_currency_indicator}"]
                    + sum(
                        new_tax_data[f"tax_amount{delta_currency_indicator}"]
                        for new_tax_data in new_tax_details["taxes_data"]
                    )
                )
        return new_tax_details_list

    @api.model
    def _split_base_line(
        self, base_line, company, target_factors, populate_function=None
    ):
        factors = self._normalize_target_factors(target_factors)

        new_tax_details_list = self._split_tax_details(
            base_line, company, target_factors
        )

        new_base_lines = [None] * len(factors)
        for index, factor in factors:
            kwargs = {
                "price_unit": factor * base_line["price_unit"],
                "tax_details": new_tax_details_list[index],
            }
            if populate_function:
                populate_function(base_line, target_factors[index], kwargs)
            new_base_lines[index] = self._prepare_base_line_for_taxes_computation(
                base_line, **kwargs
            )
        return new_base_lines

    @api.model
    def _reduce_base_lines_with_grouping_function(
        self,
        base_lines,
        grouping_function=None,
        aggregate_function=None,
        computation_key=None,
    ):
        aggregated_base_lines = {}
        base_line_map = {}
        for base_line in base_lines:
            price_unit_after_discount = base_line["price_unit"] * (
                1 - (base_line["discount"] / 100.0)
            )
            new_base_line = self._prepare_base_line_for_taxes_computation(
                base_line,
                price_unit=base_line["quantity"] * price_unit_after_discount,
                quantity=1.0,
                discount=0.0,
            )
            grouping_key = {"tax_ids": new_base_line["tax_ids"]}
            if grouping_function:
                grouping_key.update(grouping_function(new_base_line))
            grouping_key = frozendict(grouping_key)

            target_base_line = base_line_map.get(grouping_key)
            if target_base_line:
                target_base_line["price_unit"] += new_base_line["price_unit"]
                target_base_line["tax_details"] = self._merge_tax_details(
                    tax_details_1=target_base_line["tax_details"],
                    tax_details_2=base_line["tax_details"],
                )
            else:
                target_base_line = self._prepare_base_line_for_taxes_computation(
                    new_base_line,
                    **grouping_key,
                    computation_key=computation_key,
                    tax_details={
                        **base_line["tax_details"],
                        "taxes_data": [
                            dict(tax_data)
                            for tax_data in base_line["tax_details"]["taxes_data"]
                        ],
                    },
                )
                base_line_map[grouping_key] = target_base_line

            if aggregate_function:
                aggregate_function(target_base_line, base_line)
            aggregated_base_lines.setdefault(grouping_key, []).append(base_line)

        base_line_map = {
            grouping_key: base_line
            for grouping_key, base_line in base_line_map.items()
            if not base_line["currency_id"].is_zero(base_line["price_unit"])
        }

        for grouping_key, base_line in base_line_map.items():
            total_factor = 0.0
            analytic_distribution_to_aggregate = defaultdict(float)
            for aggregated_base_line in aggregated_base_lines[grouping_key]:
                amount = aggregated_base_line["tax_details"][
                    "raw_total_excluded_currency"
                ]
                total_factor += amount
                for account_id, distribution in (
                    aggregated_base_line["analytic_distribution"] or {}
                ).items():
                    analytic_distribution_to_aggregate[account_id] += (
                        distribution * amount / 100.0
                    )
            analytic_distribution = {}
            for account_id, amount in analytic_distribution_to_aggregate.items():
                analytic_distribution[account_id] = (
                    amount * 100 / total_factor if total_factor else 0.0
                )
            base_line["analytic_distribution"] = analytic_distribution

        return list(base_line_map.values())

    @api.model
    def _reduce_base_lines_to_target_amount(
        self,
        base_lines,
        company,
        amount_type,
        amount,
        computation_key=None,
        grouping_function=None,
        aggregate_function=None,
    ):
        if not base_lines:
            return []

        currency = base_lines[0]["currency_id"]
        rate = base_lines[0]["rate"]

        total_amount_currency, total_amount = self._measure_base_lines_total(base_lines)

        tax_amounts_per_tax = self._measure_tax_amounts_per_tax(base_lines)

        sign = -1 if amount < 0.0 else 1
        signed_amount = sign * amount
        if amount_type == "fixed":
            percentage = (
                (signed_amount / total_amount_currency)
                if total_amount_currency
                else 0.0
            )
            expected_total_amount_currency = currency.round(amount)
            expected_total_amount = (
                company.currency_id.round(expected_total_amount_currency / rate)
                if rate
                else 0.0
            )
        else:
            percentage = signed_amount / 100.0
            expected_total_amount_currency = currency.round(
                total_amount_currency * sign * percentage
            )
            expected_total_amount = company.currency_id.round(
                total_amount * sign * percentage
            )

        expected_tax_amounts = {
            grouping_key: {
                "tax_amount_currency": currency.round(
                    values["tax_amount_currency"] * sign * percentage
                ),
                "tax_amount": company.currency_id.round(
                    values["tax_amount"] * sign * percentage
                ),
                "base_amount_currency": currency.round(
                    values["base_amount_currency"] * sign * percentage
                ),
                "base_amount": company.currency_id.round(
                    values["base_amount"] * sign * percentage
                ),
            }
            for grouping_key, values in tax_amounts_per_tax.items()
        }
        expected_base_amount_currency = expected_total_amount_currency - sum(
            values["tax_amount_currency"] for values in expected_tax_amounts.values()
        )
        expected_base_amount = expected_total_amount - sum(
            values["tax_amount"] for values in expected_tax_amounts.values()
        )

        reduced_base_lines = self._reduce_base_lines_with_grouping_function(
            base_lines=base_lines,
            grouping_function=grouping_function,
            aggregate_function=aggregate_function,
            computation_key=computation_key,
        )
        if not reduced_base_lines:
            return []

        new_base_lines = [
            self._prepare_base_line_for_taxes_computation(
                base_line,
                price_unit=base_line["price_unit"] * sign * percentage,
                computation_key=computation_key,
            )
            for base_line in reduced_base_lines
        ]
        self._add_tax_details_in_base_lines(new_base_lines, company)
        self._round_base_lines_tax_details(new_base_lines, company)

        sorted_base_lines = sorted(
            new_base_lines,
            key=lambda base_line: (
                bool(base_line["special_type"]),
                -base_line["tax_details"]["total_excluded_currency"],
            ),
        )
        current_tax_amounts_per_tax = self._measure_tax_amounts_per_tax(new_base_lines)
        for tax_id_str, tax_amounts in current_tax_amounts_per_tax.items():
            expected = expected_tax_amounts[tax_id_str]
            for delta_suffix, delta_currency in (
                ("_currency", currency),
                ("", company.currency_id),
            ):
                for prefix in ("tax", "base"):
                    reference_amount = tax_amounts[f"{prefix}_amount_currency"]
                    if not reference_amount:
                        continue

                    field = f"{prefix}_amount{delta_suffix}"
                    target_factors = [
                        {
                            "factor": abs(
                                tax_data[f"{prefix}_amount_currency"] / reference_amount
                            ),
                            "base_line": base_line,
                            "tax_data": tax_data,
                        }
                        for base_line in sorted_base_lines
                        for tax_data in base_line["tax_details"]["taxes_data"]
                        if str(tax_data["tax"].id) == tax_id_str
                    ]
                    amounts_to_distribute = self._distribute_delta_amount_smoothly(
                        precision_digits=delta_currency.decimal_places,
                        delta_amount=expected[field] - tax_amounts[field],
                        target_factors=target_factors,
                    )
                    for target_factor, amount_to_distribute in zip(
                        target_factors, amounts_to_distribute, strict=True
                    ):
                        target_factor["tax_data"][field] += amount_to_distribute

        self._spread_delta_on_base_amount(
            new_base_lines,
            sorted_base_lines,
            company,
            currency,
            expected_base_amount_currency,
            expected_base_amount,
        )

        return new_base_lines

    @api.model
    def _measure_base_lines_total(self, base_lines):
        values_per_grouping_key = self._aggregate_base_lines_aggregated_values(
            self._aggregate_base_lines_tax_details(
                base_lines, _group_everything_together
            )
        )
        return (
            sum(
                values["total_excluded_currency"] + values["tax_amount_currency"]
                for values in values_per_grouping_key.values()
            ),
            sum(
                values["total_excluded"] + values["tax_amount"]
                for values in values_per_grouping_key.values()
            ),
        )

    @api.model
    def _measure_tax_amounts_per_tax(self, base_lines):
        values_per_grouping_key = self._aggregate_base_lines_aggregated_values(
            self._aggregate_base_lines_tax_details(base_lines, _group_by_tax)
        )
        return {
            grouping_key: {
                "tax_amount_currency": values["tax_amount_currency"],
                "tax_amount": values["tax_amount"],
                "base_amount_currency": values["base_amount_currency"],
                "base_amount": values["base_amount"],
            }
            for grouping_key, values in values_per_grouping_key.items()
            if grouping_key
        }

    @api.model
    def _spread_delta_on_base_amount(
        self,
        new_base_lines,
        sorted_base_lines,
        company,
        currency,
        expected_base_amount_currency,
        expected_base_amount,
    ):
        current_base_amount_currency, current_base_amount = 0.0, 0.0
        values_per_grouping_key = self._aggregate_base_lines_aggregated_values(
            self._aggregate_base_lines_tax_details(
                new_base_lines, _group_everything_together
            )
        )
        for values in values_per_grouping_key.values():
            current_base_amount_currency += values["total_excluded_currency"]
            current_base_amount += values["total_excluded"]

        for delta_suffix, delta_base_amount, delta_currency in (
            (
                "_currency",
                expected_base_amount_currency - current_base_amount_currency,
                currency,
            ),
            ("", expected_base_amount - current_base_amount, company.currency_id),
        ):
            target_factors = [
                {
                    "factor": abs(
                        (
                            base_line["tax_details"]["total_excluded_currency"]
                            + base_line["tax_details"]["delta_total_excluded_currency"]
                        )
                        / current_base_amount_currency
                    )
                    if current_base_amount_currency
                    else 0.0,
                    "base_line": base_line,
                }
                for base_line in sorted_base_lines
            ]
            amounts_to_distribute = self._distribute_delta_amount_smoothly(
                precision_digits=delta_currency.decimal_places,
                delta_amount=delta_base_amount,
                target_factors=target_factors,
            )
            for target_factor, amount_to_distribute in zip(
                target_factors, amounts_to_distribute, strict=True
            ):
                base_line = target_factor["base_line"]
                base_line["tax_details"][f"delta_total_excluded{delta_suffix}"] += (
                    amount_to_distribute
                )
                if delta_suffix == "_currency":
                    base_line["price_unit"] += amount_to_distribute

    @api.model
    def _partition_base_lines_taxes(self, base_lines, partition_function):
        has_taxes_to_exclude = False
        base_lines_partition_taxes = []
        for base_line in base_lines:
            tax_details = base_line["tax_details"]
            taxes_data = tax_details["taxes_data"]
            taxes_to_keep = self.env["account.tax"]
            taxes_to_exclude = self.env["account.tax"]
            for tax_data in taxes_data:
                if partition_function(base_line, tax_data):
                    taxes_to_keep += tax_data["tax"]
                else:
                    taxes_to_exclude += tax_data["tax"]
            if taxes_to_exclude:
                has_taxes_to_exclude = True
            base_lines_partition_taxes.append(
                (base_line, taxes_to_keep, taxes_to_exclude)
            )
        return base_lines_partition_taxes, has_taxes_to_exclude

    @api.model
    def _prepare_discountable_base_lines(
        self, base_lines, company, exclude_function=None
    ):
        return self._dispatch_taxes_into_new_base_lines(
            base_lines, company, self._make_undiscountable_filter(exclude_function)
        )


    @api.model
    def _prepare_global_discount_lines(
        self,
        base_lines,
        company,
        amount_type,
        amount,
        computation_key="global_discount",
        grouping_function=None,
    ):
        discountable_base_lines = self._prepare_discountable_base_lines(
            base_lines, company
        )
        new_base_lines = self._reduce_base_lines_to_target_amount(
            base_lines=discountable_base_lines,
            company=company,
            amount_type=amount_type,
            amount=-amount,
            computation_key=computation_key,
            grouping_function=grouping_function,
        )
        self._fix_base_lines_tax_details_on_manual_tax_amounts(
            base_lines=new_base_lines,
            company=company,
        )
        return new_base_lines


    @api.model
    def _prepare_base_lines_for_down_payment(
        self,
        base_lines,
        company,
        exclude_function=None,
    ):
        new_base_lines = self._dispatch_taxes_into_new_base_lines(
            base_lines,
            company,
            self._make_undiscountable_filter(exclude_function),
        )
        return new_base_lines + self._turn_removed_taxes_into_new_base_lines(
            new_base_lines,
            company,
        )

    @api.model
    def _prepare_down_payment_lines(
        self,
        base_lines,
        company,
        amount_type,
        amount,
        computation_key="down_payment",
        grouping_function=None,
    ):
        base_lines_for_dp = self._prepare_base_lines_for_down_payment(
            base_lines, company
        )
        new_base_lines = self._reduce_base_lines_to_target_amount(
            base_lines=base_lines_for_dp,
            company=company,
            amount_type=amount_type,
            amount=amount,
            computation_key=computation_key,
            grouping_function=grouping_function,
        )
        self._fix_base_lines_tax_details_on_manual_tax_amounts(
            base_lines=new_base_lines,
            company=company,
        )
        return new_base_lines


    @api.model
    def _dispatch_taxes_into_new_base_lines(
        self, base_lines, company, exclude_function
    ):
        def partition_function(base_line, tax_data):
            return not exclude_function(base_line, tax_data)

        base_lines_partition_taxes = self._partition_base_lines_taxes(
            base_lines, partition_function
        )[0]
        new_base_lines_list = [[] for _base_line in base_lines]
        to_process = deque(
            (index, base_line, taxes_to_exclude)
            for index, (base_line, _taxes_to_keep, taxes_to_exclude) in enumerate(
                base_lines_partition_taxes
            )
        )
        while to_process:
            index, base_line, taxes_to_exclude = to_process.popleft()

            tax_details = base_line["tax_details"]
            taxes_data = tax_details["taxes_data"]

            next_split_index = None
            for i, tax_data in enumerate(taxes_data):
                if tax_data["tax"] in taxes_to_exclude:
                    next_split_index = i
                    break

            if next_split_index is None:
                new_base_lines_list[index].append(dict(base_line))
                continue

            common_taxes_data = taxes_data[:next_split_index]
            tax_data_to_remove = taxes_data[next_split_index]
            remaining_taxes_data = taxes_data[next_split_index + 1 :]

            first_tax_details = {
                k: tax_details[k]
                for k in (
                    "raw_total_excluded_currency",
                    "raw_total_excluded",
                    "total_excluded_currency",
                    "total_excluded",
                    "delta_total_excluded_currency",
                    "delta_total_excluded",
                )
            }
            first_tax_details["taxes_data"] = common_taxes_data
            for suffix in ("_currency", ""):
                first_tax_details[f"raw_total_included{suffix}"] = first_tax_details[
                    f"raw_total_excluded{suffix}"
                ] + sum(
                    common_tax_data[f"raw_tax_amount{suffix}"]
                    for common_tax_data in common_taxes_data
                )
                first_tax_details[f"total_included{suffix}"] = (
                    first_tax_details[f"total_excluded{suffix}"]
                    + first_tax_details[f"delta_total_excluded{suffix}"]
                    + sum(
                        common_tax_data[f"tax_amount{suffix}"]
                        for common_tax_data in common_taxes_data
                    )
                )
            second_tax_details = {
                "raw_total_excluded_currency": tax_data_to_remove[
                    "raw_tax_amount_currency"
                ],
                "raw_total_excluded": tax_data_to_remove["raw_tax_amount"],
                "total_excluded_currency": tax_data_to_remove["tax_amount_currency"],
                "total_excluded": tax_data_to_remove["tax_amount"],
                "delta_total_excluded_currency": 0.0,
                "delta_total_excluded": 0.0,
                "raw_total_included_currency": tax_data_to_remove[
                    "raw_tax_amount_currency"
                ],
                "raw_total_included": tax_data_to_remove["raw_tax_amount"],
                "total_included_currency": tax_data_to_remove["tax_amount_currency"],
                "total_included": tax_data_to_remove["tax_amount"],
                "taxes_data": [],
            }

            target_factors = [
                {
                    "factor": first_tax_details["raw_total_excluded_currency"],
                    "tax_details": first_tax_details,
                },
                {
                    "factor": second_tax_details["raw_total_excluded_currency"],
                    "tax_details": second_tax_details,
                },
            ]
            for remaining_tax_data in remaining_taxes_data:
                if remaining_tax_data["tax"] in tax_data_to_remove["taxes"]:
                    new_remaining_taxes_data = self._split_tax_data(
                        base_line, remaining_tax_data, company, target_factors
                    )

                    first_tax_data = new_remaining_taxes_data[0]

                    second_tax_details["taxes_data"].append(new_remaining_taxes_data[1])
                    self._add_tax_data_to_included_totals(
                        second_tax_details, new_remaining_taxes_data[1]
                    )
                else:
                    first_tax_data = remaining_tax_data

                first_tax_details["taxes_data"].append(first_tax_data)
                self._add_tax_data_to_included_totals(first_tax_details, first_tax_data)

            first_taxes = self.env["account.tax"]
            for tax_data in first_tax_details["taxes_data"]:
                first_taxes += tax_data["tax"]
            first_base_line = self._prepare_base_line_for_taxes_computation(
                base_line,
                tax_ids=first_taxes,
                tax_details=first_tax_details,
            )

            second_taxes = self.env["account.tax"]
            for tax_data in second_tax_details["taxes_data"]:
                second_taxes += tax_data["tax"]
            second_base_line = self._prepare_base_line_for_taxes_computation(
                base_line,
                tax_ids=second_taxes,
                price_unit=(
                    second_tax_details["raw_total_excluded_currency"]
                    + sum(
                        sub_tax_data["raw_tax_amount_currency"]
                        for sub_tax_data in second_tax_details["taxes_data"]
                        if sub_tax_data["tax"].price_include
                    )
                )
                / (base_line["quantity"] or 1.0),
                tax_details=second_tax_details,
                _removed_tax_data=tax_data_to_remove,
            )
            to_process.appendleft((index, second_base_line, taxes_to_exclude))
            to_process.appendleft((index, first_base_line, taxes_to_exclude))

        final_base_lines = []
        for new_base_lines in new_base_lines_list:
            new_base_lines[0]["removed_taxes_data_base_lines"] = new_base_lines[1:]
            final_base_lines.append(new_base_lines[0])
        return final_base_lines

    @api.model
    def _add_tax_data_to_included_totals(self, tax_details, tax_data):
        for suffix in ("_currency", ""):
            tax_details[f"raw_total_included{suffix}"] += tax_data[
                f"raw_tax_amount{suffix}"
            ]
            tax_details[f"total_included{suffix}"] += tax_data[f"tax_amount{suffix}"]

    @api.model
    def _turn_removed_taxes_into_new_base_lines(
        self, base_lines, company, grouping_function=None, aggregate_function=None
    ):
        extra_base_lines = []
        for base_line in base_lines:
            extra_base_lines += base_line["removed_taxes_data_base_lines"]
        return self._reduce_base_lines_with_grouping_function(
            base_lines=extra_base_lines,
            grouping_function=grouping_function,
            aggregate_function=aggregate_function,
        )

    @api.model
    def _dispatch_global_discount_lines(self, base_lines, company):
        new_base_lines = []
        discount_data_per_taxes = {}
        dispatched_neg_base_lines = []
        for base_line in base_lines:
            tax_details = base_line["tax_details"]
            taxes_data = tax_details["taxes_data"]

            taxes = self.env["account.tax"]
            for gb_tax_data in taxes_data:
                taxes += gb_tax_data["tax"]
            taxes = taxes.filtered(lambda tax: tax._can_be_discounted())

            discount_data = discount_data_per_taxes.setdefault(
                taxes,
                {
                    "base_lines": [],
                    "discount_base_lines": [],
                },
            )

            new_base_line = {
                **base_line,
                "discount_base_lines": [],
            }

            if base_line["special_type"] == "global_discount":
                discount_data["discount_base_lines"].append(new_base_line)
            else:
                discount_data["base_lines"].append(new_base_line)
            new_base_lines.append(new_base_line)

        for discount_data in discount_data_per_taxes.values():
            discount_data["target_factors"] = [
                {
                    "base_line": base_line,
                    "factor": base_line["tax_details"]["raw_total_excluded_currency"],
                }
                for base_line in discount_data["base_lines"]
            ]
            if discount_data["target_factors"]:
                dispatched_neg_base_lines += discount_data["discount_base_lines"]
            else:
                continue

            for discount_base_line in discount_data["discount_base_lines"]:
                splitted_base_lines = self._split_base_line(
                    base_line=discount_base_line,
                    company=company,
                    target_factors=discount_data["target_factors"],
                )
                for base_line, new_base_line in zip(
                    discount_data["base_lines"], splitted_base_lines, strict=True
                ):
                    base_line["discount_base_lines"].append(new_base_line)
        dispatched_ids = {id(x) for x in dispatched_neg_base_lines}
        return [x for x in new_base_lines if id(x) not in dispatched_ids]

    @api.model
    def _squash_global_discount_lines(self, base_lines, company):
        for base_line in base_lines:
            for sub_base_line in base_line["discount_base_lines"]:
                base_line["tax_details"] = self._merge_tax_details(
                    tax_details_1=base_line["tax_details"],
                    tax_details_2=sub_base_line["tax_details"],
                )

        self._fix_base_lines_tax_details_on_manual_tax_amounts(
            base_lines=[
                base_line
                for base_line in base_lines
                if base_line["discount_base_lines"]
            ],
            company=company,
        )

    @api.model
    def _dispatch_return_of_merchandise_lines(self, base_lines, company):
        dispatched_neg_base_lines = []
        new_base_lines, mapping = self._group_lines_for_return_of_merchandise(
            base_lines
        )

        for signed_base_lines in mapping.values():
            neg_base_lines = sorted(
                signed_base_lines["-"], key=lambda base_line: base_line["quantity"]
            )
            target_factors_per_neg_base_line = self._match_returns_to_positive_lines(
                sorted(
                    signed_base_lines["+"],
                    key=lambda base_line: -base_line["quantity"],
                ),
                neg_base_lines,
            )

            def populate_function(base_line, target_factor, kwargs):
                kwargs["price_unit"] = base_line["price_unit"]
                kwargs["quantity"] = -target_factor["quantity_to_dispatch"]

            for target_factors, neg_base_line in zip(
                target_factors_per_neg_base_line, neg_base_lines, strict=True
            ):
                if not target_factors:
                    continue

                dispatched_neg_base_lines.append(neg_base_line)
                splitted_base_lines = self._split_base_line(
                    base_line=neg_base_line,
                    company=company,
                    target_factors=target_factors,
                    populate_function=populate_function,
                )
                for target_factor, new_base_line in zip(
                    target_factors, splitted_base_lines, strict=True
                ):
                    plus_base_line = target_factor["plus_base_line"]
                    if plus_base_line:
                        plus_base_line["return_of_merchandise_base_lines"].append(
                            new_base_line
                        )
                    else:
                        new_base_line["return_of_merchandise_base_lines"] = []
                        new_base_lines.append(new_base_line)

        dispatched_ids = {id(x) for x in dispatched_neg_base_lines}
        return [x for x in new_base_lines if id(x) not in dispatched_ids]

    @api.model
    def _group_lines_for_return_of_merchandise(self, base_lines):
        new_base_lines = []
        mapping = defaultdict(lambda: {"+": [], "-": []})
        for base_line in base_lines:
            new_base_line = {**base_line, "return_of_merchandise_base_lines": []}
            new_base_lines.append(new_base_line)

            if not base_line["product_id"] or base_line["quantity"] == 0:
                continue

            key = frozendict(
                {
                    "tax_ids": base_line["tax_ids"].ids,
                    "product": base_line["product_id"].id,
                    "price_unit": base_line["price_unit"],
                    "discount": base_line["discount"],
                }
            )
            is_negative = base_line["tax_details"]["raw_total_excluded_currency"] < 0.0
            mapping[key]["-" if is_negative else "+"].append(new_base_line)
        return new_base_lines, mapping

    @api.model
    def _match_returns_to_positive_lines(self, plus_base_lines, neg_base_lines):
        target_factors_per_neg_base_line = [[] for _neg in neg_base_lines]

        iter_plus_base_lines = iter(plus_base_lines)
        plus_base_line = next(iter_plus_base_lines, None)
        plus_quantity = abs(plus_base_line["quantity"]) if plus_base_line else 0.0

        for target_factors, neg_base_line in zip(
            target_factors_per_neg_base_line, neg_base_lines, strict=True
        ):
            neg_quantity = abs(neg_base_line["quantity"])
            remaining = neg_quantity
            while not float_is_zero(remaining, precision_digits=12) and (
                plus_base_line
            ):
                if float_is_zero(plus_quantity, precision_digits=12):
                    plus_base_line = next(iter_plus_base_lines, None)
                    plus_quantity = (
                        abs(plus_base_line["quantity"]) if plus_base_line else 0.0
                    )
                    continue

                quantity_to_dispatch = min(remaining, plus_quantity)
                target_factors.append(
                    {
                        "factor": quantity_to_dispatch / neg_quantity,
                        "quantity_to_dispatch": quantity_to_dispatch,
                        "plus_base_line": plus_base_line,
                    }
                )
                plus_quantity -= quantity_to_dispatch
                remaining -= quantity_to_dispatch

            if target_factors and not float_is_zero(remaining, precision_digits=12):
                target_factors.append(
                    {
                        "factor": remaining / neg_quantity,
                        "quantity_to_dispatch": remaining,
                        "plus_base_line": None,
                    }
                )
        return target_factors_per_neg_base_line

    @api.model
    def _squash_return_of_merchandise_lines(self, base_lines, company):
        for base_line in base_lines:
            for sub_base_line in base_line["return_of_merchandise_base_lines"]:
                base_line["tax_details"] = self._merge_tax_details(
                    tax_details_1=base_line["tax_details"],
                    tax_details_2=sub_base_line["tax_details"],
                )
                base_line["quantity"] += sub_base_line["quantity"]

        self._fix_base_lines_tax_details_on_manual_tax_amounts(
            base_lines=[
                base_line
                for base_line in base_lines
                if base_line["return_of_merchandise_base_lines"]
            ],
            company=company,
        )


    @api.model
    def _get_delta_amount_to_reach_target(
        self,
        target_amount,
        target_currency,
        raw_current_amount,
        raw_current_amount_precision_digits,
    ):
        target_amount_sign = -1 if target_amount < 0.0 else 1
        raw_current_amount_rounding = math.pow(10, -raw_current_amount_precision_digits)
        tolerance_bounds = (
            float_round(
                abs(target_amount)
                + (target_currency.rounding / 2)
                - raw_current_amount_rounding,
                precision_digits=raw_current_amount_precision_digits,
            ),
            float_round(
                abs(target_amount) - (target_currency.rounding / 2),
                precision_digits=raw_current_amount_precision_digits,
            ),
        )

        signed_raw_current_amount = target_amount_sign * raw_current_amount
        if signed_raw_current_amount > tolerance_bounds[0]:
            delta_raw_amount = tolerance_bounds[0] - signed_raw_current_amount
        elif signed_raw_current_amount < tolerance_bounds[1]:
            delta_raw_amount = tolerance_bounds[1] - signed_raw_current_amount
        else:
            return 0.0

        return target_amount_sign * delta_raw_amount

    @api.model
    def _round_raw_total_excluded(
        self,
        base_lines,
        company,
        precision_digits=6,
        apply_strict_tolerance=False,
        in_foreign_currency=True,
    ):
        if not base_lines:
            return

        suffix_currency = (
            base_lines[0]["currency_id"] if in_foreign_currency else company.currency_id
        )
        suffix = "_currency" if in_foreign_currency else ""
        raw_field = f"raw_total_excluded{suffix}"

        for base_line in base_lines:
            tax_details = base_line["tax_details"]
            tax_details[raw_field] = float_round(
                tax_details[raw_field], precision_digits=precision_digits
            )

        if not apply_strict_tolerance:
            return

        base_lines_aggregated_values = self._aggregate_base_lines_tax_details(
            base_lines, _group_everything_together
        )
        values_per_grouping_key = self._aggregate_base_lines_aggregated_values(
            base_lines_aggregated_values
        )
        expected_total_excluded = sum(
            values[f"total_excluded{suffix}"]
            for values in values_per_grouping_key.values()
        )
        current_raw_total_excluded = sum(
            base_line["tax_details"][raw_field] for base_line in base_lines
        )

        delta_raw_amount = self._get_delta_amount_to_reach_target(
            target_amount=expected_total_excluded,
            target_currency=suffix_currency,
            raw_current_amount=current_raw_total_excluded,
            raw_current_amount_precision_digits=precision_digits,
        )
        target_factors = [
            {
                "factor": base_line["tax_details"][raw_field],
                "base_line": base_line,
            }
            for base_line in base_lines
        ]
        amounts_to_distribute = self._distribute_delta_amount_smoothly(
            precision_digits=precision_digits,
            delta_amount=delta_raw_amount,
            target_factors=target_factors,
        )
        for target_factor, amount_to_distribute in zip(
            target_factors, amounts_to_distribute, strict=True
        ):
            base_line = target_factor["base_line"]
            base_line["tax_details"][raw_field] += amount_to_distribute

    @api.model
    def _get_price_unit_without_tax(
        self,
        base_line,
        raw_gross_total_excluded,
        in_foreign_currency=True,
        precision_digits=None,
    ):
        if not raw_gross_total_excluded or (
            precision_digits is not None
            and float_is_zero(
                raw_gross_total_excluded, precision_digits=precision_digits
            )
        ):
            if in_foreign_currency:
                raw_gross_price_unit = base_line["price_unit"]
            elif base_line["rate"]:
                raw_gross_price_unit = base_line["price_unit"] / base_line["rate"]
            else:
                raw_gross_price_unit = 0.0
        elif not base_line["quantity"]:
            raw_gross_price_unit = raw_gross_total_excluded
        else:
            raw_gross_price_unit = raw_gross_total_excluded / base_line["quantity"]

        if precision_digits is not None:
            raw_gross_price_unit = float_round(
                raw_gross_price_unit, precision_digits=precision_digits
            )
        return raw_gross_price_unit

    @api.model
    def _get_discount_amount_without_tax(
        self,
        base_line,
        raw_gross_total_excluded,
        in_foreign_currency=True,
        precision_digits=None,
    ):
        suffix = "_currency" if in_foreign_currency else ""
        raw_discount_amount = (
            raw_gross_total_excluded
            - base_line["tax_details"][f"raw_total_excluded{suffix}"]
        )

        if precision_digits is not None:
            raw_discount_amount = float_round(
                raw_discount_amount, precision_digits=precision_digits
            )
        return raw_discount_amount

    @api.model
    def _add_and_round_raw_gross_total_excluded_and_discount(
        self,
        base_lines,
        company,
        precision_digits=6,
        apply_strict_tolerance=False,
        in_foreign_currency=True,
        account_discount_base_lines=False,
    ):
        if not base_lines:
            return

        suffix_currency = (
            base_lines[0]["currency_id"] if in_foreign_currency else company.currency_id
        )
        suffix = "_currency" if in_foreign_currency else ""
        raw_field = f"raw_total_excluded{suffix}"

        for base_line in base_lines:
            tax_details = base_line["tax_details"]
            raw_total_excluded = tax_details[raw_field]

            global_discount_sum = 0.0
            if account_discount_base_lines:
                global_discount_sum = sum(
                    discount_base_line["tax_details"][raw_field]
                    for discount_base_line in base_line.get("discount_base_lines", [])
                )

            discount_factor = 1 - (base_line["discount"] / 100.0)
            if discount_factor:
                raw_gross_total_excluded = (
                    raw_total_excluded - global_discount_sum
                ) / discount_factor
            elif suffix == "_currency":
                raw_gross_total_excluded = (
                    base_line["price_unit"] * base_line["quantity"]
                )
            elif base_line["rate"]:
                raw_gross_total_excluded = (
                    base_line["price_unit"] * base_line["quantity"] / base_line["rate"]
                )
            else:
                raw_gross_total_excluded = 0.0
            tax_details[f"raw_gross_total_excluded{suffix}"] = float_round(
                raw_gross_total_excluded, precision_digits=precision_digits
            )

            raw_gross_price_unit = self._get_price_unit_without_tax(
                base_line=base_line,
                raw_gross_total_excluded=raw_gross_total_excluded,
                in_foreign_currency=in_foreign_currency,
                precision_digits=precision_digits,
            )
            tax_details[f"raw_gross_price_unit{suffix}"] = raw_gross_price_unit

            raw_discount_amount = self._get_discount_amount_without_tax(
                base_line=base_line,
                raw_gross_total_excluded=raw_gross_total_excluded,
                in_foreign_currency=in_foreign_currency,
                precision_digits=precision_digits,
            )
            tax_details[f"raw_discount_amount{suffix}"] = raw_discount_amount

        if apply_strict_tolerance:
            self._apply_gross_total_strict_tolerance(
                base_lines, suffix, suffix_currency, precision_digits
            )

    @api.model
    def _apply_gross_total_strict_tolerance(
        self, base_lines, suffix, suffix_currency, precision_digits
    ):
        base_lines_aggregated_values = self._aggregate_base_lines_tax_details(
            base_lines, _group_everything_together
        )
        values_per_grouping_key = self._aggregate_base_lines_aggregated_values(
            base_lines_aggregated_values
        )
        grouped_base_lines = [
            base_line
            for values in values_per_grouping_key.values()
            for base_line, _taxes_data in values["base_line_x_taxes_data"]
        ]
        expected_total_excluded = sum(
            values[f"total_excluded{suffix}"]
            for values in values_per_grouping_key.values()
        )
        raw_total_discount_amount = sum(
            base_line["tax_details"][f"raw_discount_amount{suffix}"]
            for base_line in grouped_base_lines
        )
        raw_total_gross_amount = sum(
            base_line["tax_details"][f"raw_gross_total_excluded{suffix}"]
            for base_line in grouped_base_lines
        )
        expected_total_gross_amount = expected_total_excluded + suffix_currency.round(
            raw_total_discount_amount
        )

        delta_raw_amount = self._get_delta_amount_to_reach_target(
            target_amount=expected_total_gross_amount,
            target_currency=suffix_currency,
            raw_current_amount=raw_total_gross_amount,
            raw_current_amount_precision_digits=precision_digits,
        )
        target_factors = [
            {
                "factor": base_line["tax_details"][f"raw_total_excluded{suffix}"],
                "base_line": base_line,
            }
            for base_line in grouped_base_lines
        ]
        amounts_to_distribute = self._distribute_delta_amount_smoothly(
            precision_digits=precision_digits,
            delta_amount=delta_raw_amount,
            target_factors=target_factors,
        )
        for target_factor, amount_to_distribute in zip(
            target_factors, amounts_to_distribute, strict=True
        ):
            base_line = target_factor["base_line"]
            base_line["tax_details"][f"raw_gross_total_excluded{suffix}"] += (
                amount_to_distribute
            )

    @api.model
    def _round_raw_gross_total_excluded_and_discount(
        self,
        base_lines,
        company,
        in_foreign_currency=True,
    ):
        if not base_lines:
            return

        suffix_currency = (
            base_lines[0]["currency_id"] if in_foreign_currency else company.currency_id
        )
        suffix = "_currency" if in_foreign_currency else ""

        current_gross_total_excluded = 0.0
        current_discount_amount = 0.0
        current_raw_discount_amount = 0.0
        for base_line in base_lines:
            tax_details = base_line["tax_details"]
            gross_total_excluded = tax_details[f"gross_total_excluded{suffix}"] = (
                float_round(
                    value=tax_details[f"raw_gross_total_excluded{suffix}"],
                    precision_rounding=suffix_currency.rounding,
                )
            )
            current_gross_total_excluded += gross_total_excluded

            raw_discount_amount = tax_details[f"raw_discount_amount{suffix}"]
            discount_amount = tax_details[f"discount_amount{suffix}"] = float_round(
                value=raw_discount_amount,
                precision_rounding=suffix_currency.rounding,
            )
            current_discount_amount += discount_amount
            current_raw_discount_amount += raw_discount_amount

        base_lines_aggregated_values = self._aggregate_base_lines_tax_details(
            base_lines, _group_everything_together
        )
        values_per_grouping_key = self._aggregate_base_lines_aggregated_values(
            base_lines_aggregated_values
        )
        expected_total_excluded = sum(
            values[f"total_excluded{suffix}"]
            for values in values_per_grouping_key.values()
        )

        expected_gross_total_excluded = expected_total_excluded + float_round(
            value=current_raw_discount_amount,
            precision_rounding=suffix_currency.rounding,
        )

        target_factors = [
            {
                "factor": 1.0,
                "base_line": base_line,
            }
            for base_line in base_lines
        ]
        expected_discount_amount = (
            expected_gross_total_excluded - expected_total_excluded
        )
        for field, delta_amount in (
            (
                f"gross_total_excluded{suffix}",
                expected_gross_total_excluded - current_gross_total_excluded,
            ),
            (
                f"discount_amount{suffix}",
                expected_discount_amount - current_discount_amount,
            ),
        ):
            amounts_to_distribute = self._distribute_delta_amount_smoothly(
                precision_digits=suffix_currency.decimal_places,
                delta_amount=delta_amount,
                target_factors=target_factors,
            )
            for target_factor, amount_to_distribute in zip(
                target_factors, amounts_to_distribute, strict=True
            ):
                target_factor["base_line"]["tax_details"][field] += amount_to_distribute

    @api.model
    def _round_raw_tax_amounts(
        self,
        base_lines_aggregated_values,
        company,
        precision_digits=6,
        apply_strict_tolerance=False,
        in_foreign_currency=True,
    ):
        if not base_lines_aggregated_values:
            return

        suffix_currency = (
            base_lines_aggregated_values[0][0]["currency_id"]
            if in_foreign_currency
            else company.currency_id
        )
        suffix = "_currency" if in_foreign_currency else ""

        for _base_line, aggregated_values in base_lines_aggregated_values:
            for values in aggregated_values.values():
                values[f"raw_tax_amount{suffix}"] = float_round(
                    values[f"raw_tax_amount{suffix}"], precision_digits=precision_digits
                )
                values[f"raw_base_amount{suffix}"] = float_round(
                    values[f"raw_base_amount{suffix}"],
                    precision_digits=precision_digits,
                )

        if apply_strict_tolerance:
            self._apply_raw_tax_amounts_tolerance(
                base_lines_aggregated_values, suffix, suffix_currency, precision_digits
            )

    @api.model
    def _apply_raw_tax_amounts_tolerance(
        self, base_lines_aggregated_values, suffix, suffix_currency, precision_digits
    ):
        tax_field = f"tax_amount{suffix}"
        raw_tax_field = f"raw_{tax_field}"
        base_field = f"base_amount{suffix}"
        raw_base_field = f"raw_{base_field}"
        values_per_grouping_key = self._aggregate_base_lines_aggregated_values(
            base_lines_aggregated_values
        )
        for grouping_key, values in values_per_grouping_key.items():
            tax_rate = (
                (values[raw_tax_field] / values[raw_base_field])
                if values[raw_base_field]
                else 0.0
            )

            target_factors = [
                {
                    "factor": aggregated_values[grouping_key][raw_tax_field],
                    "aggregated_values": aggregated_values[grouping_key],
                }
                for base_line, aggregated_values in base_lines_aggregated_values
                if grouping_key in aggregated_values
            ]

            expected_tax_amount = values[tax_field]
            current_raw_tax_amount = values[raw_tax_field]
            delta_raw_amount = self._get_delta_amount_to_reach_target(
                target_amount=expected_tax_amount,
                target_currency=suffix_currency,
                raw_current_amount=current_raw_tax_amount,
                raw_current_amount_precision_digits=precision_digits,
            )
            amounts_to_distribute = self._distribute_delta_amount_smoothly(
                precision_digits=precision_digits,
                delta_amount=delta_raw_amount,
                target_factors=target_factors,
            )
            for target_factor, amount_to_distribute in zip(
                target_factors, amounts_to_distribute, strict=True
            ):
                aggregated_values = target_factor["aggregated_values"]
                aggregated_values[raw_tax_field] += amount_to_distribute
                values[raw_tax_field] += amount_to_distribute
                if amount_to_distribute and tax_rate:
                    new_raw_base_amount = aggregated_values[raw_tax_field] / tax_rate
                    rounded_new_raw_base_amount = float_round(
                        new_raw_base_amount, precision_digits=precision_digits
                    )
                    values[raw_base_field] += (
                        rounded_new_raw_base_amount - aggregated_values[raw_base_field]
                    )
                    aggregated_values[raw_base_field] = rounded_new_raw_base_amount

            if tax_rate:
                current_tax_raw_base_amount = (
                    current_raw_tax_amount + delta_raw_amount
                ) / tax_rate
                delta_raw_amount = self._get_delta_amount_to_reach_target(
                    target_amount=current_tax_raw_base_amount,
                    target_currency=suffix_currency,
                    raw_current_amount=values[raw_base_field],
                    raw_current_amount_precision_digits=precision_digits,
                )
                amounts_to_distribute = self._distribute_delta_amount_smoothly(
                    precision_digits=precision_digits,
                    delta_amount=delta_raw_amount,
                    target_factors=target_factors,
                )
                for target_factor, amount_to_distribute in zip(
                    target_factors, amounts_to_distribute, strict=True
                ):
                    aggregated_values = target_factor["aggregated_values"]
                    aggregated_values[raw_base_field] += amount_to_distribute
                    values[raw_base_field] += amount_to_distribute


    def _get_repartition_tags(self, is_refund, repartition_type):
        document_type = "refund" if is_refund else "invoice"
        return self.repartition_line_ids.filtered(
            lambda x: (
                x.repartition_type == repartition_type
                and x.document_type == document_type
            )
        ).mapped("tag_ids")

    def _compute_all_special_mode(self, handle_price_include):
        if "force_price_include" in self.env.context:
            return (
                "total_included"
                if self.env.context["force_price_include"]
                else "total_excluded"
            )
        if not handle_price_include:
            return "total_excluded"
        return False

    def _compute_all_tax_values(self, tax_details, currency, partner, round_base):
        taxes = []
        void_amount = 0.0
        for tax_data in tax_details["taxes_data"]:
            tax = tax_data["tax"]
            for tax_rep_data in tax_data["tax_reps_data"]:
                rep_line = tax_rep_data["tax_rep"]
                taxes.append(
                    {
                        "id": tax.id,
                        "name": (partner and tax.with_context(lang=partner.lang).name)
                        or tax.name,
                        "amount": tax_rep_data["tax_amount_currency"],
                        "base": (
                            currency.round(tax_data["raw_base_amount_currency"])
                            if round_base
                            else tax_data["raw_base_amount_currency"]
                        ),
                        "sequence": tax.sequence,
                        "account_id": tax_rep_data["account"].id,
                        "analytic": tax.analytic,
                        "use_in_tax_closing": rep_line.use_in_tax_closing,
                        "is_reverse_charge": tax_data["is_reverse_charge"],
                        "price_include": tax.price_include,
                        "tax_exigibility": tax.tax_exigibility,
                        "tax_repartition_line_id": rep_line.id,
                        "group": tax_data["group"],
                        "tag_ids": tax_rep_data["tax_tags"].ids,
                        "tax_ids": tax_rep_data["taxes"].ids,
                    }
                )
                if not rep_line.account_id:
                    void_amount += tax_rep_data["tax_amount_currency"]
        return taxes, void_amount

    def compute_all(
        self,
        price_unit,
        currency=None,
        quantity=1.0,
        product=None,
        partner=None,
        is_refund=False,
        handle_price_include=True,
        rounding_method=None,
        *,
        include_caba_tags=False,
    ):
        if not self:
            company = self.env.company
        else:
            company = (
                self[0].company_id._accessible_branches()[:1] or self[0].company_id
            )

        currency = currency or company.currency_id
        special_mode = self._compute_all_special_mode(handle_price_include)
        base_line = self._prepare_base_line_for_taxes_computation(
            None,
            partner_id=partner,
            currency_id=currency,
            product_id=product,
            tax_ids=self,
            price_unit=price_unit,
            quantity=quantity,
            is_refund=is_refund,
            special_mode=special_mode,
        )
        self._add_tax_details_in_base_line(
            base_line, company, rounding_method=rounding_method
        )
        self._add_accounting_data_to_base_line_tax_details(
            base_line, company, include_caba_tags=include_caba_tags, rounded=False
        )

        tax_details = base_line["tax_details"]
        total_void = total_excluded = tax_details["raw_total_excluded_currency"]
        total_included = tax_details["raw_total_included_currency"]
        round_base = self.env.context.get("round_base", True)

        taxes, void_amount = self._compute_all_tax_values(
            tax_details, currency, partner, round_base
        )
        total_void += void_amount

        if round_base:
            total_excluded = currency.round(total_excluded)
            total_included = currency.round(total_included)

        return {
            "base_tags": base_line["tax_tag_ids"].ids,
            "taxes": taxes,
            "total_excluded": total_excluded,
            "total_included": total_included,
            "total_void": total_void,
        }


class AccountTaxRepartitionLine(models.Model):
    _inherit = "account.tax.repartition.line"

    account_id = fields.Many2one(
        string="Account",
        comodel_name="account.account",
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable', 'off_balance'))]",
        check_company=True,
        help="Account on which to post the tax amount",
    )
    tag_ids = fields.Many2many(
        string="Tax Grids",
        comodel_name="account.account.tag",
        domain=[("applicability", "=", "taxes")],
        copy=True,
        ondelete="restrict",
    )
    use_in_tax_closing = fields.Boolean(
        string="Tax Closing Entry",
        compute="_compute_use_in_tax_closing",
        store=True,
        readonly=False,
        precompute=True,
    )
    tag_ids_domain = fields.Binary(
        string="tag domain",
        help="Dynamic domain used for the tag that can be set on tax",
        compute="_compute_tag_ids_domain",
    )

    @api.depends(
        "company_id.multi_vat_foreign_country_ids",
        "company_id.account_fiscal_country_id",
    )
    def _compute_tag_ids_domain(self):
        for rep_line in self:
            allowed_country_ids = (
                False,
                rep_line.company_id.account_fiscal_country_id.id,
                *rep_line.company_id.multi_vat_foreign_country_ids.ids,
            )
            rep_line.tag_ids_domain = [
                ("applicability", "=", "taxes"),
                ("country_id", "in", allowed_country_ids),
            ]

    @api.depends("account_id", "repartition_type")
    def _compute_use_in_tax_closing(self):
        for rep_line in self:
            rep_line.use_in_tax_closing = (
                rep_line.repartition_type == "tax"
                and rep_line.account_id
                and rep_line.account_id.internal_group not in ("income", "expense")
            )

    @api.onchange("repartition_type")
    def _onchange_repartition_type(self):
        if self.repartition_type == "base":
            self.account_id = None

    def _get_aml_target_tax_account(self, force_caba_exigibility=False):
        self.ensure_one()
        if (
            not force_caba_exigibility
            and self.tax_id.tax_exigibility == "on_payment"
            and not self.env.context.get("caba_no_transition_account")
        ):
            return self.tax_id.cash_basis_transition_account_id
        else:
            return self.account_id
