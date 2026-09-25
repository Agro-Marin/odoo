import functools
import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class MixinOrderProductMatrix(models.AbstractModel):
    _name = "mixin.order.product.matrix"
    _description = "Order Variant Grid"

    _matrix_display_extra_price = False

    report_grids = fields.Boolean(
        string="Print Variant Grids",
        default=True,
        help="If set, the matrix of configurable products will be shown on the report of this order.",
    )
    grid_product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        store=False,
        help="Technical field for product_matrix functionalities.",
    )
    grid_update = fields.Boolean(
        default=False,
        store=False,
        help="Whether the grid field contains a new matrix to apply or not.",
    )
    grid = fields.Char(
        string="Matrix local storage",
        store=False,
        help="Technical storage of grid. \nIf grid_update, will be loaded on the order. \nIf not, represents the matrix to open.",
    )

    @api.onchange("grid_product_tmpl_id")
    def _set_grid_up(self):
        if self.grid_product_tmpl_id:
            self.grid_update = False
            self.grid = json.dumps(self._get_matrix(self.grid_product_tmpl_id))

    @api.onchange("grid")
    def _apply_grid(self):
        if not (self.grid and self.grid_update):
            return
        grid = json.loads(self.grid)
        product_template = self.env["product.template"].browse(
            grid["product_template_id"]
        )
        Attrib = self.env["product.template.attribute.value"]
        default_line_vals = {}
        new_lines = []
        for cell in grid["changes"]:
            combination = Attrib.browse(cell["ptav_ids"])
            no_variant_attribute_values = (
                combination - combination._without_no_variant_attributes()
            )
            product = product_template._create_product_variant(combination)
            order_lines = self._get_matrix_cell_lines(
                product, no_variant_attribute_values
            )
            qty = cell["qty"]
            if not qty - sum(order_lines.mapped("product_qty")):
                continue

            if order_lines:
                if qty == 0:
                    if self.state in ["draft", "sent"]:
                        self.line_ids -= order_lines
                    else:
                        order_lines.update({"product_qty": 0.0})
                    continue
                # several lines of one variant would each lose their own
                # business logic if merged, so the grid refuses to pick one
                if len(order_lines) > 1:
                    _debug.logic("matrix_qty_refused", lines=order_lines)
                    raise ValidationError(self._get_matrix_line_conflict_message())
                order_lines[0].product_qty = qty
                continue

            if not default_line_vals:
                OrderLine = self.env[self._get_line_model()]
                default_line_vals = OrderLine.default_get(OrderLine._fields.keys())
            last_sequence = self.line_ids[-1:].sequence
            if last_sequence:
                default_line_vals["sequence"] = last_sequence
            new_lines.append(
                (
                    0,
                    0,
                    dict(
                        default_line_vals,
                        product_id=product.id,
                        product_qty=qty,
                        product_no_variant_attribute_value_ids=no_variant_attribute_values.ids,
                    ),
                )
            )
        _debug.pipeline("matrix_applied", order=self._origin, new_lines=len(new_lines))
        if new_lines:
            self.update({"line_ids": new_lines})

    def _get_matrix_line_conflict_message(self):
        raise NotImplementedError(
            f"{self._name} must implement _get_matrix_line_conflict_message()"
        )

    def _is_matrix_excluded_line(self, line):
        return False

    def _get_matrix_cell_lines(self, product, no_variant_attribute_values):
        return self.line_ids.filtered(
            lambda line: (
                (line._origin or line).product_id == product
                and (line._origin or line).product_no_variant_attribute_value_ids
                == no_variant_attribute_values
                and not self._is_matrix_excluded_line(line)
            )
        )

    def _get_matrix(self, product_template):
        def has_ptavs(line, sorted_attr_ids):
            pav = (
                line.product_no_variant_attribute_value_ids.ids
                + line.product_template_attribute_value_ids.ids
            )
            pav.sort()
            return pav == sorted_attr_ids

        matrix = product_template._get_template_matrix(
            company_id=self.company_id,
            currency_id=self.currency_id,
            display_extra_price=self._matrix_display_extra_price,
        )
        if self.line_ids:
            order_lines = self.line_ids.filtered(
                lambda line: line.product_template_id == product_template
            )
            for row in matrix["matrix"]:
                for cell in row:
                    if cell.get("name", False):
                        continue
                    matching_lines = order_lines.filtered(
                        functools.partial(has_ptavs, sorted_attr_ids=cell["ptav_ids"])
                    )
                    if matching_lines and not any(
                        self._is_matrix_excluded_line(line) for line in matching_lines
                    ):
                        cell.update({"qty": sum(matching_lines.mapped("product_qty"))})
        return matrix

    def _get_matrix_report_templates(self):
        return self.line_ids.filtered("is_configurable_product").product_template_id

    def get_report_matrixes(self):
        matrixes = []
        if not self.report_grids:
            return matrixes
        lines_by_template = self.line_ids.grouped("product_template_id")
        for template in self._get_matrix_report_templates():
            if len(lines_by_template[template]) > 1:
                matrix = self._get_matrix(template)
                matrix["matrix"] = [
                    row
                    for row in matrix["matrix"]
                    if any(column["qty"] != 0 for column in row[1:])
                ]
                matrixes.append(matrix)
        return matrixes
