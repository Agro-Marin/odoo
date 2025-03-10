# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class SaleReport(models.Model):
    _inherit = "sale.report"

    @api.model
    def _get_done_states(self):
        done_states = super()._get_done_states()
        done_states.extend(['paid', 'invoiced', 'done'])
        return done_states

    state = fields.Selection(
        selection_add=[
            ('paid', 'Paid'),
            ('invoiced', 'Invoiced'),
            ('done', 'Posted')
        ],
    )

    order_reference = fields.Reference(selection_add=[('pos.order', 'POS Order')])

    def _select_pos(self):
        select_ = f"""
            pos.company_id AS company_id,
            CONCAT('pos.order', ',', pos.id) AS order_reference,
            -MIN(l.id) AS id,
            pos.partner_id AS partner_id,
            partner.commercial_partner_id AS commercial_partner_id,
            partner.country_id AS country_id,
            partner.state_id AS state_id,
            partner.zip AS partner_zip,
            partner.industry_id AS industry_id,
            pos.pricelist_id AS pricelist_id,
            pos.crm_team_id AS team_id,
            pos.user_id AS user_id,
            NULL AS campaign_id,
            NULL AS medium_id,
            NULL AS source_id,
            pos.date_order AS date_order,
            pos.name AS name,
            (CASE WHEN pos.state = 'done' THEN 'sale' ELSE pos.state END) AS state,
            NULL as invoice_state,
            NULL AS line_invoice_state,
            l.product_id AS product_id,
            p.product_tmpl_id,
            t.categ_id AS product_category_id,
            t.uom_id AS product_uom_id,
            SUM(l.qty) AS product_uom_qty,
            (AVG(l.price_unit) / MIN({self._case_value_or_one('pos.currency_rate')}) * {self._case_value_or_one('account_currency_table.rate')}
            ) AS price_unit,
            (SUM(l.price_subtotal) / MIN({self._case_value_or_one('pos.currency_rate')}) * {self._case_value_or_one('account_currency_table.rate')}
            ) AS price_subtotal,
            (SUM(l.price_subtotal_incl) / MIN({self._case_value_or_one('pos.currency_rate')}) * {self._case_value_or_one('account_currency_table.rate')}
            ) AS price_total,
            l.discount AS discount,
            (SUM((l.price_unit * l.discount * l.qty / 100.0
                / {self._case_value_or_one('pos.currency_rate')}
                * {self._case_value_or_one('account_currency_table.rate')}))
            ) AS discount_amount,
            SUM(l.qty_delivered) AS qty_transfered,
            SUM(l.qty - l.qty_delivered) AS qty_to_transfer,
            CASE WHEN pos.account_move IS NOT NULL
                THEN SUM(l.qty) ELSE 0
            END AS qty_invoiced,
            CASE WHEN pos.account_move IS NULL
                THEN SUM(l.qty) ELSE 0
            END AS qty_to_invoice,
            (CASE WHEN pos.account_move IS NOT NULL THEN SUM(l.price_subtotal) ELSE 0 END)
                / MIN({self._case_value_or_one('pos.currency_rate')})
                * {self._case_value_or_one('account_currency_table.rate')}
            AS amount_invoiced_taxexc,
            (CASE WHEN pos.account_move IS NULL THEN SUM(l.price_subtotal) ELSE 0 END)
                / MIN({self._case_value_or_one('pos.currency_rate')})
                * {self._case_value_or_one('account_currency_table.rate')}
            AS amount_to_invoice_taxexc,
            (SUM(p.weight) * l.qty) AS weight,
            (SUM(p.volume) * l.qty) AS volume,
            count(*) AS nbr
        """

        additional_fields = self._select_additional_fields()
        additional_fields_info = self._fill_pos_fields(additional_fields)
        template = """,
            %s AS %s"""
        for fname, value in additional_fields_info.items():
            select_ += template % (value, fname)
        return select_

    def _available_additional_pos_fields(self):
        """Hook to replace the additional fields from sale with the one from pos_sale."""
        return {
            'warehouse_id': 'picking.warehouse_id',
        }

    def _fill_pos_fields(self, additional_fields):
        """Hook to fill additional fields for the pos_sale.

        :param values: dictionary of values to fill
        :type values: dict
        """
        filled_fields = {x: 'NULL' for x in additional_fields}
        for fname, value in self._available_additional_pos_fields().items():
            if fname in additional_fields:
                filled_fields[fname] = value
        return filled_fields

    def _from_pos(self):
        currency_table = self.env['res.currency']._get_simple_currency_table(self.env.companies)
        currency_table = self.env.cr.mogrify(currency_table).decode(
            self.env.cr.connection.encoding
        )
        return f"""
            pos_order_line l
            LEFT JOIN pos_order pos ON l.order_id = pos.id
            LEFT JOIN product_product p ON l.product_id=p.id
                LEFT JOIN res_partner partner ON (pos.partner_id=partner.id OR pos.partner_id = NULL)
                LEFT JOIN product_template t ON p.product_tmpl_id=t.id
                LEFT JOIN uom_uom u ON t.uom_id=u.id
                LEFT JOIN pos_session session ON pos.session_id=session.id
                LEFT JOIN pos_config config ON session.config_id=config.id
                LEFT JOIN stock_picking_type picking ON config.picking_type_id=picking.id
                JOIN {currency_table} ON pos.company_id=account_currency_table.company_id
        """


    def _where_pos(self):
        return """
            l.sale_order_line_id IS NULL"""

    def _group_by_pos(self):
        return """
            l.order_id,
            l.product_id,
            l.price_unit,
            l.discount,
            l.qty,
            t.uom_id,
            t.categ_id,
            pos.id,
            pos.name,
            pos.date_order,
            pos.partner_id,
            pos.user_id,
            pos.state,
            pos.company_id,
            pos.pricelist_id,
            p.product_tmpl_id,
            partner.commercial_partner_id,
            partner.country_id,
            partner.industry_id,
            partner.state_id,
            partner.zip,
            u.factor,
            pos.crm_team_id,
            account_currency_table.rate,
            picking.warehouse_id"""

    def _query(self):
        res = super()._query()
        return res + f"""UNION ALL (
            SELECT {self._select_pos()}
            FROM {self._from_pos()}
            WHERE {self._where_pos()}
            GROUP BY {self._group_by_pos()}
            )
        """
