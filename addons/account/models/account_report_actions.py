import base64
import re

from dateutil.relativedelta import relativedelta

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.service.model import get_public_method
from odoo.tools import SQL

from .account_report_engine import UNDISTR_LINE_NAME
from odoo.addons.account.tools.display_types import NON_ACCOUNTABLE_DISPLAY_TYPES
from odoo.addons.web.controllers.utils import clean_action


class AccountReportActions(models.Model):
    _inherit = "account.report"

    def action_view_report_form(self, options, params):
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.report",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": self.id,
        }

    def open_account_report_file_download_error_wizard(self, errors, content):
        self.check_singleton()

        model = "account.report.file.download.error.wizard"
        vals = {"actionable_errors": errors}

        if content:
            vals["file_name"] = content["file_name"]
            vals["file_content"] = base64.b64encode(
                re.sub(r"\n\s*\n", "\n", content["file_content"]).encode()
            )

        return {
            "type": "ir.actions.act_window",
            "res_model": model,
            "res_id": self.env[model].create(vals).id,
            "target": "new",
            "views": [(False, "form")],
        }

    def _get_caret_options(self):
        return {
            **self._caret_options_initializer_default(),
            **(
                self.env[self.custom_handler_model_name]._caret_options_initializer()
                if self.custom_handler_model_id
                else {}
            ),
        }

    def _caret_options_initializer_default(self):
        return {
            "account.account": [
                {
                    "name": _("General Ledger"),
                    "action": "caret_option_open_general_ledger",
                },
            ],
            "account.move": [
                {
                    "name": _("View Journal Entry"),
                    "action": "caret_option_open_record_form",
                },
            ],
            "account.move.line": [
                {
                    "name": _("View Journal Entry"),
                    "action": "caret_option_open_record_form",
                    "action_param": "move_id",
                },
            ],
            "account.payment": [
                {
                    "name": _("View Payment"),
                    "action": "caret_option_open_record_form",
                    "action_param": "payment_id",
                },
            ],
            "account.bank.statement": [
                {
                    "name": _("View Bank Statement"),
                    "action": "caret_option_open_statement_line_reco_widget",
                },
            ],
            "res.partner": [
                {"name": _("View Partner"), "action": "caret_option_open_record_form"},
            ],
        }

    def caret_option_open_record_form(self, options, params):
        model, record_id = self._get_model_info_from_id(params["line_id"])
        record = self.env[model].browse(record_id)
        target_record = (
            record[params["action_param"]] if "action_param" in params else record
        )

        view_id = self._resolve_caret_option_view(target_record)

        action = {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "views": [
                (view_id, "form")
            ],  # view_id will be False in case the default view is needed
            "res_model": target_record._name,
            "res_id": target_record.id,
            "context": self.env.context,
        }

        if view_id is not None:
            action["view_id"] = view_id

        return action

    def _get_caret_option_view_map(self):
        return {
            "account.payment": "account.view_account_payment_form",
            "res.partner": "base.view_partner_form",
            "account.move": "account.view_move_form",
        }

    def _resolve_caret_option_view(self, target):
        """Retrieve the target view of the caret option.

        :param target:  The target record of the redirection.
        :return: The id of the target view.
        """
        view_map = self._get_caret_option_view_map()

        view_xmlid = view_map.get(target._name)
        if not view_xmlid:
            return None

        return self.env["ir.model.data"]._get_xmlid_target(view_xmlid)[1]

    def caret_option_open_general_ledger(self, options, params):
        # When coming from a specific account, the unfold must only be retained
        # on the specified account. Better performance and more ergonomic
        # as it opens what client asked. And "Unfold All" is 1 clic away.
        options["unfold_all"] = True
        general_ledger = self.env.ref("account.general_ledger_report")
        account_id_to_search = self._get_res_id_from_line_id(
            params["line_id"], "account.account"
        )
        company_id_to_search = self._get_res_id_from_line_id(
            params["line_id"], "res.company"
        )
        if not account_id_to_search and not company_id_to_search:
            raise UserError(
                _(
                    "'Open General Ledger' caret option is only available form report lines targetting "
                    "accounts or Result Brought Forward."
                )
            )

        if account_id_to_search:
            search_content = (
                self.env["account.account"].browse(account_id_to_search).code
            )
        elif len(self.env.companies) == 1:
            search_content = str(UNDISTR_LINE_NAME)
        else:
            search_content = _(
                "%(line_name)s - %(company_name)s",
                line_name=UNDISTR_LINE_NAME,
                company_name=self.env["res.company"].browse(company_id_to_search).name,
            )
        gl_options = general_ledger.get_options(options)
        gl_options["not_reset_journals_filter"] = (
            True  # prevents resetting the default journal group
        )
        gl_options["unfold_all"] = True
        gl_options["filter_search_bar"] = search_content

        action_vals = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "account.action_account_report_general_ledger"
        )
        action_vals["params"] = {
            "options": gl_options,
            "ignore_session": True,
        }
        action_vals["context"] = dict(
            self.env["ir.actions.actions"]._eval_action_context(action_vals["context"]),
            default_filter_accounts=search_content,
        )

        return action_vals

    def caret_option_open_statement_line_reco_widget(self, options, params):
        model, record_id = self._get_model_info_from_id(params["line_id"])
        record = self.env[model].browse(record_id)
        if record._name == "account.bank.statement.line":
            return record.action_view_recon_st_line()
        elif record._name == "account.bank.statement":
            return record.action_view_bank_reconcile_widget()
        raise UserError(
            _(
                "'View Bank Statement' caret option is only available for report lines targeting bank statements."
            )
        )

    def dispatch_report_action(
        self, options, action, action_param=None, on_sections_source=False
    ):
        """Dispatches calls made by the client to either the report itself, or its custom handler if it exists.
        The action should be a public method, by definition, but a check is made to make sure
        it is not trying to call a private method.
        """
        self.check_singleton()

        if on_sections_source:
            report_to_call = self.env["account.report"].browse(
                options["sections_source_id"]
            )
            # on_sections_source and sections_source_id both come from the client,
            # so the link has to be checked here: without it the guard below can
            # never fire on this path, since the recursive call always lands on
            # the very report the options name. Recurse on a copy, too -- the
            # caller still holds the dict we were handed.
            #
            # _init_options_sections sets sections_source_id to self, or to the
            # selected variant; the client sets it to the composite report when a
            # section of one is on screen. Those three are the whole legitimate
            # set, and anything else is a dispatch onto an unrelated report.
            if report_to_call != self and not (
                self in report_to_call.section_report_ids
                or report_to_call in self.variant_report_ids
            ):
                raise UserError(
                    _(
                        "Trying to dispatch an action on a report unrelated to the provided sections source."
                    )
                )
            return report_to_call.dispatch_report_action(
                {**options, "report_id": report_to_call.id},
                action,
                action_param=action_param,
                on_sections_source=False,
            )

        if self.id not in (options["report_id"], options.get("sections_source_id")):
            raise UserError(
                _(
                    "Trying to dispatch an action on a report not compatible with the provided options."
                )
            )

        model = self
        custom_handler_model = self._get_custom_handler_model()
        if custom_handler_model and hasattr(self.env[custom_handler_model], action):
            model = self.env[custom_handler_model]
        report_method = get_public_method(model, action)
        args = [options, action_param] if action_param is not None else [options]
        return report_method(model, *args)

    def action_audit_cell(self, options, params):
        report_line = self.env["account.report.line"].browse(params["report_line_id"])
        expression_label = params["expression_label"]
        expression = report_line.expression_ids.filtered(
            lambda x: x.label == expression_label
        )
        column_group_options = self._get_column_group_options(
            options, params["column_group_key"]
        )

        # Audit of external values
        if expression.engine == "external":
            date_from, date_to = self._get_date_bounds_info(
                column_group_options, expression.date_scope
            )
            external_values_domain = [
                ("target_report_expression_id", "=", expression.id),
                ("date", "<=", date_to),
            ]
            if date_from:
                external_values_domain.append(("date", ">=", date_from))

            if expression.formula == "most_recent":
                query = self.env["account.report.external.value"]._search(
                    external_values_domain, bypass_access=True
                )
                rows = self.env.execute_query(
                    SQL(
                        """
                    SELECT ARRAY_AGG(id)
                    FROM %s
                    WHERE %s
                    GROUP BY date
                    ORDER BY date DESC
                    LIMIT 1
                """,
                        query.from_clause,
                        query.where_clause or SQL("TRUE"),
                    )
                )
                if rows:
                    external_values_domain = [("id", "in", rows[0][0])]

            return {
                "name": _("Manual values"),
                "type": "ir.actions.act_window",
                "res_model": "account.report.external.value",
                "view_mode": "list",
                "views": [(False, "list")],
                "domain": external_values_domain,
            }

        # Audit of move lines
        # If we're auditing a groupby line, we need to make sure to restrict the result of what we audit to the right group values
        column = next(
            (
                col
                for col in report_line.report_id.column_ids
                if col.expression_label == expression_label
            ),
            self.env["account.report.column"],
        )
        if column.custom_audit_action_id:
            action_dict = column.custom_audit_action_id._get_action_dict()
        else:
            action_dict = {
                "name": _("Journal Items"),
                "type": "ir.actions.act_window",
                "res_model": "account.move.line",
                "view_mode": "list",
                "views": [(False, "list")],
                "context": {
                    "active_test": False,
                },
            }

        action = clean_action(action_dict, env=self.env)
        action["domain"] = self._get_audit_line_domain(
            column_group_options, expression, params
        )
        return action

    def action_view_all_variants(self, options, params):
        return {
            "name": _("All Report Variants"),
            "type": "ir.actions.act_window",
            "res_model": "account.report",
            "view_mode": "list",
            "views": [(False, "list"), (False, "form")],
            "context": {
                "active_test": False,
            },
            "domain": [
                (
                    "id",
                    "in",
                    self._get_variants(options["variants_source_id"])
                    ._is_available_for(options)
                    .ids,
                )
            ],
        }

    def open_journal_items(self, options, params):
        """Open the journal items view with the proper filters and groups"""
        record_model, record_id = self._get_model_info_from_id(params.get("line_id"))
        view_id = (
            self.env.ref(params["view_ref"]).id if params.get("view_ref") else None
        )

        ctx = {
            "search_default_group_by_account": 1,
            "search_default_posted": 0 if options.get("all_entries") else 1,
            "date_from": options.get("date").get("date_from"),
            "date_to": options.get("date").get("date_to"),
            "search_default_journal_id": params.get("journal_id", False),
            "expand": 1,
        }

        if options["date"].get("date_from"):
            ctx["search_default_date_between"] = 1
        else:
            ctx["search_default_date_before"] = 1

        if options.get("selected_journal_groups"):
            ctx.update(
                {
                    "search_default_journal_group_id": [
                        options["selected_journal_groups"]["id"]
                    ],
                }
            )

        journal_type = params.get("journal_type")
        if journal_type or (
            options.get("selected_journal_groups")
            and options["selected_journal_groups"]["journal_types"]
        ):
            type_to_view_param = {
                "bank": {
                    "filter": "search_default_bank",
                    "view_id": self.env.ref(
                        "account.view_account_move_line_list_grouped_bank_cash"
                    ).id,
                },
                "cash": {
                    "filter": "search_default_cash",
                    "view_id": self.env.ref(
                        "account.view_account_move_line_list_grouped_bank_cash"
                    ).id,
                },
                "general": {
                    "filter": "search_default_misc_filter",
                    "view_id": self.env.ref(
                        "account.view_account_move_line_list_grouped_misc"
                    ).id,
                },
                "sale": {
                    "filter": "search_default_sales",
                    "view_id": self.env.ref(
                        "account.view_account_move_line_list_grouped_sales_purchases"
                    ).id,
                },
                "purchase": {
                    "filter": "search_default_purchases",
                    "view_id": self.env.ref(
                        "account.view_account_move_line_list_grouped_sales_purchases"
                    ).id,
                },
                "credit": {
                    "filter": "search_default_credit",
                    "view_id": self.env.ref("account.view_account_move_line_list").id,
                },
            }
            if options.get("selected_journal_groups"):
                ctx_to_update = {}
                for journal_type in options["selected_journal_groups"]["journal_types"]:
                    ctx_to_update[type_to_view_param[journal_type]["filter"]] = 1
                ctx.update(ctx_to_update)
            else:
                ctx.update(
                    {
                        type_to_view_param[journal_type]["filter"]: 1,
                    }
                )
            view_id = type_to_view_param[journal_type]["view_id"]

        action_domain = [("display_type", "not in", NON_ACCOUNTABLE_DISPLAY_TYPES)]

        if record_model == "account.group":
            if record_id:
                # NB: the root company id is passed as an *unquoted* text param,
                # exactly like the sibling branch below. Under psycopg3 a '%(name)s'
                # inside a SQL string literal is not substituted, so the previous
                # code_store->>'%(root_company_id)s' silently read the literal jsonb
                # key '%s' and matched no account (clicking a group showed nothing).
                query = SQL(
                    """
                    SELECT a.id
                      FROM account_account a
                      JOIN account_group ag
                           ON ag.code_prefix_start <= LEFT(a.code_store->>%(root_company_id)s, char_length(ag.code_prefix_start))
                              AND ag.code_prefix_end >= LEFT(a.code_store->>%(root_company_id)s, char_length(ag.code_prefix_end))
                              AND ag.company_id = %(root_company_id)s
                     WHERE ag.id = %(record_id)s
                           AND a.code_store ? %(root_company_id)s
                """,
                    root_company_id=str(self.env.company.root_id.id),
                    record_id=record_id,
                )
            else:
                query = SQL(
                    """
                    WITH relevant_accounts AS (
                        SELECT id, code_store->>%(root_company_id)s AS code
                          FROM account_account
                         WHERE code_store ? %(root_company_id)s
                    )
                  SELECT a.id
                    FROM relevant_accounts a
                   WHERE NOT EXISTS (
                        SELECT 1
                          FROM account_group ag
                         WHERE ag.company_id = %(root_company_id)s
                               AND LEFT(a.code, char_length(ag.code_prefix_start)) >= ag.code_prefix_start
                               AND LEFT(a.code, char_length(ag.code_prefix_end))   <= ag.code_prefix_end
                    )
                """,
                    root_company_id=str(self.env.company.root_id.id),
                )

            self.env.cr.execute(query)
            account_ids = [account[0] for account in self.env.cr.fetchall()]
            action_domain += [("account_id", "in", account_ids)]
        elif record_id is None:
            # Default filters don't support the 'no set' value. For this case, we use a domain on the action instead
            model_fields_map = {
                "account.account": "account_id",
                "res.partner": "partner_id",
                "account.journal": "journal_id",
            }
            model_field = model_fields_map.get(record_model)
            if model_field:
                action_domain += [(model_field, "=", False)]
        else:
            model_default_filters = {
                "account.account": "search_default_account_id",
                "res.partner": "search_default_partner_id",
                "account.journal": "search_default_journal_id",
                "product.product": "search_default_product_id",
                "product.category": "search_default_product_category_id",
            }
            model_filter = model_default_filters.get(record_model)
            if model_filter:
                ctx.update(
                    {
                        "active_id": record_id,
                        model_filter: [record_id],
                    }
                )

        if options:
            for account_type in options.get("account_type", []):
                ctx.update(
                    {
                        f"search_default_{account_type['id']}": (
                            account_type["selected"] and 1
                        )
                        or 0,
                    }
                )

            if options.get("journals") and not ctx["search_default_journal_id"]:
                selected_journals = [
                    journal["id"]
                    for journal in options["journals"]
                    if journal.get("selected")
                ]
                if len(selected_journals) == 1:
                    ctx["search_default_journal_id"] = selected_journals
                elif len(selected_journals) > 1:
                    ctx["search_default_journal_ids"] = True
                    ctx["journal_ids"] = selected_journals

            if options.get("analytic_accounts"):
                analytic_ids = [int(r) for r in options["analytic_accounts"]]
                ctx.update(
                    {
                        "search_default_analytic_accounts": 1,
                        "analytic_ids": analytic_ids,
                    }
                )

        return {
            "name": self._get_action_name(params, record_model, record_id),
            "view_mode": "list,pivot,graph,kanban",
            "res_model": "account.move.line",
            "views": [(view_id, "list")],
            "type": "ir.actions.act_window",
            "domain": action_domain,
            "context": ctx,
        }

    def open_unallocated_items_journal_items(self, options, params):
        _record_model, record_id = self._get_model_info_from_id(params.get("line_id"))
        fiscal_year = self.env.company.compute_fiscalyear_dates(
            fields.Date.to_date(options.get("date").get("date_from"))
        )
        options_for_audit = {
            **options,
            "date": {
                **options["date"],
                "date_from": fields.Date.to_string(fiscal_year["date_from"]),
                "date_to": fields.Date.to_string(fiscal_year["date_to"]),
            },
        }

        action = self.open_journal_items(options=options_for_audit, params=params)
        action["domain"] += self._get_unallocated_earnings_lines_domain(
            action["context"]["date_from"], record_id
        )
        action.get("context", {}).update({"search_default_date_between": 0})
        return action

    def open_unposted_moves(self, options, params=None):
        """Open the list of draft journal entries that might impact the reporting"""
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "account.action_move_journal_line"
        )
        action = clean_action(action, env=self.env)
        action["domain"] = [
            ("state", "=", "draft"),
            ("date", "<=", options["date"]["date_to"]),
        ]
        # overwrite the context to avoid default filtering on 'misc' journals
        action["context"] = {}
        return action

    def open_deferral_entries(self, options, params):
        domain = self._get_generated_deferral_entries_domain(options)
        deferral_line_ids = self.env["account.move"].search(domain).line_ids.ids
        return {
            "type": "ir.actions.act_window",
            "name": _("Deferred Entries"),
            "res_model": "account.move.line",
            "domain": [("id", "in", deferral_line_ids)],
            "views": [(False, "list"), (False, "form")],
            "context": {
                "search_default_group_by_move": True,
                "expand": True,
            },
        }

    def action_modify_manual_value(
        self,
        line_id,
        options,
        column_group_key,
        new_value_str,
        target_expression_id,
        rounding,
        json_friendly_column_group_totals,
    ):
        """Edit a manual value from the report, updating or creating the corresponding account.report.external.value object.

        :param options: The option dict the report is evaluated with.

        :param column_group_key: The string identifying the column group into which the change as manual value needs to be done.

        :param new_value_str: The new value to be set, as a string.

        :param rounding: The number of decimal digits to round with.

        :param json_friendly_column_group_totals: The expression totals by column group already computed for this report, in the format returned
                                                  by _get_json_friendly_column_group_totals. These will be used to reevaluate the report, recomputing
                                                  only the expressions depending on the newly-modified manual value, and keeping all the results
                                                  from the previous computations for the other ones.
        """
        self.check_singleton()

        target_column_group_options = self._get_column_group_options(
            options, column_group_key
        )
        self._init_currency_table(target_column_group_options)

        if target_column_group_options.get("compute_budget"):
            expressions_to_recompute = self.env["account.report.expression"].browse(
                target_expression_id
            ) + self.line_ids.expression_ids.filtered(
                lambda x: x.engine == "aggregation"
            )
            self._action_modify_manual_budget_value(
                line_id,
                target_column_group_options,
                new_value_str,
                target_expression_id,
                rounding,
            )
        else:
            expressions_to_recompute = self.line_ids.expression_ids.filtered(
                lambda x: x.engine in ("external", "aggregation")
            )
            self._action_modify_manual_external_value(
                target_column_group_options,
                new_value_str,
                target_expression_id,
                rounding,
            )

        # We recompute values for each column group, not only the one we modified a value in; this is important in case some date_scope is used to
        # retrieve the manual value from a previous period.

        all_column_groups_expression_totals = (
            self._convert_json_friendly_column_group_totals(
                json_friendly_column_group_totals,
                expressions_to_exclude=expressions_to_recompute,
            )
        )

        recomputed_expression_totals = self._compute_expression_totals_for_each_column_group(
            expressions_to_recompute,
            options,
            forced_all_column_groups_expression_totals=all_column_groups_expression_totals,
        )

        return {
            "lines": self._get_lines(
                options,
                all_column_groups_expression_totals=recomputed_expression_totals,
            ),
            "column_groups_totals": self._get_json_friendly_column_group_totals(
                recomputed_expression_totals
            ),
        }

    def action_display_inactive_sections(self, options):
        self.check_singleton()

        return {
            "type": "ir.actions.act_window",
            "name": _("Enable Sections"),
            "view_mode": "list,form",
            "res_model": "account.report",
            "domain": [
                ("section_main_report_ids", "in", options["sections_source_id"]),
                ("active", "=", False),
            ],
            "views": [(False, "list"), (False, "form")],
            "context": {
                "list_view_ref": "account.account_report_add_sections_tree",
                "active_test": False,
            },
        }

    def action_view_returns(self, options):

        date_to = options["date"]["date_to"]
        date_from = options["date"].get("date_from") or fields.Date.to_string(
            fields.Date.from_string(date_to) - relativedelta(months=3)
        )

        # If no return is found for the period and the return type, retry to generate them
        types_with_records = sum(
            (
                return_type
                for return_type, _return_count in self.env[
                    "account.return"
                ]._read_group(
                    domain=Domain(
                        [
                            ("type_id", "in", self.return_type_ids.ids),
                            ("date_to", ">=", date_from),
                            ("date_to", "<=", date_to),
                            ("company_id", "in", self.env.companies.ids),
                        ]
                    ),
                    groupby=["type_id"],
                    aggregates=["__count"],
                )
            ),
            self.env["account.return.type"],
        )

        types_without_record = self.return_type_ids - types_with_records
        if types_without_record:
            root_companies = (
                self.env["res.company"]
                .sudo()
                .search(
                    [
                        ("account_opening_date", "!=", False),
                        ("id", "parent_of", self.env.companies.ids),
                    ]
                )
            )
            self.env["account.return.type"].with_context(
                only_refresh_conditional_types=True
            )._generate_or_refresh_all_returns(root_companies)

        return self.env["account.return"].action_view_tax_return_view(
            additional_context={
                "filter_report_id": self.id,
                "search_default_filter_report_id": True,
            }
        )

    def action_create_composite_report(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.report",
            "views": [[False, "form"]],
            "context": {
                "default_section_report_ids": self.ids,
            },
        }
