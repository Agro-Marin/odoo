import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from random import choice
from string import digits

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models, tools
from odoo.exceptions import AccessError, RedirectWarning, UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.datetime import localize_standard, timezone
from odoo.libs.numbers import float_is_zero
from odoo.tools import SQL, Query, convert, email_normalize, format_time

from odoo.addons.hr.models.hr_version import format_date_abbr
from odoo.addons.mail.tools.discuss import Store

_ALLOW_READ_HR_EMPLOYEE = object()


class HrEmployee(models.Model):
    _name = "hr.employee"
    _description = "Employee"
    _order = "name"
    _inherit = [
        "mixin.mail.thread.main.attachment",
        "mixin.mail.activity",
        "mixin.resource",
    ]
    _mail_post_access = "read"
    _primary_email = "work_email"
    _mail_partner_fields = ("partner_id",)
    _inherits = {"hr.version": "version_id", "res.partner": "partner_id"}

    _DIRTY_HACK_PRIVATE_FIELDS = (
        "activity_calendar_event_id",
        "rating_ids",
        "website_message_ids",
        "message_has_sms_error",
    )

    company_id = fields.Many2one(
        "res.company",
        required=True,
        tracking=True,
    )
    company_country_id = fields.Many2one(
        "res.country",
        "Company Country",
        related="company_id.country_id",
        readonly=True,
        groups="base.group_system,hr.group_hr_user",
    )
    company_country_code = fields.Char(
        related="company_country_id.code",
        depends=["company_country_id"],
        readonly=True,
        groups="base.group_system,hr.group_hr_user",
        string="Company Country Code",
    )
    country_code = fields.Char(
        related="version_id.country_code",
        inherited=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
        groups="hr.group_hr_user",
    )
    resource_id = fields.Many2one(
        "resource.resource",
        required=True,
    )
    name = fields.Char(
        related="partner_id.name",
        inherited=True,
        string="Employee Name",
        store=True,
        readonly=False,
        tracking=True,
    )
    active = fields.Boolean(
        "Active",
        related="resource_id.active",
        default=True,
        store=True,
        readonly=False,
    )
    user_id = fields.Many2one(
        "res.users",
        related="resource_id.user_id",
        string="User",
        store=True,
        readonly=False,
        copy=False,
        check_company=True,
        precompute=True,
        index="btree_not_null",
        ondelete="restrict",
    )
    share = fields.Boolean(
        related="user_id.share",
    )

    version_id = fields.Many2one(
        "hr.version",
        required=True,
        compute="_compute_version_id",
        compute_sudo=True,
        store=False,
        search="_search_version_id",
        ondelete="cascade",
        groups="hr.group_hr_user",
    )
    resource_calendar_id = fields.Many2one(
        related="version_id.resource_calendar_id",
        inherited=True,
        index=False,
        store=False,
        check_company=True,
    )
    work_location_id = fields.Many2one(
        related="version_id.work_location_id",
        inherited=True,
        store=False,
        check_company=True,
    )
    current_version_id = fields.Many2one(
        "hr.version",
        compute="_compute_current_version_id",
        compute_sudo=True,
        store=True,
        bypass_search_access=True,
    )
    current_date_version = fields.Date(
        related="current_version_id.date_version",
        string="Current Date Version",
        groups="hr.group_hr_user",
    )
    version_ids = fields.One2many(
        "hr.version",
        "employee_id",
        string="Employee Versions",
        groups="hr.group_hr_user",
    )
    versions_count = fields.Integer(
        compute="_compute_versions_count",
        groups="hr.group_hr_user",
    )

    hr_presence_state = fields.Selection(
        [
            ("present", "Present"),
            ("absent", "Absent"),
            ("archive", "Archived"),
            ("out_of_working_hour", "Off-Hours"),
        ],
        compute="_compute_hr_presence_state",
    )
    last_activity = fields.Date(
        compute="_compute_last_activity_and_time",
    )
    last_activity_time = fields.Char(
        compute="_compute_last_activity_and_time",
    )
    hr_icon_display = fields.Selection(
        [
            ("presence_present", "Present"),
            ("presence_out_of_working_hour", "Off-Hours"),
            ("presence_absent", "Absent"),
            ("presence_archive", "Archived"),
            ("presence_undetermined", "Undetermined"),
        ],
        compute="_compute_presence_icon",
    )
    show_hr_icon_display = fields.Boolean(
        compute="_compute_presence_icon",
    )
    newly_hired = fields.Boolean(
        "Newly Hired",
        compute="_compute_newly_hired",
        search="_search_newly_hired",
    )

    work_phone = fields.Char(
        "Work Phone",
        tracking=True,
        compute="_compute_work_contact_details",
        store=True,
        readonly=False,
        inverse="_inverse_work_contact_details",
    )
    mobile_phone = fields.Char("Work Mobile")
    work_email = fields.Char(
        "Work Email",
        compute="_compute_work_contact_details",
        store=True,
        inverse="_inverse_work_contact_details",
    )
    partner_id = fields.Many2one(
        "res.partner",
        "Contact",
        required=True,
        ondelete="restrict",
        copy=False,
        index=True,
    )
    legal_name = fields.Char(
        compute="_compute_legal_name",
        store=True,
        readonly=False,
        groups="hr.group_hr_user",
    )
    is_user_active = fields.Boolean(
        related="user_id.active",
        string="User's active",
        groups="hr.group_hr_user",
    )
    private_phone = fields.Char(
        string="Private Phone",
        related="private_address_id.phone",
        readonly=False,
        groups="hr.group_hr_user",
    )
    private_email = fields.Char(
        string="Private Email",
        related="private_address_id.email",
        readonly=False,
        groups="hr.group_hr_user",
    )
    place_of_birth = fields.Char(
        "Place of Birth",
        tracking=True,
        groups="hr.group_hr_user",
    )
    country_id = fields.Many2one(
        "res.country",
        "Nationality (Country)",
        related="private_address_id.nationality_id",
        readonly=False,
        tracking=True,
        groups="hr.group_hr_user",
    )
    country_of_birth = fields.Many2one(
        "res.country",
        string="Country of Birth",
        tracking=True,
        groups="hr.group_hr_user",
    )
    birthday = fields.Date(
        "Birthday",
        related="private_address_id.birthdate",
        readonly=False,
        store=True,
        tracking=True,
        groups="hr.group_hr_user",
    )
    birthday_public_display = fields.Boolean(
        "Show to all employees",
        default=False,
        groups="hr.group_hr_user",
    )
    birthday_public_display_string = fields.Char(
        "Public Date of Birth",
        compute="_compute_birthday_public_display_string",
    )
    identification_id = fields.Char(
        string="Identification No",
        compute="_compute_identifiers",
        inverse="_inverse_identifiers",
        search="_search_identification_id",
        compute_sudo=True,
        tracking=True,
        groups="hr.group_hr_user",
        help="Enter the employee's National Identification Number issued by the government (e.g., Aadhaar, SIN, NIN). This is used for official records and statutory compliance.",
    )
    ssnid = fields.Char(
        "SSN No",
        compute="_compute_identifiers",
        inverse="_inverse_identifiers",
        search="_search_ssnid",
        compute_sudo=True,
        help="Social Security Number",
        tracking=True,
        groups="hr.group_hr_user",
    )
    passport_id = fields.Char(
        "Passport No",
        compute="_compute_identifiers",
        inverse="_inverse_identifiers",
        search="_search_passport_id",
        compute_sudo=True,
        tracking=True,
        groups="hr.group_hr_user",
    )
    passport_expiration_date = fields.Date(
        "Passport Expiration Date",
        compute="_compute_identifiers",
        inverse="_inverse_identifiers",
        compute_sudo=True,
        tracking=True,
        groups="hr.group_hr_user",
    )
    sex = fields.Selection(
        string="Gender",
        related="private_address_id.gender",
        readonly=False,
        tracking=True,
        groups="hr.group_hr_user",
        help="This is the legal sex recognized by the state.",
    )

    private_address_id = fields.Many2one(
        "res.partner",
        string="Private Address",
        compute="_compute_private_address_id",
        store=True,
        groups="hr.group_hr_user",
        copy=False,
        index="btree_not_null",
        help="The employee's home address, held as a private child of their "
        "work contact rather than as columns here.",
    )
    private_street = fields.Char(
        string="Private Street",
        related="private_address_id.street",
        readonly=False,
        tracking=True,
        groups="hr.group_hr_user",
    )
    private_street2 = fields.Char(
        string="Private Street2",
        related="private_address_id.street2",
        readonly=False,
        tracking=True,
        groups="hr.group_hr_user",
    )
    private_city = fields.Char(
        string="Private City",
        related="private_address_id.city",
        readonly=False,
        tracking=True,
        groups="hr.group_hr_user",
    )
    allowed_country_state_ids = fields.Many2many(
        "res.country.state",
        compute="_compute_allowed_country_state_ids",
        groups="hr.group_hr_user",
    )
    private_state_id = fields.Many2one(
        "res.country.state",
        string="Private State",
        related="private_address_id.state_id",
        readonly=False,
        domain="[('id', 'in', allowed_country_state_ids)]",
        tracking=True,
        groups="hr.group_hr_user",
    )
    private_zip = fields.Char(
        string="Private Zip",
        related="private_address_id.zip",
        readonly=False,
        tracking=True,
        groups="hr.group_hr_user",
    )
    private_country_id = fields.Many2one(
        "res.country",
        string="Private Country",
        related="private_address_id.country_id",
        readonly=False,
        tracking=True,
        groups="hr.group_hr_user",
    )
    marital = fields.Selection(
        selection="_selection_marital_status",
        string="Marital Status",
        groups="hr.group_hr_user",
        default="single",
        required=True,
        tracking=True,
    )
    spouse_complete_name = fields.Char(
        string="Spouse Legal Name",
        groups="hr.group_hr_user",
        tracking=True,
    )
    spouse_birthdate = fields.Date(
        string="Spouse Birthdate",
        groups="hr.group_hr_user",
        tracking=True,
    )
    children = fields.Integer(
        string="Dependent Children",
        groups="hr.group_hr_user",
        tracking=True,
    )
    emergency_contact = fields.Char(
        groups="hr.group_hr_user",
        tracking=True,
    )
    emergency_phone = fields.Char(
        groups="hr.group_hr_user",
        tracking=True,
    )

    distance_home_work = fields.Integer(
        string="Home-Work Distance",
        groups="hr.group_hr_user",
        tracking=True,
    )
    km_home_work = fields.Integer(
        string="Home-Work Distance in Km",
        groups="hr.group_hr_user",
        compute="_compute_km_home_work",
        inverse="_inverse_km_home_work",
        store=True,
        tracking=True,
    )
    distance_home_work_unit = fields.Selection(
        [
            ("kilometers", "km"),
            ("miles", "mi"),
        ],
        "Home-Work Distance unit",
        groups="hr.group_hr_user",
        required=True,
        default="kilometers",
        tracking=True,
    )
    work_location_name = fields.Char(
        "Work Location Name",
        compute="_compute_work_location_name",
    )
    work_location_type = fields.Selection(
        [("home", "Home"), ("office", "Office"), ("other", "Other")],
        compute="_compute_work_location_type",
        tracking=True,
    )

    bank_account_ids = fields.Many2many(
        "res.partner.bank",
        relation="employee_bank_account_rel",
        column1="employee_id",
        column2="bank_account_id",
        domain="[('partner_id', '=', partner_id), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        string="Bank Accounts",
        tracking=True,
        groups="hr.group_hr_user",
        help="Employee bank accounts to pay salaries",
    )
    is_trusted_bank_account = fields.Boolean(
        compute="_compute_is_trusted_bank_account",
        groups="hr.group_hr_user",
    )
    primary_bank_account_id = fields.Many2one(
        "res.partner.bank",
        compute="_compute_primary_bank_account_id",
        groups="hr.group_hr_user",
    )
    has_multiple_bank_accounts = fields.Boolean(
        compute="_compute_has_multiple_bank_accounts",
        groups="hr.group_hr_user",
    )
    salary_distribution = fields.Json(
        string="Salary Distribution",
        compute="_compute_salary_distribution",
        store=True,
        readonly=False,
        groups="hr.group_hr_user",
    )

    visa_no = fields.Char(
        "Visa No",
        groups="hr.group_hr_user",
        tracking=True,
    )
    visa_expire = fields.Date(
        "Visa Expiration Date",
        groups="hr.group_hr_user",
        tracking=True,
    )
    permit_no = fields.Char(
        "Work Permit No",
        groups="hr.group_hr_user",
        tracking=True,
    )
    work_permit_expiration_date = fields.Date(
        "Work Permit Expiration Date",
        groups="hr.group_hr_user",
        tracking=True,
    )
    has_work_permit = fields.Binary(
        string="Work Permit",
        groups="hr.group_hr_user",
    )
    work_permit_name = fields.Char(
        "work_permit_name",
        compute="_compute_work_permit_name",
        groups="hr.group_hr_user",
    )

    certificate = fields.Selection(
        selection="_selection_certificate",
        string="Certificate Level",
        groups="hr.group_hr_user",
        tracking=True,
    )
    study_field = fields.Char(
        "Field of Study",
        groups="hr.group_hr_user",
        tracking=True,
    )
    study_school = fields.Char(
        "School",
        groups="hr.group_hr_user",
        tracking=True,
    )

    driving_license = fields.Binary(
        string="Driving License",
        groups="hr.group_hr_user",
    )
    private_car_plate = fields.Char(
        groups="hr.group_hr_user",
        help="If you have more than one car, just separate the plates by a space.",
    )

    parent_id = fields.Many2one(
        "hr.employee",
        "Manager",
        index=True,
        domain="['|', ('company_id', '=', False), ('company_id', 'in', allowed_company_ids)]",
        tracking=True,
    )
    child_ids = fields.One2many(
        "hr.employee",
        "parent_id",
        string="Direct subordinates",
    )
    coach_id = fields.Many2one(
        "hr.employee",
        "Coach",
        compute="_compute_coach_id",
        store=True,
        readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', 'in', allowed_company_ids)]",
        help='Select the "Employee" who is the coach of this employee.\n'
        'The "Coach" has no specific rights or responsibilities by default.',
    )

    tag_ids = fields.Many2many(
        "res.partner.tag",
        "employee_tag_rel",
        "employee_id",
        "tag_id",
        groups="hr.group_hr_user",
        string="Tags",
    )
    tz = fields.Selection(tracking=True)
    color = fields.Integer("Color Index", default=0)
    barcode = fields.Char(
        string="Badge ID",
        compute="_compute_identifiers",
        inverse="_inverse_identifiers",
        search="_search_barcode",
        compute_sudo=True,
        groups="hr.group_hr_user",
        help="ID used for employee identification.",
    )
    pin = fields.Char(
        string="PIN",
        groups="hr.group_hr_user",
        copy=False,
        help="PIN used to Check In/Out in the Kiosk Mode of the Attendance application (if enabled in Configuration) and to change the cashier in the Point of Sale application.",
    )
    message_main_attachment_id = fields.Many2one(
        groups="hr.group_hr_user",
    )
    id_card = fields.Binary(
        string="ID Card Copy",
        groups="hr.group_hr_user",
    )
    related_partners_count = fields.Integer(
        compute="_compute_related_partners_count",
        groups="hr.group_hr_user",
    )
    employee_properties = fields.Properties(
        "Properties",
        definition="company_id.employee_properties_definition",
        precompute=False,
        groups="hr.group_hr_user",
    )

    activity_ids = fields.One2many(groups="hr.group_hr_user")
    activity_state = fields.Selection(groups="hr.group_hr_user")
    activity_user_id = fields.Many2one(groups="hr.group_hr_user")
    activity_type_id = fields.Many2one(groups="hr.group_hr_user")
    activity_type_icon = fields.Char(groups="hr.group_hr_user")
    activity_date_deadline = fields.Date(groups="hr.group_hr_user")
    my_activity_date_deadline = fields.Date(groups="hr.group_hr_user")
    activity_summary = fields.Char(groups="hr.group_hr_user")
    activity_exception_decoration = fields.Selection(groups="hr.group_hr_user")
    activity_exception_icon = fields.Char(groups="hr.group_hr_user")

    message_is_follower = fields.Boolean(groups="hr.group_hr_user")
    message_follower_ids = fields.One2many(groups="hr.group_hr_user")
    message_partner_ids = fields.Many2many(groups="hr.group_hr_user")
    message_ids = fields.One2many(groups="hr.group_hr_user")
    has_message = fields.Boolean(groups="hr.group_hr_user")
    message_needaction = fields.Boolean(groups="hr.group_hr_user")
    message_needaction_counter = fields.Integer(groups="hr.group_hr_user")
    message_has_error = fields.Boolean(groups="hr.group_hr_user")
    message_has_error_counter = fields.Integer(groups="hr.group_hr_user")
    message_attachment_count = fields.Integer(groups="hr.group_hr_user")

    _BARCODE_DRAW_ATTEMPTS = 32

    _user_uniq = models.Constraint(
        "unique (user_id, company_id)",
        "A user cannot be linked to multiple employees in the same company.",
    )

    @api.constrains("barcode")
    def _check_barcode(self):
        for employee in self:
            if employee.barcode and not (
                re.match(r"^[A-Za-z0-9]+$", employee.barcode)
                and len(employee.barcode) <= 18
            ):
                raise ValidationError(
                    self.env._(
                        "The Badge ID must be alphanumeric without any accents and no longer than 18 characters."
                    )
                )

    @api.constrains("user_id", "partner_id")
    def _check_work_contact_is_the_user_partner(self):
        for employee in self:
            user_partner = employee.user_id.partner_id
            if user_partner and employee.partner_id != user_partner:
                raise ValidationError(
                    self.env._(
                        "%(employee)s is linked to user %(user)s, so their work "
                        "contact must be that user's contact, not %(contact)s.",
                        employee=employee.display_name,
                        user=employee.user_id.display_name,
                        contact=employee.partner_id.display_name,
                    )
                )

    @api.constrains("salary_distribution")
    def _check_salary_distribution(self):
        for employee in self:
            dist = employee.salary_distribution
            if not dist:
                continue

            total = 0
            check_total = False
            for ba_values in dist.values():
                amount = ba_values.get("amount")
                is_percentage = ba_values.get("amount_is_percentage", True)
                if is_percentage and (
                    not isinstance(amount, (float, int)) or not (0 <= amount <= 100)
                ):
                    raise ValidationError(
                        self.env._(
                            "Each amount percentage must be a number between 0 and 100."
                        )
                    )
                if not is_percentage and (
                    isinstance(amount, bool)
                    or not isinstance(amount, (float, int))
                    or amount < 0
                ):
                    raise ValidationError(
                        self.env._(
                            "Each fixed amount must be a number of zero or more."
                        )
                    )
                if is_percentage:
                    check_total = True
                    total += amount

            if check_total and not float_is_zero(total - 100.0, precision_digits=4):
                raise ValidationError(
                    self.env._(
                        "Total salary distribution on bank accounts must be exactly 100%."
                    )
                )

    @api.constrains("pin")
    def _check_pin(self):
        for employee in self:
            if employee.pin and not employee.pin.isdigit():
                raise ValidationError(
                    self.env._("The PIN must be a sequence of digits.")
                )

    @api.model
    def new(self, values=None, origin=None, ref=None):
        if not values:
            values = {}
        new_vals, version_vals = self._split_employee_and_version_vals(values)

        employee = super().new(new_vals, origin, ref)
        version_vals["employee_id"] = employee
        self.env["hr.version"].new(
            {
                f_name: value
                for f_name, value in version_vals.items()
                if self.env["hr.version"]._has_field_access(
                    self.env["hr.version"]._fields[f_name], "read"
                )
            }
        )
        return employee

    @api.model
    def _follow_company_calendar(self, company_id, vals_list):
        # The working-hours default is the current company's calendar, taken
        # before the record's company is known; an employee of another company
        # gets that company's calendar instead, never a calendar it cannot use.
        default_calendar = self.env.company.resource_calendar_id
        if company_id == self.env.company.id or not default_calendar.company_id:
            return
        company = self.env["res.company"].browse(company_id)
        for vals in vals_list:
            if (
                vals.get("resource_calendar_id", default_calendar.id)
                == default_calendar.id
            ):
                vals["resource_calendar_id"] = company.resource_calendar_id.id

    @api.model_create_multi
    def create(self, vals_list):
        vals_per_company = defaultdict(list)
        private_address_vals = {}
        for idx, caller_vals in enumerate(vals_list):
            vals, address_vals = self._split_private_address_vals(caller_vals)
            if address_vals:
                private_address_vals[idx] = address_vals
            if vals.get("user_id"):
                user = self.env["res.users"].browse(vals["user_id"])
                vals.update(self._sync_user(user))
                vals["name"] = vals.get("name", user.name)
                self._remove_work_contact_id(user, vals.get("company_id"))
            vals_per_company[vals.get("company_id") or self.env.company.id].append(
                (idx, vals)
            )
        index_per_employee = {}
        employees = self.env["hr.employee"]
        for company, company_vals_list in vals_per_company.items():
            idxs, company_vals_list = zip(*company_vals_list, strict=True)
            self._follow_company_calendar(company, company_vals_list)
            new_employees = super(HrEmployee, self.with_company(company)).create(
                company_vals_list
            )
            index_per_employee.update(dict(zip(new_employees, idxs, strict=True)))
            employees |= new_employees
        employees = employees.sorted(key=lambda employee: index_per_employee[employee])
        for employee in employees:
            if address_vals := private_address_vals.get(index_per_employee[employee]):
                employee.write(address_vals)
        if self.env.context.get("salary_simulation"):
            return employees
        employees.sudo()._generate_missing_avatars()
        employee_departments = employees.department_id
        if employee_departments:
            self.env["discuss.channel"].sudo().search(
                [("subscription_department_ids", "in", employee_departments.ids)]
            )._subscribe_users_automatically()
        onboarding_notes_bodies = {}
        hr_root_menu = self.env.ref("hr.menu_hr_root")
        for employee in employees:
            url = (
                "/odoo/%s/action-hr.plan_wizard_action?active_model=hr.employee&menu_id=%s"
                % (employee.id, hr_root_menu.id)
            )
            onboarding_notes_bodies[employee.id] = (
                Markup(
                    self.env._(
                        '<b>Congratulations!</b> May I recommend you to setup an <a href="%s">onboarding plan?</a>',
                    )
                )
                % url
            )
        employees._message_log_batch(onboarding_notes_bodies)
        employees.invalidate_recordset()
        return employees

    @api.model
    def _create(self, data_list):
        version_ids = [vals["stored"].pop("version_id", None) for vals in data_list]
        result = super()._create(data_list)
        pairs = [
            (version_id, employee.id)
            for version_id, employee in zip(version_ids, result, strict=True)
            if version_id
        ]
        if not pairs:
            return result
        versions = self.env["hr.version"].browse([pair[0] for pair in pairs])
        versions.flush_recordset()
        self.env.cr.execute(
            SQL(
                "UPDATE hr_version AS v SET employee_id = p.employee_id,"
                " write_date = %s, write_uid = %s"
                " FROM (VALUES %s) AS p(id, employee_id) WHERE v.id = p.id",
                fields.Datetime.now(),
                self.env.uid,
                SQL(", ").join(
                    SQL("(%s, %s)", version_id, employee_id)
                    for version_id, employee_id in pairs
                ),
            )
        )
        versions.invalidate_recordset(["employee_id", "write_date", "write_uid"])
        versions.modified(["employee_id"])
        versions._check_fields(["employee_id"])
        return result

    def write(self, vals):
        vals = dict(vals)
        if vals.get("company_id") and "resource_calendar_id" not in vals:
            # Moving an employee to another company moves the working hours
            # with it: a calendar owned by the old company stays behind.
            company = self.env["res.company"].browse(vals["company_id"])
            moving = self.filtered(
                lambda employee: (
                    employee.resource_calendar_id.company_id
                    and employee.resource_calendar_id.company_id != company
                )
            )
            if moving:
                (self - moving).write(vals)
                moving.write(
                    {**vals, "resource_calendar_id": company.resource_calendar_id.id}
                )
                return True
        if "partner_id" in vals:
            self.message_unsubscribe(self.partner_id.ids)
        user_to_sync = None
        if "user_id" in vals:
            user_to_sync = self.env["res.users"].browse(vals["user_id"])
            vals.update(self._sync_user(user_to_sync))
            self._remove_work_contact_id(user_to_sync, vals.get("company_id"))
        if vals.get("tz"):
            users_to_update = self.env["res.users"]
            for employee in self:
                if (
                    employee.user_id
                    and employee.company_id == employee.user_id.company_id
                    and vals["tz"] != employee.user_id.tz
                ):
                    users_to_update |= employee.user_id
            if users_to_update:
                users_to_update.write({"tz": vals["tz"]})
        if vals.get("department_id") or vals.get("user_id"):
            department_ids = (
                [vals["department_id"]]
                if vals.get("department_id")
                else self.department_id.ids
            )
            if department_ids:
                self.env["discuss.channel"].sudo().search(
                    [("subscription_department_ids", "in", department_ids)]
                )._subscribe_users_automatically()
        if vals.get("departure_description"):
            for employee in self:
                employee.message_post(
                    body=self.env._(
                        "Additional Information: \n %(description)s",
                        description=vals.get("departure_description"),
                    )
                )
        new_vals, version_vals = self._split_employee_and_version_vals(vals)
        res = super().write(new_vals)
        if "partner_id" in vals:
            self._update_bank_account_contact(vals["partner_id"])
            self._reparent_private_address()
        if "name" in vals:
            self.resource_id.write({"name": vals["name"]})
        if version_vals:
            version_vals["last_modified_date"] = fields.Datetime.now()
            version_vals["last_modified_uid"] = self.env.uid
            self.version_id.write(version_vals)

            for employee in self:
                employee._track_set_log_message(
                    Markup("<b>Modified on the Version '%s'</b>")
                    % employee.version_id.display_name
                )
        return res

    @api.model
    def _lang_get(self):
        return self.env["res.lang"].get_installed()

    @api.model
    def _is_version_delegate_field(self, fname):
        field = self._fields.get(fname)
        return bool(
            field and field.inherited and field.related_field.model_name == "hr.version"
        )

    @api.model
    def _is_private_address_field(self, fname):
        field = self._fields.get(fname)
        return bool(
            field and field.related and field.related.startswith("private_address_id.")
        )

    @api.model
    def _split_private_address_vals(self, vals):
        employee_vals, address_vals = {}, {}
        for fname, value in vals.items():
            target = (
                address_vals if self._is_private_address_field(fname) else employee_vals
            )
            target[fname] = value
        return employee_vals, address_vals

    @api.model
    def _split_employee_and_version_vals(self, vals):
        employee_vals, version_vals = {}, {}
        for fname, value in vals.items():
            target = (
                version_vals
                if self._is_version_delegate_field(fname)
                else employee_vals
            )
            target[fname] = value
        return employee_vals, version_vals

    def _prepare_create_values(self, vals_list):
        result = super()._prepare_create_values(vals_list)
        new_vals_list = []
        Version = self.env["hr.version"]
        writable_version_fields = {
            fname
            for fname, field in Version._fields.items()
            if Version._has_field_access(field, "write")
        }
        for vals in result:
            employee_vals, version_vals = self._split_employee_and_version_vals(vals)
            new_vals_list.append(
                {
                    **employee_vals,
                    **{
                        k: v
                        for k, v in version_vals.items()
                        if k in writable_version_fields
                    },
                }
            )
        return new_vals_list

    @api.depends(
        "bank_account_ids.allow_out_payment",
        "salary_distribution",
    )
    def _compute_is_trusted_bank_account(self):
        for employee in self:
            employee.is_trusted_bank_account = (
                employee.primary_bank_account_id.allow_out_payment
            )

    @api.depends("bank_account_ids")
    def _compute_has_multiple_bank_accounts(self):
        for employee in self:
            employee.has_multiple_bank_accounts = len(employee.bank_account_ids) > 1

    @api.depends("bank_account_ids")
    def _compute_salary_distribution(self):
        for employee in self:
            current_salary_distribution = employee.salary_distribution or {}
            current_ids = set(map(int, current_salary_distribution.keys()))
            account_ids = set(employee.bank_account_ids.ids)

            added_ids = account_ids - current_ids
            removed_ids = current_ids - account_ids
            unchanged_ids = account_ids & current_ids

            ordered = sorted(
                [
                    (int(i), data)
                    for i, data in current_salary_distribution.items()
                    if int(i) in unchanged_ids
                ],
                key=lambda x: (
                    not x[1].get("amount_is_percentage"),
                    x[1].get("sequence", float("inf")),
                ),
            )

            new_salary_distribution = {str(i): data for i, data in ordered}

            removed_percentage = sum(
                current_salary_distribution[str(i)]["amount"]
                for i in removed_ids
                if str(i) in current_salary_distribution
                and current_salary_distribution[str(i)]["amount_is_percentage"]
            )
            if removed_percentage and ordered:
                first_id = str(ordered[0][0])
                if new_salary_distribution[first_id]["amount_is_percentage"]:
                    new_salary_distribution[first_id]["amount"] = (
                        employee.currency_id.round(
                            new_salary_distribution[first_id]["amount"]
                            + removed_percentage
                        )
                    )

            total_allocated = sum(
                d["amount"]
                for d in new_salary_distribution.values()
                if d["amount_is_percentage"]
            )
            remaining = max(0.0, 100.0 - total_allocated)
            seq = max(
                (d.get("sequence", 0) for d in new_salary_distribution.values()),
                default=0,
            )
            amount = (
                employee.currency_id.round(remaining / len(added_ids))
                if added_ids
                else 0.0
            )
            for i, new_id in enumerate(sorted(added_ids)):
                seq += 1
                if i == len(added_ids) - 1:
                    amount = employee.currency_id.round(remaining)
                new_salary_distribution[str(new_id)] = {
                    "amount": amount,
                    "amount_is_percentage": True,
                    "sequence": seq,
                }
                remaining -= amount

            employee.salary_distribution = new_salary_distribution

    @api.depends("private_country_id")
    def _compute_allowed_country_state_ids(self):
        states = None
        for employee in self:
            if employee.private_country_id:
                employee.allowed_country_state_ids = (
                    employee.private_country_id.state_ids
                )
            else:
                if states is None:
                    states = self.env["res.country.state"].search([])
                employee.allowed_country_state_ids = states

    @api.depends("distance_home_work", "distance_home_work_unit")
    def _compute_km_home_work(self):
        for employee in self:
            employee.km_home_work = (
                employee.distance_home_work * 1.609
                if employee.distance_home_work_unit == "miles"
                else employee.distance_home_work
            )

    @api.depends(lambda self: [self._get_new_hire_field_name()])
    def _compute_newly_hired(self):
        new_hire_field = self._get_new_hire_field_name()
        new_hire_date = fields.Datetime.now() - timedelta(days=90)
        for employee in self:
            if not employee[new_hire_field]:
                employee.newly_hired = False
            elif not isinstance(employee[new_hire_field], datetime):
                employee.newly_hired = employee[new_hire_field] > new_hire_date.date()
            else:
                employee.newly_hired = employee[new_hire_field] > new_hire_date

    @api.depends("resource_calendar_id", "hr_presence_state")
    def _compute_presence_icon(self):
        for employee in self:
            employee.hr_icon_display = "presence_" + employee.hr_presence_state
            employee.show_hr_icon_display = bool(employee.user_id)

    @api.depends("name")
    def _compute_legal_name(self):
        for employee in self:
            if not employee.legal_name:
                employee.legal_name = employee.name

    @api.depends("current_version_id")
    @api.depends_context("version_id")
    def _compute_version_id(self):
        context_version_id = self.env.context.get("version_id", False)
        context_version = (
            self.env["hr.version"].browse(context_version_id).exists()
            if context_version_id
            else self.env["hr.version"]
        )

        for employee in self:
            if context_version and context_version.employee_id == employee:
                version = context_version
            else:
                version = employee.current_version_id
            employee.version_id = version

    @api.depends("version_id.work_location_id.name")
    def _compute_work_location_name(self):
        for employee in self:
            employee.work_location_name = (
                employee.version_id.work_location_id.name or None
            )

    @api.depends("version_id.work_location_id.location_type")
    def _compute_work_location_type(self):
        for employee in self:
            employee.work_location_type = (
                employee.version_id.work_location_id.location_type or "other"
            )

    @api.depends("version_ids.date_version", "version_ids.active", "active")
    def _compute_current_version_id(self):
        Version = self.env["hr.version"].with_context(active_test=True)
        today = fields.Date.today()
        latest_version_by_employee = {}
        for version in Version.search(
            [("employee_id", "in", self.ids), ("date_version", "<=", today)],
            order="date_version asc",
        ):
            latest_version_by_employee[version.employee_id.id] = version
        employees_without_past_version = [
            employee.id
            for employee in self
            if employee.id not in latest_version_by_employee
        ]
        earliest_version_by_employee = {}
        if employees_without_past_version:
            for version in Version.search(
                [("employee_id", "in", employees_without_past_version)],
                order="date_version asc",
            ):
                earliest_version_by_employee.setdefault(version.employee_id.id, version)
        no_version = self.env["hr.version"]
        for employee in self:
            new_current_version = latest_version_by_employee.get(
                employee.id
            ) or earliest_version_by_employee.get(employee.id, no_version)
            if not new_current_version and not employee.id:
                new_current_version = employee.version_ids[:1]
            if employee.current_version_id != new_current_version:
                employee.current_version_id = new_current_version

    @api.depends("partner_id")
    def _compute_private_address_id(self):
        Partner = self.env["res.partner"].sudo()
        unresolved = self.filtered(lambda e: not e.private_address_id)
        existing_by_contact = {}
        for home in Partner.search(
            [
                ("parent_id", "in", unresolved.partner_id.ids),
                ("type", "=", "private"),
            ],
            order="id",
        ):
            existing_by_contact.setdefault(home.parent_id, home)
        to_create = []
        for employee in unresolved:
            contact = employee.partner_id
            if not contact:
                employee.private_address_id = False
            elif contact in existing_by_contact:
                employee.private_address_id = existing_by_contact[contact]
            elif not employee.id:
                employee.private_address_id = employee._origin.private_address_id
            else:
                to_create.append(employee)
        if to_create:
            homes = Partner.create(
                [
                    {"parent_id": employee.partner_id.id, "type": "private"}
                    for employee in to_create
                ]
            )
            for employee, home in zip(to_create, homes, strict=True):
                employee.private_address_id = home

    @api.depends("parent_id")
    def _compute_coach_id(self):
        for version in self:
            manager = version.parent_id
            previous_manager = version._origin.parent_id
            if manager and (
                version.coach_id == previous_manager or not version.coach_id
            ):
                version.coach_id = manager
            elif not version.coach_id:
                version.coach_id = False

    @api.depends("partner_id", "partner_id.phone", "partner_id.email")
    def _compute_work_contact_details(self):
        for employee in self:
            if employee.partner_id:
                if len(employee.partner_id.employee_ids) <= 1:
                    employee.work_phone = employee.partner_id.phone
                    employee.work_email = employee.partner_id.email

    def _has_field_access(self, field, operation):
        if not super()._has_field_access(field, operation):
            return False
        if self.env.su or self.env.user.has_group("hr.group_hr_user"):
            return True
        if field.name in self._DIRTY_HACK_PRIVATE_FIELDS:
            return False
        return not self._is_party_field(field.name) or self._is_public_party_field(
            field.name
        )

    def check_no_existing_contract(self, date):
        if isinstance(date, str):
            date = fields.Date.from_string(date)
        if self._is_in_contract(date):
            raise ValidationError(
                self.env._(
                    "The employee is already in contract on %s. "
                    "Please select a date outside existing contracts",
                    format_date_abbr(self.env, date),
                )
            )

    @api.onchange("contract_template_id")
    def _onchange_contract_template_id(self):
        if self.contract_template_id:
            whitelist = self.env["hr.version"]._get_whitelist_fields_from_template()
            for field in self.contract_template_id._fields:
                if (
                    field in whitelist
                    and not self.env["hr.version"]._fields[field].related
                ):
                    self[field] = self.contract_template_id[field]

    @api.onchange("contract_date_start")
    def _onchange_contract_date_start(self):
        if not self.contract_date_start:
            self.contract_date_end = False

    def _inverse_km_home_work(self):
        for employee in self:
            employee.distance_home_work = (
                employee.km_home_work / 1.609
                if employee.distance_home_work_unit == "miles"
                else employee.km_home_work
            )

    @api.model
    def _selection_marital_status(self):
        return [
            ("single", self.env._("Single")),
            ("married", self.env._("Married")),
            ("cohabitant", self.env._("Legal Cohabitant")),
            ("widower", self.env._("Widower")),
            ("divorced", self.env._("Divorced")),
        ]

    @api.constrains("ssnid")
    def _check_ssnid(self):
        pass

    @api.onchange("private_state_id")
    def _onchange_private_state_id(self):
        if self.private_state_id:
            self.private_country_id = self.private_state_id.country_id

    @api.onchange("work_phone", "mobile_phone", "company_country_id", "company_id")
    def _onchange_phone_validation_employee(self):
        if self.work_phone:
            self.work_phone = (
                self._phone_format(number=self.work_phone, force_format="INTERNATIONAL")
                or self.work_phone
            )
        if self.mobile_phone:
            self.mobile_phone = (
                self._phone_format(
                    number=self.mobile_phone, force_format="INTERNATIONAL"
                )
                or self.mobile_phone
            )

    def _get_display_name_visible_ids(self) -> set[int]:
        if not self.env.user._is_internal():
            return super()._get_display_name_visible_ids()
        return set(self._ids)

    @api.model
    def _get_new_hire_field_name(self):
        return "create_date"

    @api.model
    def _selection_certificate(self):
        return [
            ("graduate", self.env._("Graduate")),
            ("bachelor", self.env._("Bachelor")),
            ("master", self.env._("Master")),
            ("doctor", self.env._("Doctor")),
            ("other", self.env._("Other")),
        ]

    def _get_first_versions(self):
        self.check_singleton()
        versions = self.version_ids
        if self.env.context.get("before_date"):
            versions = versions.filtered(
                lambda c: c.date_start <= self.env.context["before_date"]
            )
        return versions

    def _get_first_version_date(self, no_gap=True):
        self.check_singleton()
        if not self.env.su and not self.env.user.has_group("hr.group_hr_user"):
            raise AccessError(
                self.env._(
                    "Only HR users can access first version date on an employee."
                )
            )

        def get_versions_continuous(versions):
            if not versions:
                return self.env["hr.version"]
            if len(versions) == 1:
                return versions
            current_version = versions[0]
            older_versions = versions[1:]
            current_date = current_version.date_start
            for i, other_version in enumerate(older_versions):
                gap = (current_date - (other_version.date_end or date(2100, 1, 1))).days
                current_date = other_version.date_start
                if gap >= 4:
                    return older_versions[0:i] + current_version
            return older_versions + current_version

        versions = self._get_first_versions().sorted("date_start", reverse=True)
        if no_gap:
            versions = get_versions_continuous(versions)
        return min(versions.mapped("date_start")) if versions else False

    def _cron_update_current_version_id(self):
        self.with_context(active_test=False).search([])._compute_current_version_id()

    def _search_version_id(self, operator, value):
        if operator in ("any", "any!"):
            return Domain("current_version_id", operator, value)
        domain = Domain("id", operator, value)
        return Domain(
            "id", "in", self.env["hr.version"]._search(domain).select("employee_id")
        )

    def _field_to_sql(
        self, alias: str, field_expr: str, query: (Query | None) = None
    ) -> SQL:
        if field_expr == "version_id":
            field_expr = "current_version_id"
        return super()._field_to_sql(alias, field_expr, query)

    def _get_version(self, date=None):
        date = date or fields.Date.today()
        self.check_singleton()
        versions = self.version_ids.filtered_domain([("date_version", "<=", date)])
        return (
            max(versions, key=lambda v: v.date_version)
            if versions
            else self.version_ids[0]
        )

    @staticmethod
    def _coerce_date(value):
        if isinstance(value, str):
            return fields.Date.to_date(value)
        if isinstance(value, datetime):
            return value.date()
        return value

    def _get_new_version_dates(self, values):
        date = self._coerce_date(values.get("date_version", False))
        if not date:
            raise ValueError("date_version is required")

        date_from, date_to = self.sudo()._get_contract_dates(date)
        contract_date_start = self._coerce_date(
            values.get("contract_date_start", date_from)
        )
        contract_date_end = self._coerce_date(values.get("contract_date_end", date_to))

        if contract_date_end and not contract_date_start:
            raise UserError(
                self.env._("A contract end date requires a contract start date.")
            )
        return date, contract_date_start, contract_date_end, date_from, date_to

    def _update_sibling_contract_end(
        self, employee_id, date_from, date_to, contract_date_start, contract_date_end
    ):
        if not (
            date_from
            and contract_date_start == date_from
            and contract_date_end != date_to
        ):
            return
        versions_sudo_to_sync = (
            self.env["hr.version"]
            .with_context(sync_contract_dates=True)
            .sudo()
            .search(
                [
                    ("employee_id", "=", employee_id),
                    ("contract_date_start", "=", date_from),
                ]
            )
        )
        if versions_sudo_to_sync:
            versions_sudo_to_sync.write({"contract_date_end": contract_date_end})

    def create_version(self, values):
        self.check_singleton()
        date, contract_date_start, contract_date_end, date_from, date_to = (
            self._get_new_version_dates(values)
        )

        version_to_copy = self._get_version(date)
        if not version_to_copy:
            version_to_copy = self.env["hr.version"].search(
                [("employee_id", "=", self.id)], limit=1
            )
        if version_to_copy.date_version == date:
            return version_to_copy

        employee_id = values.get("employee_id", self.id)
        self._update_sibling_contract_end(
            employee_id, date_from, date_to, contract_date_start, contract_date_end
        )
        self.check_access("write")
        version_to_copy.check_access("write")
        copy_vals = {
            "date_version": date,
            "employee_id": employee_id,
            "contract_date_start": contract_date_start,
            "contract_date_end": contract_date_end,
        }
        if "active" in values:
            copy_vals["active"] = values["active"]
        if calendar_id := values.get("resource_calendar_id"):
            copy_vals["resource_calendar_id"] = calendar_id
        new_version_vals = {
            field_name: field_value
            for field_name, field_value in values.items()
            if field_name not in copy_vals
        }
        version_fields = self.env["hr.version"]._fields
        copy_vals = {
            k: v
            for k, v in version_to_copy.sudo().copy_data()[0].items()
            if not (
                k in new_version_vals
                and version_fields[k].type in ["one2many", "many2many"]
            )
        } | copy_vals
        new_version = self.env["hr.version"].sudo().create(copy_vals).sudo(False)
        with self.env.protecting(
            [
                f
                for f_name, f in version_fields.items()
                if f_name not in new_version_vals and f.copy
            ],
            new_version,
        ):
            properties_fields_vals = {
                field_name: field_value
                for field_name, field_value in copy_vals.items()
                if version_fields[field_name].type == "properties"
                and field_name not in new_version_vals
            }
            if properties_fields_vals:
                new_version.sudo().write(properties_fields_vals)
            new_version.write(new_version_vals)
        return new_version

    def create_contract(self, date):
        self.check_singleton()
        if date and isinstance(date, str):
            date = fields.Date.to_date(date)

        contracts = self._get_contract_versions(date)[self.id]
        future_contract_dates = [d for d in list(contracts.keys()) if d > date]
        new_contract_date_end = (
            min(future_contract_dates) + relativedelta(days=-1)
            if future_contract_dates
            else False
        )

        if version_same_date := self.version_ids.filtered(
            lambda v: v.date_version == date
        ):
            version_same_date.write(
                {
                    "contract_date_start": date,
                    "contract_date_end": new_contract_date_end,
                }
            )
            return version_same_date

        return self.create_version(
            {
                "date_version": date,
                "contract_date_start": date,
                "contract_date_end": new_contract_date_end,
            }
        )

    def _is_in_contract(self, date):
        return self._get_contract_dates(date) != (False, False)

    def _get_contracts(self, date_start=None, date_end=None, domain=None):
        contract_versions_by_employee = self._get_contract_versions(
            date_start, date_end, domain
        )
        contracts_by_employee = defaultdict(lambda: self.env["hr.version"])
        for employee_id, versions_by_contract in contract_versions_by_employee.items():
            for contract_versions in versions_by_contract.values():
                if not date_end:
                    contracts_by_employee[employee_id] |= contract_versions[-1]
                    continue
                effective_versions = contract_versions.filtered(
                    lambda v, date_end=date_end: v.date_version <= date_end
                )
                contracts_by_employee[employee_id] |= (
                    effective_versions[-1]
                    if effective_versions
                    else contract_versions[0]
                )
        return contracts_by_employee

    def _get_contract_versions(self, date_start=None, date_end=None, domain=None):
        version_domain = Domain("contract_date_start", "!=", False)
        if self.ids:
            version_domain &= Domain("employee_id", "in", self.ids)
        elif not any(self._ids):
            version_domain &= Domain("employee_id", "in", self._origin.ids)
        if date_start:
            version_domain &= Domain("contract_date_end", "=", False) | Domain(
                "contract_date_end", ">=", date_start
            )
        if date_end:
            version_domain &= Domain("contract_date_start", "<=", date_end)
        if domain:
            version_domain &= domain
        all_versions = self.env["hr.version"]._read_group(
            domain=version_domain,
            groupby=["employee_id", "date_version:day"],
            aggregates=["id:recordset"],
        )
        contract_versions_by_employee = defaultdict(
            lambda: defaultdict(lambda: self.env["hr.version"])
        )
        for employee, _date_version, version in all_versions:
            first_version = next(iter(version), version)
            contract_versions_by_employee[employee.id][
                first_version.contract_date_start
            ] |= version
        return contract_versions_by_employee

    def _get_all_contract_dates(self):
        self.check_singleton()
        return self.env["hr.version"]._read_group(
            [("employee_id", "=", self.id), ("contract_date_start", "!=", False)],
            ["contract_date_start:day", "contract_date_end:day"],
        )

    def _get_contract_dates(self, date):
        self.check_singleton()
        is_day_in_period = self.env["hr.version"]._is_day_in_period
        for date_from, date_to in self._get_all_contract_dates():
            if is_day_in_period(date_from, date_to, date):
                return date_from, date_to
        return False, False

    @api.depends("version_ids")
    def _compute_versions_count(self):
        version_count_per_employee = dict(
            self.env["hr.version"]._read_group(
                [("employee_id", "in", self.ids)],
                ["employee_id"],
                ["id:count"],
            ),
        )
        for employee in self:
            employee.versions_count = version_count_per_employee.get(employee, 0)

    def _search_newly_hired(self, operator, value):
        if operator not in ("in", "not in"):
            return NotImplemented
        new_hire_field = self._get_new_hire_field_name()
        threshold = fields.Datetime.now() - timedelta(days=90)
        if operator == "in":
            return Domain(new_hire_field, ">", threshold)
        return Domain(new_hire_field, "<=", threshold) | Domain(
            new_hire_field, "=", False
        )

    @api.model
    def _get_valid_employee_for_user(self):
        user = self.env.user
        employee = user.employee_id
        if not employee:
            user_employees = self.sudo().search([("user_id", "=", user.id)])
            employee = (
                user_employees.filtered(lambda r: r.company_id == user.company_id)
                or user_employees[:1]
            )
        return employee

    @api.model
    def _search_member_of_department_domain(self, operator):
        if operator != "in":
            return NotImplemented
        department = self._get_valid_employee_for_user().department_id
        if not department:
            return Domain.FALSE
        return Domain("department_id", "child_of", department.ids)

    def _inverse_work_contact_details(self):
        for employee in self:
            if len(employee.partner_id.employee_ids) <= 1:
                employee.partner_id.sudo().write(
                    {
                        "email": employee.work_email,
                        "phone": employee.work_phone,
                    }
                )

    @api.model
    def _get_employee_ids_working_now(self):
        start_dt = fields.Datetime.now().replace(tzinfo=UTC)
        stop_dt = start_dt + timedelta(hours=1)
        employees_by_schedule = defaultdict(lambda: self.env["hr.employee"])
        for employee in self.sudo():
            employees_by_schedule[
                (employee.tz or "UTC", employee.resource_calendar_id)
            ] += employee
        working_now = []
        for (tz, calendar), employees in employees_by_schedule.items():
            if not calendar:
                continue
            zone = timezone(tz)
            work_intervals = calendar._work_intervals_batch(
                start_dt.astimezone(zone), stop_dt.astimezone(zone)
            )[False]
            if work_intervals:
                working_now += employees.ids
        return working_now

    @api.depends("user_id.im_status", "active")
    def _compute_hr_presence_state(self):
        employee_to_check_working = self.filtered(
            lambda e: (
                e.company_id.sudo().hr_presence_control_login
                and (e.user_id.sudo().presence_ids.status or "offline") == "offline"
            )
        )
        working_now_list = employee_to_check_working._get_employee_ids_working_now()
        for employee in self:
            state = "out_of_working_hour"
            if employee.company_id.sudo().hr_presence_control_login:
                presence_status = (
                    employee.user_id.sudo().presence_ids.status or "offline"
                )
                if presence_status == "online":
                    state = "present"
                elif presence_status == "offline" and employee.id in working_now_list:
                    state = "absent"
            if not employee.active:
                state = "archive"
            employee.hr_presence_state = state

    @api.depends("user_id")
    def _compute_last_activity_and_time(self):
        for employee in self:
            tz = employee.tz
            if last_presence := employee.user_id.sudo().presence_ids.last_presence:
                last_activity_datetime = (
                    last_presence.replace(tzinfo=UTC)
                    .astimezone(timezone(tz or "UTC"))
                    .replace(tzinfo=None)
                )
                employee.last_activity = last_activity_datetime.date()
                if employee.last_activity == fields.Date.today():
                    employee.last_activity_time = format_time(
                        self.env, last_presence, time_format="short"
                    )
                else:
                    employee.last_activity_time = False
            else:
                employee.last_activity = False
                employee.last_activity_time = False

    @api.depends("birthday", "birthday_public_display")
    def _compute_birthday_public_display_string(self):
        for employee in self:
            if employee.birthday and employee.birthday_public_display:
                employee.birthday_public_display_string = datetime.strftime(
                    employee.birthday, "%d %B"
                )
            else:
                employee.birthday_public_display_string = "hidden"

    @api.depends("name", "permit_no")
    def _compute_work_permit_name(self):
        for employee in self:
            name = employee.name.replace(" ", "_") + "_" if employee.name else ""
            permit_no = "_" + employee.permit_no if employee.permit_no else ""
            employee.work_permit_name = "%swork_permit%s" % (name, permit_no)

    def _get_partner_count_depends(self):
        return ["user_id", "partner_id"]

    @api.depends(lambda self: self._get_partner_count_depends())
    def _compute_related_partners_count(self):
        for employee in self:
            employee.related_partners_count = len(employee._get_related_partners())

    def _get_related_partners(self):
        return self.partner_id | self.user_id.partner_id

    def action_view_related_contacts(self):
        related_partners = self._get_related_partners()
        action = {
            "name": self.env._("Related Contacts"),
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "view_mode": "form",
        }
        if len(related_partners) > 1:
            action["view_mode"] = "kanban,list,form"
            action["domain"] = [("id", "in", related_partners.ids)]
            return action
        if not related_partners:
            raise UserError(self.env._("%s has no related contact.", self.display_name))
        action["res_id"] = related_partners.id
        return action

    def action_create_user(self):
        self.check_singleton()
        if self.user_id:
            raise ValidationError(self.env._("This employee already has an user."))
        return {
            "name": self.env._("Create User"),
            "type": "ir.actions.act_window",
            "res_model": "res.users",
            "view_mode": "form",
            "view_id": self.env.ref("hr.view_users_simple_form").id,
            "target": "new",
            "context": {
                **self.env.context,
                "default_create_employee_id": self.id,
                "default_name": self.name,
                "default_phone": self.work_phone,
                "default_mobile": self.mobile_phone,
                "default_login": self.work_email,
                "default_partner_id": self.partner_id.id,
            },
        }

    def action_create_users_confirmation(self):
        raise RedirectWarning(
            message=self.env._(
                "You're about to invite new users. %s users will be created with the default user template's rights. "
                "Adding new users may increase your subscription cost. Do you wish to continue?",
                len(self.ids),
            ),
            action=self.env.ref("hr.action_hr_employee_create_users").id,
            button_text=self.env._("Confirm"),
            additional_context={
                "selected_ids": self.ids,
            },
        )

    def _prepare_action_user_creation_notification(
        self, message, message_type, next_action
    ):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("User Creation Notification"),
                "type": message_type,
                "message": message,
                "next": next_action,
            },
        }

    def _prepare_user_vals_and_blocked_names(self):
        employee_emails = [
            normalized_email
            for employee in self
            for normalized_email in tools.mail.email_normalize_all(employee.work_email)
        ]
        conflicting_users = self.env["res.users"]
        if employee_emails:
            conflicting_users = self.env["res.users"].search(
                [
                    "|",
                    ("email_normalized", "in", employee_emails),
                    ("login", "in", employee_emails),
                ]
            )
        taken_addresses = set(conflicting_users.mapped("email_normalized")) | set(
            conflicting_users.mapped("login")
        )
        create_vals = []
        blocked = defaultdict(list)
        for employee in self:
            if employee.user_id:
                blocked["has_user"].append(employee.name)
                continue
            if not employee.work_email:
                blocked["no_email"].append(employee.name)
                continue
            login = email_normalize(employee.work_email)
            if not login:
                blocked["invalid_email"].append(employee.name)
                continue
            if login in taken_addresses:
                blocked["address_taken"].append(employee.name)
                continue
            create_vals.append(
                {
                    "create_employee_id": employee.id,
                    "name": employee.name,
                    "phone": employee.work_phone,
                    "login": login,
                    "partner_id": employee.partner_id.id,
                }
            )
        return create_vals, blocked

    def action_create_users(self):
        create_vals, blocked = self._prepare_user_vals_and_blocked_names()

        next_action = {"type": "ir.actions.act_window_close"}
        if create_vals:
            self.env["res.users"].create(create_vals)
            next_action = self._prepare_action_user_creation_notification(
                self.env._(
                    "Users %s creation successful",
                    ", ".join(vals["name"] for vals in create_vals),
                ),
                "success",
                {
                    "type": "ir.actions.client",
                    "tag": "soft_reload",
                    "params": {"next": next_action},
                },
            )

        for names, message_type, message in (
            (
                blocked["has_user"],
                "warning",
                self.env._(
                    "User already exists for Those Employees %s",
                    ", ".join(blocked["has_user"]),
                ),
            ),
            (
                blocked["no_email"],
                "danger",
                self.env._(
                    "You need to set the work email address for %s",
                    ", ".join(blocked["no_email"]),
                ),
            ),
            (
                blocked["invalid_email"],
                "danger",
                self.env._(
                    "You need to set a valid work email address for %s",
                    ", ".join(blocked["invalid_email"]),
                ),
            ),
            (
                blocked["address_taken"],
                "warning",
                self.env._(
                    "User already exists with the same email for Employees %s",
                    ", ".join(blocked["address_taken"]),
                ),
            ),
        ):
            if names:
                next_action = self._prepare_action_user_creation_notification(
                    message, message_type, next_action
                )
        return next_action

    def _compute_display_name(self):
        if self.browse().has_access("read"):
            return super()._compute_display_name()
        for employee_private, employee_public in zip(
            self, self.env["hr.employee.public"].browse(self.ids), strict=True
        ):
            employee_private.display_name = employee_public.display_name
        return None

    @contextmanager
    def _mask_domain_errors_as_access_errors(self):
        try:
            yield
        except (ValueError, RuntimeError) as error:
            raise AccessError(
                self.env._("You do not have access to this document.")
            ) from error

    @api.model
    def search_fetch(self, domain, field_names=None, offset=0, limit=None, order=None):
        if self.browse().has_access("read"):
            return super().search_fetch(domain, field_names, offset, limit, order)

        if field_names is None:
            field_names = [field.name for field in self._determine_fields_to_fetch()]
        field_names = [
            f_name for f_name in field_names if f_name != "current_version_id"
        ]
        self._check_no_private_fields(field_names)
        public_names, party_names = self._split_public_and_party_fields(field_names)
        self.flush_model(field_names)
        with self._mask_domain_errors_as_access_errors():
            public = self.env["hr.employee.public"].search_fetch(
                domain, public_names, offset, limit, order
            )
        employees = self.browse(public._ids)
        employees._copy_cache_from_public(public, public_names)
        for fname in party_names:
            employees.mapped(fname)
        return employees

    def fetch(self, field_names=None):
        if self.browse().has_access("read"):
            return super().fetch(field_names)

        if field_names is None:
            field_names = [field.name for field in self._determine_fields_to_fetch()]
        field_names = [
            f_name for f_name in field_names if f_name != "current_version_id"
        ]
        self._check_no_private_fields(field_names)
        public_names, party_names = self._split_public_and_party_fields(field_names)
        self.flush_recordset(field_names)
        public = self.env["hr.employee.public"].browse(self._ids)
        public.fetch(public_names)
        for field_name in public_names:
            public_field = self.env["hr.employee.public"]._fields[field_name]
            private_field = self.env["hr.employee"]._fields[field_name]
            if (
                public_field.related
                and public_field.related_field.model_name == "hr.employee"
            ) or (
                private_field.inherited
                and private_field.inherited_field.model_name == "hr.version"
            ):
                public.mapped(field_name)
        self._copy_cache_from_public(public, public_names)
        for fname in party_names:
            self.mapped(fname)
        return None

    def _check_access(self, operation):
        if (
            operation == "read"
            and self.env.context.get("_allow_read_hr_employee")
            is _ALLOW_READ_HR_EMPLOYEE
        ):
            return None

        return super()._check_access(operation)

    def _is_party_field(self, fname):
        field = self._fields[fname]
        return bool(
            field.inherited and field.inherited_field.model_name == "res.partner"
        )

    def _is_public_party_field(self, fname):
        """A party field a public-profile reader may read through the employee:
        one the partner stores as a column, which the reader could read on the
        partner itself. Computed and x2many party fields reach into other
        models and stay behind the profile."""
        field = self._fields[fname]
        return (
            self._is_party_field(fname)
            and field.inherited_field.store
            and field.inherited_field.type not in ("one2many", "many2many")
        )

    def _split_public_and_party_fields(self, field_names):
        public_fields = self.env["hr.employee.public"]._fields
        party_names = [
            fname
            for fname in field_names
            if fname not in public_fields and self._is_public_party_field(fname)
        ]
        public_names = [fname for fname in field_names if fname not in party_names]
        if party_names and "partner_id" not in public_names:
            public_names.append("partner_id")
        return public_names, party_names

    def _check_no_private_fields(self, field_names):
        public_fields = self.env["hr.employee.public"]._fields
        private_fields = [
            fname
            for fname in field_names
            if fname not in public_fields and not self._is_public_party_field(fname)
        ]
        if private_fields:
            raise AccessError(
                self.env._(
                    "The fields “%s”, which you are trying to read, are not available for employee public profiles.",
                    ",".join(private_fields),
                )
            )

    def _copy_cache_from_public(self, public, field_names):
        for fname in field_names:
            values = self.env.cache.get_values(public, public._fields[fname])
            if self._fields[fname].translate:
                values = [(value.copy() if value else None) for value in values]
            self.env.cache.update_raw(self, self._fields[fname], values)

    @api.model
    def notify_expiring_contract_work_permit(self):
        companies = self.env["res.company"].search([])
        employees_contract_expiring = self.env["hr.employee"]
        employees_work_permit_expiring = self.env["hr.employee"]

        today = fields.Date.today()
        companies_by_contract_period = defaultdict(lambda: self.env["res.company"])
        companies_by_permit_period = defaultdict(lambda: self.env["res.company"])
        for company in companies:
            companies_by_contract_period[company.contract_expiration_notice_period] += (
                company
            )
            companies_by_permit_period[
                company.work_permit_expiration_notice_period
            ] += company

        for notice_period, period_companies in companies_by_contract_period.items():
            employees_contract_expiring += self.env["hr.employee"].search(
                [
                    ("company_id", "in", period_companies.ids),
                    ("contract_date_start", "!=", False),
                    ("contract_date_start", "<=", today),
                    ("contract_date_end", ">=", today),
                    (
                        "contract_date_end",
                        "<=",
                        today + relativedelta(days=notice_period),
                    ),
                ]
            )
        for notice_period, period_companies in companies_by_permit_period.items():
            employees_work_permit_expiring += self.env["hr.employee"].search(
                [
                    ("company_id", "in", period_companies.ids),
                    ("work_permit_expiration_date", ">=", today),
                    (
                        "work_permit_expiration_date",
                        "<=",
                        today + relativedelta(days=notice_period),
                    ),
                ]
            )

        for employee in employees_contract_expiring:
            employee._schedule_expiry_activity(
                employee.contract_date_end,
                self.env._("The contract of %s is about to expire.", employee.name),
            )

        for employee in employees_work_permit_expiring:
            employee._schedule_expiry_activity(
                employee.work_permit_expiration_date,
                self.env._("The work permit of %s is about to expire.", employee.name),
            )

        return True

    def _schedule_expiry_activity(self, date_deadline, summary):
        self.check_singleton()
        already_scheduled = (
            self.env["mail.activity"]
            .sudo()
            .search_count(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "=", self.id),
                    ("date_deadline", "=", date_deadline),
                    ("summary", "=", summary),
                ],
                limit=1,
            )
        )
        if already_scheduled:
            return
        self.with_context(mail_activity_quick_update=True).activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline,
            summary,
            user_id=self.hr_responsible_id.id or self.env.uid,
        )

    @api.model
    def get_view(self, view_id=None, view_type="form", **options):
        if self.browse().has_access("read"):
            return super().get_view(view_id, view_type, **options)
        return self.env["hr.employee.public"].get_view(view_id, view_type, **options)

    @api.model
    def get_views(self, views, options=None):
        if self.browse().has_access("read"):
            return super().get_views(views, options)
        raise RedirectWarning(
            message=self.env._(
                'You are not allowed to access "Employee" (hr.employee) records.\n'
                "We can redirect you to the public employee list."
            ),
            action=self.env.ref("hr.hr_employee_public_action").id,
            button_text=self.env._("Employees profile"),
        )

    @api.model
    def _search(
        self, domain, offset=0, limit=None, order=None, *, bypass_access=False, **kwargs
    ):
        if self.browse().has_access("read") or bypass_access:
            return super()._search(
                domain, offset, limit, order, bypass_access=bypass_access, **kwargs
            )
        domain = Domain(domain)
        domain = domain.map_conditions(
            lambda cond: (
                Domain("id", cond.operator, cond.value)
                if cond.field_expr == "current_version_id"
                else cond
            )
        )
        with self._mask_domain_errors_as_access_errors():
            ids = self.env["hr.employee.public"]._search(
                domain, offset, limit, order, **kwargs
            )
        return super(HrEmployee, self.sudo())._search([("id", "in", ids)], order=order)

    def _load_demo_data(self):
        self.sudo()._load_scenario()
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def get_formview_id(self, access_uid=None):
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid).sudo()

        if user.has_group("hr.group_hr_user"):
            return super().get_formview_id(access_uid=access_uid)
        return self.env.ref("hr.hr_employee_public_view_form").id

    def get_formview_action(self, access_uid=None):
        res = super().get_formview_action(access_uid=access_uid)
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid).sudo()

        if not user.has_group("hr.group_hr_user"):
            res["res_model"] = "hr.employee.public"

        return res

    @api.onchange("user_id")
    def _onchange_user(self):
        self.update(self._sync_user(self.user_id))
        if not self.name:
            self.name = self.user_id.name

    @api.onchange("resource_calendar_id")
    def _onchange_timezone(self):
        if self.resource_calendar_id and not self.tz:
            self.tz = self.resource_calendar_id.tz

    def unlink(self):
        resources = self.mapped("resource_id")
        result = super().unlink()
        resources.unlink()
        return result

    @api.onchange("company_id")
    def _onchange_company_id(self):
        if self._origin:
            return {
                "warning": {
                    "title": self.env._("Warning"),
                    "message": self.env._(
                        "To avoid multi company issues (losing the access to your previous contracts, leaves, ...), you should create another employee in the new company instead."
                    ),
                }
            }
        return None

    def _load_scenario(self):
        demo_tag = self.env.ref("hr.employee_category_demo", raise_if_not_found=False)
        if demo_tag:
            return
        convert.convert_file(
            self.env, "hr", "data/scenarios/hr_scenario.xml", None, mode="init"
        )

    @api.depends("bank_account_ids", "salary_distribution")
    def _compute_primary_bank_account_id(self):
        for employee in self:
            if employee.bank_account_ids:
                distribution = employee.salary_distribution or {}
                primary_account = min(
                    employee.bank_account_ids,
                    key=lambda acc: distribution.get(str(acc.id), {}).get(
                        "sequence", float("inf")
                    ),
                )
                employee.primary_bank_account_id = primary_account
            else:
                employee.primary_bank_account_id = False

    def action_unarchive(self):
        res = super().action_unarchive()
        self.write(
            {
                "departure_reason_id": False,
                "departure_description": False,
                "departure_date": False,
            }
        )
        return res

    def action_archive(self):
        archived_employees = self.filtered("active")
        res = super().action_archive()
        if archived_employees:
            employee_fields_to_empty = (
                self._get_employee_field_names_to_empty_on_archive()
            )
            user_fields_to_empty = self._get_user_field_names_to_empty_on_archive()
            employee_domain = Domain.OR(
                Domain(field, "in", archived_employees.ids)
                for field in employee_fields_to_empty
            )
            user_domain = Domain.OR(
                Domain(field, "in", archived_employees.user_id.ids)
                for field in user_fields_to_empty
            )
            employees = self.env["hr.employee"].search(employee_domain | user_domain)
            for field in employee_fields_to_empty:
                employees.filtered(lambda e, f=field: e[f] in archived_employees).write(
                    {field: False}
                )
            for field in user_fields_to_empty:
                employees.filtered(
                    lambda e, f=field: e[f] in archived_employees.user_id
                ).write({field: False})

            if len(archived_employees) == 1 and not self.env.context.get(
                "no_wizard", False
            ):
                return {
                    "type": "ir.actions.act_window",
                    "name": self.env._("Register Departure"),
                    "res_model": "hr.departure.wizard",
                    "view_mode": "form",
                    "target": "new",
                    "context": {"active_id": archived_employees.id},
                    "views": [[False, "form"]],
                }
        return res

    def action_toggle_primary_bank_account_trust(self):
        self.check_singleton()
        current_val = self.primary_bank_account_id.allow_out_payment
        self.primary_bank_account_id.allow_out_payment = not current_val

    def action_view_allocation_wizard(self):
        self.check_singleton()
        wizard = self.env["hr.bank.account.allocation.wizard"].create(
            {
                "employee_id": self.id,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Bank Account Allocation"),
            "res_model": "hr.bank.account.allocation.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_view_versions(self):
        self.check_singleton()
        return {
            "type": "ir.actions.act_window",
            "name": self.name + self.env._(" Records"),
            "path": "versions",
            "res_model": "hr.version",
            "view_mode": "list,graph,pivot",
            "views": [
                (self.env.ref("hr.hr_version_list_view").id, "list"),
                (False, "graph"),
                (False, "pivot"),
            ],
            "domain": [("employee_id", "=", self.id)],
            "search_view_id": self.env.ref("hr.hr_version_search_view").id,
        }

    def action_generate_random_barcode(self):
        Employee = self.env["hr.employee"].sudo().with_context(active_test=False)
        minted = set()
        for employee in self:
            for _attempt in range(self._BARCODE_DRAW_ATTEMPTS):
                barcode = "041" + "".join(choice(digits) for _ in range(9))
                if barcode in minted:
                    continue
                if not Employee.search_count([("barcode", "=", barcode)], limit=1):
                    break
            else:
                raise UserError(
                    self.env._(
                        "Could not generate a unique Badge ID after %(attempts)s"
                        " attempts. Please set one manually.",
                        attempts=self._BARCODE_DRAW_ATTEMPTS,
                    )
                )
            minted.add(barcode)
            employee.barcode = barcode

    def _get_tz(self):
        self.check_singleton()
        return (
            self.resource_calendar_id.tz
            or self.tz
            or self.company_id.resource_calendar_id.tz
            or "UTC"
        )

    def _get_tz_batch(self):
        return {emp.id: emp._get_tz() for emp in self}

    def _get_calendar_tz_batch(self, dt=None):
        employees_by_id = self.grouped("id")

        def get_timezones_by_employee_id(employees, date_at=None):
            return {
                emp_id: calendar.sudo().tz or employees_by_id[emp_id].tz
                for emp_id, calendar in employees._get_calendars(date_at).items()
            }

        if not dt:
            return get_timezones_by_employee_id(self)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        employee_timezones = {}
        for tz, employees in self.grouped(lambda emp: emp._get_tz()).items():
            employee_timezones |= get_timezones_by_employee_id(
                employees, dt.astimezone(timezone(tz)).date()
            )
        return employee_timezones

    def _get_calendars(self, date_from=None):
        res = super()._get_calendars(date_from=date_from)
        if not date_from:
            return res

        date_from = fields.Date.to_date(date_from)
        for employee in self:
            employee_versions_sudo = employee.sudo().version_ids.filtered(
                lambda v: v._is_in_contract(date_from)
            )
            version_sudo = employee_versions_sudo[:1] or employee.sudo()._get_version(
                date_from
            )
            if version_sudo:
                res[employee.id] = version_sudo.resource_calendar_id.sudo(False)
        return res

    @staticmethod
    def _combine_tz(day, moment, tz):
        naive = datetime.combine(day, moment)
        return localize_standard(naive, tz) if tz else naive

    def _get_version_periods(self, start, stop, field_name=None, check_contract=False):
        if field_name and field_name not in self.env["hr.version"]._fields:
            raise UserError(
                self.env._(
                    "This field %(field_name)s doesn't exist on this model (hr.version).",
                    field_name=field_name,
                )
            )
        version_periods_by_employee = defaultdict(list)
        if check_contract:
            versions = self._get_versions_with_contract_overlap_with_period(
                start.date(), stop.date()
            )
        else:
            start_date, stop_date = start.date(), stop.date()
            versions = self.version_ids.filtered(
                lambda version: (
                    version.date_start
                    and version.date_start <= stop_date
                    and (not version.date_end or version.date_end >= start_date)
                )
            )
        for version in versions:
            calendar_tz = (
                timezone(version.resource_calendar_id.tz)
                if version.resource_calendar_id
                else timezone(version.employee_id.resource_id.tz)
            )
            date_start = self._combine_tz(
                version.date_start, time.min, calendar_tz
            ).astimezone(UTC)
            end_date = version.date_end
            if end_date:
                date_end = self._combine_tz(
                    end_date + relativedelta(days=1), time.min, calendar_tz
                ).astimezone(UTC)
            else:
                date_end = stop
            version_periods_by_employee[version.employee_id].append(
                (
                    max(date_start, start),
                    min(date_end, stop),
                    version[field_name] if field_name else version,
                )
            )
        return version_periods_by_employee

    def _get_calendar_periods(self, start, stop, check_contract=True):
        return self.sudo()._get_version_periods(
            start, stop, "resource_calendar_id", check_contract
        )

    @api.model
    def _get_all_versions_with_contract_overlap_with_period(self, date_from, date_to):
        all_employees = self.search(
            ["|", ("active", "=", True), ("active", "=", False)]
        )
        return all_employees._get_versions_with_contract_overlap_with_period(
            date_from, date_to
        )

    def _get_unusual_days(self, date_from, date_to=None):
        self.check_singleton()
        date_from_date = datetime.strptime(date_from, "%Y-%m-%d %H:%M:%S").date()
        date_to_date = (
            datetime.strptime(date_to, "%Y-%m-%d %H:%M:%S").date()
            if date_to
            else date_from_date
        )
        employee_versions = (
            self.env["hr.version"]
            .sudo()
            .search([("employee_id", "=", self.id)])
            .filtered(lambda v: v._has_contract_overlap(date_from_date, date_to_date))
        )
        if not employee_versions:
            return (
                self.resource_calendar_id or self.env.company.resource_calendar_id
            )._get_unusual_days(
                datetime.combine(date_from_date, time.min).replace(tzinfo=UTC),
                datetime.combine(date_to_date, time.max).replace(tzinfo=UTC),
                self.company_id,
            )
        unusual_days = {}
        for version in employee_versions:
            tmp_date_from = max(date_from_date, version.date_start)
            tmp_date_to = (
                min(date_to_date, version.date_end)
                if version.date_end
                else date_to_date
            )
            unusual_days.update(
                version.resource_calendar_id.sudo(False)._get_unusual_days(
                    datetime.combine(
                        fields.Date.from_string(tmp_date_from), time.min
                    ).replace(tzinfo=UTC),
                    datetime.combine(
                        fields.Date.from_string(tmp_date_to), time.max
                    ).replace(tzinfo=UTC),
                    self.company_id,
                )
            )
        return unusual_days

    def _get_employee_field_names_to_empty_on_archive(self):
        return ["parent_id", "coach_id"]

    def _get_user_field_names_to_empty_on_archive(self):
        return []

    def _get_employee_tz(self):
        self.check_singleton()
        return timezone(self.tz) if self.tz else None

    def _get_fallback_calendar(self):
        self.check_singleton()
        return self.resource_calendar_id or self.company_id.resource_calendar_id

    def _get_version_windows(self, start, stop, tz=None):
        self.check_singleton()
        versions = self.sudo()._get_versions_with_contract_overlap_with_period(
            start.date(), stop.date()
        )
        for version in versions:
            window_start = self._combine_tz(version.date_start, time.min, tz)
            window_stop = (
                self._combine_tz(version.date_end, time.max, tz)
                if version.date_end
                else stop
            )
            calendar = (
                version.resource_calendar_id or version.company_id.resource_calendar_id
            )
            yield version, max(start, window_start), min(stop, window_stop), calendar

    def _get_fields_store_avatar_card(self, target):
        employee_fields = [
            "company_id",
            Store.One("department_id", ["name"]),
            "work_email",
            Store.One("work_location_id", ["location_type", "name"]),
            "work_phone",
        ]
        user = target.get_user(self.env)
        if user.has_group("hr.group_hr_user"):
            employee_fields.append("job_title")
        if len(self) > 0:
            self.fetch(
                [
                    field.field_name if isinstance(field, Store.Attr) else field
                    for field in employee_fields
                ]
            )
        return employee_fields

    def get_bank_account_salary_allocation(self, account_id):
        ba_info = (self.salary_distribution or {}).get(str(account_id), {})
        return ba_info.get("amount", 0), ba_info.get("amount_is_percentage", True)

    def get_remaining_percentage(self):
        self.check_singleton()
        distribution = self.salary_distribution or {}
        allocated = 0.0

        for vals in distribution.values():
            if vals.get("amount_is_percentage"):
                allocated += vals.get("amount", 0.0)

        remaining = 100.0 - allocated
        return max(0.0, remaining)

    def _get_accounts_with_fixed_allocations(self):
        self.check_singleton()
        distribution = self.salary_distribution or {}
        return self.bank_account_ids.filtered(
            lambda a: (
                not distribution.get(str(a.id), {}).get("amount_is_percentage", True)
            )
        )

    def _fold_version_windows(self, start, stop, fallback, per_window, combine):
        self.check_singleton()
        employee_tz = self._get_employee_tz()
        windows = list(self._get_version_windows(start, stop, employee_tz))
        if not windows:
            return fallback(self._get_fallback_calendar(), employee_tz)
        result = None
        for index, window in enumerate(windows):
            part = per_window(index, window, employee_tz)
            result = part if result is None else combine(result, part)
        return result

    def _get_attendance_intervals(self, start, stop, lunch=False):
        self.check_singleton()
        if not lunch:
            return self._get_expected_attendances(start, stop)
        resource = self.resource_id

        def fallback(calendar, _tz):
            return calendar._attendance_intervals_batch(
                start, stop, resource, lunch=True
            )[resource.id]

        def per_window(_index, window, _tz):
            _version, window_start, window_stop, calendar = window
            return calendar._attendance_intervals_batch(
                window_start, window_stop, resources=resource, lunch=True
            )[resource.id]

        return self._fold_version_windows(
            start, stop, fallback, per_window, lambda a, b: a | b
        )

    def _get_expected_attendances(self, date_from, date_to):
        self.check_singleton()
        resource = self.resource_id
        company_domain = [("company_id", "in", [False, self.company_id.id])]

        def fallback(calendar, tz):
            return calendar._work_intervals_batch(
                date_from,
                date_to,
                tz=tz,
                resources=resource,
                compute_leaves=True,
                domain=company_domain,
            )[resource.id]

        def per_window(index, window, tz):
            version, window_start, window_stop, calendar = window
            if index == 0:
                window_start = max(
                    date_from,
                    self._combine_tz(version.contract_date_start, time.min, tz),
                )
            return calendar._work_intervals_batch(
                window_start,
                window_stop,
                tz=tz,
                resources=resource,
                compute_leaves=True,
                domain=[*company_domain, ("time_type", "=", "leave")],
            )[resource.id]

        return self._fold_version_windows(
            date_from, date_to, fallback, per_window, lambda a, b: a | b
        )

    def _get_calendar_attendances(self, date_from, date_to):
        self.check_singleton()

        def fallback(calendar, tz):
            return calendar.with_context(employee_timezone=tz).get_work_duration_data(
                date_from,
                date_to,
                domain=[("company_id", "in", [False, self.company_id.id])],
            )

        def per_window(_index, window, tz):
            version, window_start, window_stop, calendar = window
            return calendar.with_context(employee_timezone=tz).get_work_duration_data(
                window_start,
                window_stop,
                domain=[("company_id", "in", [False, version.company_id.id])],
            )

        def combine(total, part):
            return {
                "days": total["days"] + part["days"],
                "hours": total["hours"] + part["hours"],
            }

        return self._fold_version_windows(
            date_from, date_to, fallback, per_window, combine
        )

    @api.model
    def get_import_templates(self):
        return [
            {
                "label": self.env._("Import Template for Employees"),
                "template": "/hr/static/xls/hr_employee.xls",
            }
        ]

    def _get_age(self, target_date=None):
        self.check_singleton()
        if target_date is None:
            target_date = fields.Date.context_today(self.env.user)
        return relativedelta(target_date, self.birthday).years if self.birthday else 0

    def _get_departure_date(self):
        self.check_singleton()
        if self.date_end and self.date_end < fields.Date.today():
            return self.departure_date
        return False

    def _get_versions_with_contract_overlap_with_period(self, date_from, date_to):
        return self.version_ids.filtered_domain(
            [
                ("contract_date_start", "!=", False),
                ("contract_date_start", "<=", date_to),
                "|",
                ("contract_date_end", ">=", date_from),
                ("contract_date_end", "=", False),
            ]
        )

    def get_avatar_card_data(self, field_names):
        return self.read(field_names)

    def _get_phone_number_fields(self):
        return ["mobile_phone"]

    def _remove_work_contact_id(self, user, employee_company=None):
        if not user:
            return
        if employee_company:
            companies = {employee_company}
        else:
            companies = set(self.mapped("company_id").ids) or {self.env.company.id}
        squatters = user.partner_id.employee_ids.filtered(
            lambda e: not e.user_id and e.company_id.id in companies and e not in self
        )
        if not squatters:
            return
        fresh = (
            self.env["res.partner"]
            .sudo()
            .create(
                [
                    {
                        "name": employee.name,
                        "email": employee.work_email,
                        "phone": employee.work_phone,
                    }
                    for employee in squatters
                ]
            )
        )
        for employee, partner in zip(squatters, fresh, strict=True):
            employee.partner_id = partner

    def _generate_missing_avatars(self):
        if not self.env["ir.ui.view"].sudo(False).has_access("write"):
            return
        for partner in self.partner_id:
            if partner.image_1920 or not (partner.name or "").strip():
                continue
            partner.image_1920 = partner._prepare_avatar_svg()

    def _sync_user(self, user):
        vals = {"user_id": user.id}
        if user:
            vals["partner_id"] = user.partner_id.id
        if user.tz:
            vals["tz"] = user.tz
        return vals

    def _prepare_resource_values(self, vals, tz):
        resource_vals = super()._prepare_resource_values(vals, tz)
        user_id = vals.pop("user_id", None)
        if user_id:
            resource_vals["user_id"] = user_id
        active_status = vals.get("active")
        if active_status is not None:
            resource_vals["active"] = active_status
        return resource_vals

    _IDENTIFIER_TYPES = {
        "identification_id": "NATIONAL_ID",
        "ssnid": "SSN",
        "passport_id": "PASSPORT",
        "barcode": "BADGE",
    }

    @api.depends(
        "partner_id.identifier_ids.type_id",
        "partner_id.identifier_ids.value",
        "partner_id.identifier_ids.valid_until",
    )
    def _compute_identifiers(self):
        for employee in self:
            by_code = {
                identifier.type_id.code: identifier
                for identifier in employee.partner_id.identifier_ids
            }
            for fname, code in self._IDENTIFIER_TYPES.items():
                employee[fname] = by_code[code].value if code in by_code else False
            passport = by_code.get("PASSPORT")
            employee.passport_expiration_date = (
                passport.valid_until if passport else False
            )

    def _inverse_identifiers(self):
        Type = self.env["res.partner.identifier.type"].sudo()
        types = {
            identifier_type.code: identifier_type
            for identifier_type in Type.search(
                [("code", "in", list(self._IDENTIFIER_TYPES.values()))]
            )
        }
        for employee in self:
            partner = employee.partner_id.sudo()
            by_code = {
                identifier.type_id.code: identifier
                for identifier in partner.identifier_ids
            }
            for fname, code in self._IDENTIFIER_TYPES.items():
                value = employee[fname]
                row = by_code.get(code)
                vals = {"value": value}
                if code == "PASSPORT":
                    vals["valid_until"] = employee.passport_expiration_date
                if not value:
                    if row:
                        row.unlink()
                    continue
                if row:
                    changed = {k: v for k, v in vals.items() if row[k] != v}
                    if changed:
                        row.write(changed)
                else:
                    partner.identifier_ids.create(
                        {"partner_id": partner.id, "type_id": types[code].id, **vals}
                    )

    @api.model
    def _search_identifier(self, code, operator, value):
        if operator in ("=", "!=") and not value:
            has_one = "any" if operator == "!=" else "not any"
            return [
                ("partner_id.identifier_ids", has_one, [("type_id.code", "=", code)])
            ]
        return [
            (
                "partner_id.identifier_ids",
                "any",
                [("type_id.code", "=", code), ("value", operator, value)],
            )
        ]

    def _search_identification_id(self, operator, value):
        return self._search_identifier("NATIONAL_ID", operator, value)

    def _search_ssnid(self, operator, value):
        return self._search_identifier("SSN", operator, value)

    def _search_passport_id(self, operator, value):
        return self._search_identifier("PASSPORT", operator, value)

    def _search_barcode(self, operator, value):
        return self._search_identifier("BADGE", operator, value)

    def _reparent_private_address(self):
        for employee in self.sudo():
            home = employee.private_address_id
            contact = employee.partner_id
            if home and contact and home.parent_id != contact:
                home.parent_id = contact

    def _update_bank_account_contact(self, partner_id):
        accounts_sudo = (
            self.env["res.partner.bank"].sudo().browse(self.bank_account_ids.ids)
        )
        to_move = accounts_sudo.filtered(
            lambda account: account.partner_id.id != partner_id
        )
        if not to_move:
            return
        trusted = to_move.filtered("allow_out_payment")
        if trusted:
            trusted.allow_out_payment = False
        if partner_id:
            to_move.partner_id = partner_id
