from collections import defaultdict
from dateutil.relativedelta import relativedelta

from odoo import api, Command, fields, models, _
from odoo.addons.fleet.models.fleet_vehicle_model import FUEL_TYPES


# Some fields don"t have the exact same name
MODEL_FIELDS_TO_VEHICLE = {
    "transmission": "transmission",
    "electric_assistance": "electric_assistance",
    "color": "color",
    "seats": "seats",
    "doors": "doors",
    "trailer_hook": "trailer_hook",
    "default_co2": "co2",
    "co2_standard": "co2_standard",
    "default_fuel_type": "fuel_type",
    "fuel_tank_capacity": "fuel_tank_capacity",
    "fuel_efficiency": "fuel_efficiency",
    "cilinders": "cilinders",
    "power": "power",
    "power_unit": "power_unit",
    "horsepower": "horsepower",
    "horsepower_tax": "horsepower_tax",
    "vehicle_range": "vehicle_range",
    "model_year": "model_year",
    "category_id": "category_id",
}


class FleetVehicle(models.Model):
    _name = "fleet.vehicle"
    _inherit = ["mail.thread", "mail.activity.mixin", "avatar.mixin"]
    _description = "Vehicle"
    _order = "license_plate asc, acquisition_date asc"
    _rec_names_search = ["name", "driver_id.name"]

    def _get_default_state(self):
        state = self.env.ref(
            "fleet.fleet_vehicle_state_new_request", raise_if_not_found=False
        )
        return state if state and state.id else False

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    country_id = fields.Many2one(related="company_id.country_id")
    country_code = fields.Char(related="country_id.code", depends=["country_id"])
    name = fields.Char(compute="_compute_vehicle_name", store=True)
    active = fields.Boolean(string="Active", default=True, tracking=True)
    manager_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Manager",
        domain=lambda self: [
            ("groups_id", "in", self.env.ref("fleet.fleet_group_manager").id),
            ("company_id", "in", self.env.companies.ids),
        ],
    )
    driver_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Driver",
        domain=[("company_id", "in", (company_id, False))],
        copy=False,
        tracking=True,
        help="Driver address of the vehicle",
    )
    mobility_card = fields.Char(related="driver_id.mobility_card", store=True,)
    future_driver_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Future Driver",
        domain=[("company_id", "in", (company_id, False))],
        tracking=True,
        copy=False,
        help="Next Driver Address of the vehicle",
    )
    tag_ids = fields.Many2many(
        comodel_name="fleet.vehicle.tag",
        relation="fleet_vehicle_vehicle_tag_rel",
        column1="vehicle_tag_id",
        column2="tag_id",
        string="Tags",
        copy=False,
    )
    model_id = fields.Many2one(
        comodel_name="fleet.vehicle.model",
        string="Model",
        required=True,
        tracking=True,
    )
    brand_id = fields.Many2one(
        related="model_id.brand_id", store=True, string="Brand", readonly=False,
    )
    vehicle_type = fields.Selection(
        related="model_id.vehicle_type",
        store=True,
    )
    image_128 = fields.Image(
        related="model_id.image_128",
        readonly=True,
    )
    category_id = fields.Many2one(
        comodel_name="fleet.vehicle.model.category",
        string="Category",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
    )
    doors = fields.Integer(
        string="Doors Number",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
        help="Number of doors of the vehicle",
    )
    seats = fields.Integer(
        string="Seats Number",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
        help="Number of seats of the vehicle",
    )
    transmission = fields.Selection(
        [("manual", "Manual"), ("automatic", "Automatic")],
        string="Transmission",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
    )
    fuel_type = fields.Selection(
        FUEL_TYPES,
        string="Fuel Type",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
    )
    fuel_tank_capacity = fields.Integer(
        string="Tank capacity",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
        help="Fuel tank capacity in liters",
    )
    fuel_efficiency = fields.Float(
        compute="_compute_model_fields",
        store=True,
        readonly=False,
        aggregator="avg",
        help="Fuel efficiency in kilometers per liter (km/L)",
    )
    cilinders = fields.Integer(
        string="Cilinders Number",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
    )
    trailer_hook = fields.Boolean(
        string="Trailer Hitch",
        default=False,
        compute="_compute_model_fields",
        store=True,
        readonly=False,
    )
    power_unit = fields.Selection(
        [("power", "kW"), ("horsepower", "Horsepower"),],
        string="Power Unit",
        required=True,
        default="power",
    )
    power = fields.Integer(
        string="Power",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
        help="Power in kW of the vehicle",
    )
    horsepower = fields.Integer(
        compute="_compute_model_fields",
        store=True,
        readonly=False,
    )
    horsepower_tax = fields.Float(
        string="Horsepower Taxation",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
    )
    co2 = fields.Float(
        string="CO2 Emissions",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
        tracking=True,
        aggregator=None,
        help="CO2 emissions of the vehicle",
    )
    co2_standard = fields.Char(
        string="CO2 Standard",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
    )
    electric_assistance = fields.Boolean(
        compute="_compute_model_fields",
        store=True,
        readonly=False,
    )
    model_year = fields.Char(
        string="Model Year",
        compute="_compute_model_fields",
        store=True,
        readonly=False,
        help="Year of the model",
    )
    color = fields.Char(
        compute="_compute_model_fields",
        store=True,
        readonly=False,
        help="Color of the vehicle",
    )
    service_activity = fields.Selection(
        selection=[
            ("none", "None"),
            ("overdue", "Overdue"),
            ("today", "Today"),
        ],
        compute="_compute_service_activity",
    )
    odometer_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Odometer Unit",
        required=True,
        default=lambda self: self.env.ref("uom.product_uom_km").id,
        # TODO implement domain for new uom logic
        # domain=lambda self: [
        #     ("category_id", "=", self.env.ref("uom.uom_categ_length").id),
        # ],
        copy=True,
        help="Odometer measure of the vehicle",
    )
    odometer = fields.Float(
        string="Odometer",
        compute="_compute_odometer",
        readonly=True,
        help="Odometer measure of the vehicle",
    )
    vehicle_range = fields.Integer(string="Range")
    location = fields.Char(help="Location of the vehicle (garage, ...)")
    license_plate = fields.Char(
        tracking=True,
        help="License plate number of the vehicle (i = plate number for a car)",
    )
    vin_sn = fields.Char(
        string="Chassis Number",
        copy=False,
        tracking=True,
        help="Unique number written on the vehicle chassis (VIN/SN number).",
    )
    engine_sn = fields.Char(
        string="Engine SN",
        tracking=True,
        help="Unique number written on the vehicle engine.",
    )
    description = fields.Html("Vehicle Description")
    vehicle_properties = fields.Properties(
        string="Properties",
        definition="model_id.vehicle_properties_definition",
        copy=True,
    )
    acquisition_date = fields.Date(
        string="Registration Date",
        required=False,
        default=fields.Date.today,
        tracking=True,
        help="Date of vehicle registration",
    )
    write_off_date = fields.Date(
        string="Cancellation Date",
        tracking=True,
        help='Date when the vehicle"s license plate has been cancelled/removed.',
    )
    car_value = fields.Float(string="Catalog Value (VAT Incl.)", tracking=True)
    net_car_value = fields.Float(string="Purchase Value")
    residual_value = fields.Float()
    log_ids = fields.One2many("fleet.vehicle.log", "vehicle_id", "Logs")
    assignment_count = fields.Integer(
        "Drivers History Count", compute="_compute_count_all",
    )
    service_count = fields.Integer("Services", compute="_compute_count_all",)
    contract_count = fields.Integer("Contracts", compute="_compute_count_all",)
    first_contract_date = fields.Date(
        string="First Contract Date",
        default=fields.Date.today,
        tracking=True,
    )
    next_assignation_date = fields.Date(
        string="Assignment Date",
        help="This is the date at which the car will be available, "
        "if not set it means available instantly",
    )
    contract_renewal_due_soon = fields.Boolean(
        string="Has Contracts to renew",
        compute="_compute_contract_reminder",
        search="_search_contract_renewal_due_soon",
    )
    contract_renewal_overdue = fields.Boolean(
        string="Has Contracts Overdue",
        compute="_compute_contract_reminder",
        search="_search_get_overdue_contract_reminder",
    )
    contract_state = fields.Selection(
        selection=[
            ("futur", "Incoming"),
            ("open", "In Progress"),
            ("expired", "Expired"),
            ("closed", "Closed"),
        ],
        string="Last Contract State",
        required=False,
        compute="_compute_contract_reminder",
    )

    @api.model_create_multi
    def create(self, vals_list):
        ptc_values = [self._clean_vals_internal_user(vals) for vals in vals_list]
        vehicles = super().create(vals_list)
        for vehicle, vals, ptc_value in zip(vehicles, vals_list, ptc_values):
            if ptc_value:
                vehicle.sudo().write(ptc_value)
            if "driver_id" in vals and vals["driver_id"]:
                vehicle.create_driver_history(vals)
        return vehicles

    def write(self, vals):
        if "driver_id" in vals and vals["driver_id"]:
            driver_id = vals["driver_id"]
            for vehicle in self.filtered(lambda v: v.driver_id.id != driver_id):
                vehicle.create_driver_history(vals)

        if "active" in vals and not vals["active"]:
            self.env["fleet.vehicle.log"].search(
                [("vehicle_id", "in", self.ids)]
            ).active = False

        su_vals = self._clean_vals_internal_user(vals)
        if su_vals:
            self.sudo().write(su_vals)
        res = super(FleetVehicle, self).write(vals)
        return res

    def _track_subtype(self, init_values):
        self.ensure_one()
        if "driver_id" in init_values or "future_driver_id" in init_values:
            return self.env.ref("fleet.mt_fleet_driver_updated")

        return super(FleetVehicle, self)._track_subtype(init_values)

    @api.depends("model_id")
    def _compute_model_fields(self):
        """
        Copies all the related fields from the model to the vehicle
        """
        model_values = dict()
        for vehicle in self.filtered("model_id"):
            if vehicle.model_id.id in model_values:
                write_vals = model_values[vehicle.model_id.id]
            else:
                # copy if value is truthy
                write_vals = {
                    MODEL_FIELDS_TO_VEHICLE[key]: vehicle.model_id[key]
                    for key in MODEL_FIELDS_TO_VEHICLE
                    if vehicle.model_id[key]
                }
                model_values[vehicle.model_id.id] = write_vals
            vehicle.update(write_vals)

    @api.depends("model_id.brand_id.name", "model_id.name", "license_plate")
    def _compute_vehicle_name(self):
        for vehicle in self:
            vehicle.name = (
                (vehicle.model_id.brand_id.name or "")
                + "/"
                + (vehicle.model_id.name or "")
                + "/"
                + (vehicle.license_plate or _("No Plate"))
            )
            # vehicle.name = f"{vehicle.model_id.brand_id.name or ""}/{vehicle.model_id.name or ""}/{vehicle.license_plate or _("No Plate")}"

    @api.depends("log_ids")
    def _compute_service_activity(self):
        service_category = self.env.ref("fleet.product_category_vehicle_maintenance")
        for vehicle in self:
            activities_state = set(
                state
                for state in vehicle.log_ids.filtered(lambda x: x.product_category_id == service_category).mapped("activity_state")
                if state and state != "planned"
            )
            vehicle.service_activity = (
                sorted(activities_state)[0] if activities_state else "none"
            )

    @api.depends("log_ids")
    def _compute_contract_reminder(self):
        contract_product_category = self.env.ref("fleet.product_category_vehicle_contracts")
        params = self.env["ir.config_parameter"].sudo()
        delay_alert_contract = int(
            params.get_param("hr_fleet.delay_alert_contract", default=30)
        )
        current_date = fields.Date.context_today(self)
        data = self.env["fleet.vehicle.log"]._read_group(
            domain=[
                ("date_end", "!=", False),
                ("vehicle_id", "in", self.ids),
                ("product_category_id", "=", contract_product_category.id),
                ("state", "!=", "closed"),
            ],
            groupby=["vehicle_id", "state"],
            aggregates=["date_end:max"],
        )
        prepared_data = {}
        for vehicle_id, state, date_end in data:
            if prepared_data.get(vehicle_id.id):
                if prepared_data[vehicle_id.id]["date_end"] < date_end:
                    prepared_data[vehicle_id.id]["date_end"] = date_end
                    prepared_data[vehicle_id.id]["state"] = state
            else:
                prepared_data[vehicle_id.id] = {
                    "state": state,
                    "date_end": date_end,
                }
        for vehicle in self:
            vehicle_data = prepared_data.get(vehicle.id)
            if vehicle_data:
                diff_time = (vehicle_data["date_end"] - current_date).days
                vehicle.contract_renewal_overdue = diff_time < 0
                vehicle.contract_renewal_due_soon = (
                    not vehicle.contract_renewal_overdue
                    and (diff_time < delay_alert_contract)
                )
                vehicle.contract_state = vehicle_data["state"]
            else:
                vehicle.contract_renewal_overdue = False
                vehicle.contract_renewal_due_soon = False
                vehicle.contract_state = ""

    @api.depends("log_ids", "log_ids.odometer")
    def _compute_odometer(self):
        for vehicle in self:
            if vehicle.log_ids:
                vehicle.odometer = max(vehicle.log_ids.mapped("odometer"))
            else:
                vehicle.odometer = 0.0

    def _compute_count_all(self):
        Log = self.env["fleet.vehicle.log"].with_context(active_test=False)
        service_product_category = self.env.ref("fleet.product_category_vehicle_maintenance")
        contract_product_category = self.env.ref("fleet.product_category_vehicle_contracts")
        driver_assignation_product = self.env.ref("fleet.product_product_driver_assignment")

        contract_data = Log._read_group(
            [
                ("vehicle_id", "in", self.ids),
                ("product_category_id", "=", contract_product_category.id),
                ("state", "!=", "closed"),
            ],
            ["vehicle_id", "active"],
            ["__count"],
        )
        service_data = Log._read_group(
            [("vehicle_id", "in", self.ids), ("product_category_id", "=", service_product_category.id)],
            ["vehicle_id", "active"],
            ["__count"],
        )
        history_data = Log._read_group(
            [("vehicle_id", "in", self.ids), ("product_id", "=", driver_assignation_product.id)],
            ["vehicle_id"],
            ["__count"],
        )

        mapped_contract_data = defaultdict(lambda: defaultdict(lambda: 0))
        mapped_service_data = defaultdict(lambda: defaultdict(lambda: 0))
        mapped_history_data = defaultdict(lambda: 0)

        for vehicle, active, count in contract_data:
            mapped_contract_data[vehicle.id][active] = count
        for vehicle, active, count in service_data:
            mapped_service_data[vehicle.id][active] = count
        for vehicle, count in history_data:
            mapped_history_data[vehicle.id] = count

        for vehicle in self:
            vehicle.contract_count = mapped_contract_data[vehicle.id][vehicle.active]
            vehicle.service_count = mapped_service_data[vehicle.id][vehicle.active]
            vehicle.assignment_count = mapped_history_data[vehicle.id]

    def _search_contract_renewal_due_soon(self, operator, value):
        params = self.env["ir.config_parameter"].sudo()
        delay_alert_contract = int(
            params.get_param("hr_fleet.delay_alert_contract", default=30)
        )
        contract_product_category = self.env.ref("fleet.product_category_vehicle_contracts")
        res = []
        assert operator in ("=", "!=", "<>") and value in (
            True,
            False,
        ), "Operation not supported"
        if (operator == "=" and value is True) or (
            operator in ("<>", "!=") and value is False
        ):
            search_operator = "in"
        else:
            search_operator = "not in"
        today = fields.Date.context_today(self)
        datetime_today = fields.Datetime.from_string(today)
        limit_date = fields.Datetime.to_string(
            datetime_today + relativedelta(days=+delay_alert_contract)
        )
        res_ids = (
            self.env["fleet.vehicle.log"]
            .search(
                [
                    ("date_end", ">", today),
                    ("date_end", "<", limit_date),
                    ("product_category_id", "=", contract_product_category.id),
                    ("state", "in", ["open", "expired"]),
                ]
            )
            .mapped("vehicle_id")
            .ids
        )
        res.append(("id", search_operator, res_ids))
        return res

    def _search_get_overdue_contract_reminder(self, operator, value):
        res = []
        assert operator in ("=", "!=", "<>") and value in (
            True,
            False,
        ), "Operation not supported"
        if (operator == "=" and value is True) or (
            operator in ("<>", "!=") and value is False
        ):
            search_operator = "in"
        else:
            search_operator = "not in"
        today = fields.Date.context_today(self)
        # get the id of vehicles that have overdue contracts
        # but exclude those for which a new contract has already been created for them
        vehicle_ids = self.env["fleet.vehicle"]._search(
            [
                (
                    "contract_ids",
                    "any",
                    [
                        ("date_end", "!=", False),
                        ("date_end", "<", today),
                        ("state", "in", ["open", "expired"]),
                    ],
                ),
                "!",
                (
                    "contract_ids",
                    "any",
                    [
                        ("date_end", "!=", False),
                        ("date_end", ">=", today),
                        ("state", "in", ["open", "futur"]),
                    ],
                ),
            ]
        )
        res.append(("id", search_operator, vehicle_ids))
        return res

    def _clean_vals_internal_user(self, vals):
        # Fleet administrator may not have rights to write on partner
        # related fields when the driver_id is a res.user.
        # This trick is used to prevent access right error.
        su_vals = {}
        if self.env.su:
            return su_vals

        return su_vals

    def _get_analytic_name(self):
        # This function is used in fleet_account and is overrided in l10n_be_hr_payroll_fleet
        return self.license_plate or _("No plate")

    def _get_driver_history_data(self, vals):
        self.ensure_one()
        driver_assignation_product = self.env.ref("fleet.product_product_driver_assignment")
        return {
            "vehicle_id": self.id,
            "driver_id": vals["driver_id"],
            "product_id": driver_assignation_product.id,
            "product_category_id": driver_assignation_product.categ_id.id,
            "date_start": fields.Date.today(),
            "odometer": self.odometer,
        }

    def create_driver_history(self, vals):
        for vehicle in self:
            self.env["fleet.vehicle.log"].create(vehicle._get_driver_history_data(vals))

    def accept_driver_change(self):
        # Find all the vehicles of the same type for which the driver is the future_driver_id
        # remove their driver_id and close their history using current date
        vehicles = self.search(
            [
                ("driver_id", "in", self.mapped("future_driver_id").ids),
                ("vehicle_type", "=", self.vehicle_type),
            ]
        )
        vehicles.write({"driver_id": False})
        for vehicle in self:
            vehicle.driver_id = vehicle.future_driver_id
            vehicle.future_driver_id = False

    def action_view_assignation_logs(self):
        self.ensure_one()
        driver_assignation_product = self.env.ref("fleet.product_product_driver_assignment")
        action = self.env['ir.actions.act_window']._for_xml_id('fleet.action_fleet_vehicle_log')
        action["domain"] = [
            ("vehicle_id", "=", self.id),
            ("product_id", "=", driver_assignation_product.id),
        ]
        action['context'] = {
            "default_driver_id": self.driver_id.id,
            "default_vehicle_id": self.id,
            "default_product_category_id": driver_assignation_product.categ_id.id,
            "default_product_id": driver_assignation_product.id,
            "hide_product_category": True,
            "hide_product": True,
            "show_driver": True,
            "search_default_groupby_product_category_id": False,
        }
        return action

    def action_view_contract_logs(self):
        self.ensure_one()
        contract_product_category = self.env.ref("fleet.product_category_vehicle_contracts")
        action = self.env['ir.actions.act_window']._for_xml_id('fleet.action_fleet_vehicle_log')
        action["domain"] = [
            ("vehicle_id", "=", self.id),
            ("product_category_id", "=", contract_product_category.id),
        ]
        action['context'] = {
            "default_vehicle_id": self.id,
            "default_product_category_id": contract_product_category.id,
            "hide_product_category": True,
            "show_vendor": True,
            "search_default_groupby_product_category_id": False,
        }
        return action

    def action_view_service_logs(self):
        self.ensure_one()
        service_product_category = self.env.ref("fleet.product_category_vehicle_maintenance")
        action = self.env['ir.actions.act_window']._for_xml_id('fleet.action_fleet_vehicle_log')
        action["domain"] = [
            ("vehicle_id", "=", self.id),
            ("product_category_id", "=", service_product_category.id),
        ]
        action['context'] = {
            "default_vehicle_id": self.id,
            "default_product_category_id": service_product_category.id,
            "hide_product_category": True,
            "show_vendor": True,
            "search_default_groupby_product_category_id": False,
        }
        return action
