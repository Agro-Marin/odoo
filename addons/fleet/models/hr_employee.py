# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class Employee(models.Model):
    _inherit = "hr.employee"


    vehicle_ids = fields.One2many(
        comodel_name="fleet.vehicle",
        inverse_name="driver_id",
        string="Vehicles (private)",
        groups="fleet.fleet_group_manager,hr.group_hr_user",
    )
    vehicle_count = fields.Integer(
        string="Cars",
        compute="_compute_vehicle_count",
        groups="fleet.fleet_group_manager",
    )
    license_plate = fields.Char(
        compute="_compute_license_plate",
        search="_search_license_plate",
        groups="hr.group_hr_user"
    )
    mobility_card = fields.Char(
        groups="fleet.fleet_group_user"
    )

    @api.depends("private_car_plate", "vehicle_ids.license_plate")
    def _compute_license_plate(self):
        for employee in self:
            if employee.private_car_plate and employee.vehicle_ids.license_plate:
                employee.license_plate = " ".join(employee.vehicle_ids.filtered("license_plate").mapped("license_plate") + [employee.private_car_plate])
            else:
                employee.license_plate = " ".join(employee.vehicle_ids.filtered("license_plate").mapped("license_plate")) or employee.private_car_plate

    def _compute_vehicle_count(self):
        driver_assignation_product = self.env.ref("fleet.product_product_driver_assignment")
        logs = self.env["fleet.vehicle.log"]._read_group(
            [("driver_id", "in", self.ids), ("product_id", "=", driver_assignation_product.id)],
            ["driver_id"],
            ["__count"]
        )
        cars_count = {driver.id: count for driver, count in logs}
        for employee in self:
            employee.vehicle_count = cars_count.get(employee.id, 0)

    def _search_license_plate(self, operator, value):
        employees = self.env["hr.employee"].search([
            "|",
            ("vehicle_ids.license_plate", operator, value),
            ("private_car_plate", operator, value)
        ])
        return [("id", "in", employees.ids)]

    def action_open_employee_vehicles(self):
        self.ensure_one()
        driver_assignation_product = self.env.ref("fleet.product_product_driver_assignment")
        action = self.env['ir.actions.act_window']._for_xml_id('fleet.action_fleet_vehicle_log')
        action["name"] = self.env._("Employee's cars history")
        action["views"] = [
            [self.env.ref("fleet.view_list_fleet_vehicle_log").id, "list"],
            [False, "form"]
        ],
        action["domain"] = [
            ("driver_id", "=", self.id),
            ("product_id", "=", driver_assignation_product.id),
        ]
        action["context"] = dict(
            self._context,
            default_driver_id=self.id,
            default_product_id=driver_assignation_product.id,
            search_default_groupby_product_category_id=False,
            hide_product=True,
            show_driver=True,
        )
        return action


class EmployeePublic(models.Model):
    _inherit = "hr.employee.public"


    mobility_card = fields.Char(readonly=True)
