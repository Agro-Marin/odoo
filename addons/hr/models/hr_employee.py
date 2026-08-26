import re
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from random import choice
from string import digits

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models, tools
from odoo.exceptions import AccessError, RedirectWarning, UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.datetime import localize_standard, timezone
from odoo.libs.intervals import Intervals
from odoo.libs.numbers import float_is_zero
from odoo.tools import SQL, Query, convert, email_normalize, format_time

from odoo.addons.hr.models.hr_version import format_date_abbr
from odoo.addons.mail.tools.discuss import Store

# This sentinel object, when in the context, provides read access to the
# model 'hr.employee' in certain situations, like when setting a many2many
# field for users that don't have access to `hr.employee`.
_ALLOW_READ_HR_EMPLOYEE = object()


class HrEmployee(models.Model):
    """
    NB: Any field only available on the model hr.employee (i.e. not on the
    hr.employee.public model) should have `groups="hr.group_hr_user"` on its
    definition to avoid being prefetched when the user hasn't access to the
    hr.employee model. Indeed, the prefetch loads the data for all the fields
    that are available according to the group defined on them.
    """

    _name = "hr.employee"
    _description = "Employee"
    _order = "name"
    _inherit = [
        "mixin.mail.thread.main.attachment",
        "mixin.mail.activity",
        "mixin.resource",
        "mixin.avatar",
    ]
    _mail_post_access = "read"
    _primary_email = "work_email"
    _mail_partner_fields = ("work_contact_id", "user_partner_id")
    _inherits = {"hr.version": "version_id"}

    # DISCLAIMER: Dirty hack fields (see check_field_access_rights / _has_field_access):
    # not prefetched (not stored) and would crash if read directly by non-hr users.
    _DIRTY_HACK_PRIVATE_FIELDS = (
        "activity_calendar_event_id",
        "rating_ids",
        "website_message_ids",
        "message_has_sms_error",
    )

    # versions
    version_id = fields.Many2one(
        "hr.version",
        compute="_compute_version_id",
        search="_search_version_id",
        ondelete="cascade",
        required=True,
        store=False,
        compute_sudo=True,
        groups="hr.group_hr_user",
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
        required=True,
    )
    versions_count = fields.Integer(
        compute="_compute_versions_count", groups="hr.group_hr_user"
    )

    @api.model
    def _lang_get(self):
        return self.env["res.lang"].get_installed()

    # resource and user
    # required on the resource, make sure required="True" set in the view
    name = fields.Char(
        string="Employee Name",
        related="resource_id.name",
        store=True,
        readonly=False,
        tracking=True,
    )
    resource_id = fields.Many2one("resource.resource", required=True)
    # required because the mixin already creates it so it is not related to the version_id
    resource_calendar_id = fields.Many2one(
        related="version_id.resource_calendar_id",
        inherited=True,
        index=False,
        store=False,
        check_company=True,
    )
    user_id = fields.Many2one(
        "res.users",
        "User",
        related="resource_id.user_id",
        store=True,
        readonly=False,
        check_company=True,
        precompute=True,
        index="btree_not_null",
        ondelete="restrict",
    )
    user_partner_id = fields.Many2one(
        related="user_id.partner_id", related_sudo=False, string="User's partner"
    )
    share = fields.Boolean(related="user_id.share")
    phone = fields.Char(related="user_id.phone")
    im_status = fields.Char(related="user_id.im_status")
    email = fields.Char(related="user_id.email")
    hr_presence_state = fields.Selection(
        [
            ("present", "Present"),
            ("absent", "Absent"),
            ("archive", "Archived"),
            ("out_of_working_hour", "Off-Hours"),
        ],
        compute="_compute_hr_presence_state",
        default="out_of_working_hour",
    )
    last_activity = fields.Date(compute="_compute_last_activity")
    last_activity_time = fields.Char(compute="_compute_last_activity")
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
    show_hr_icon_display = fields.Boolean(compute="_compute_presence_icon")
    newly_hired = fields.Boolean(
        "Newly Hired", compute="_compute_newly_hired", search="_search_newly_hired"
    )

    active = fields.Boolean(
        "Active", related="resource_id.active", default=True, store=True, readonly=False
    )
    company_id = fields.Many2one("res.company", required=True, tracking=True)
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
    work_phone = fields.Char(
        "Work Phone",
        store=True,
        readonly=False,
        tracking=True,
        compute="_compute_work_contact_details",
        inverse="_inverse_work_contact_details",
    )
    mobile_phone = fields.Char("Work Mobile")
    work_email = fields.Char(
        "Work Email",
        compute="_compute_work_contact_details",
        store=True,
        inverse="_inverse_work_contact_details",
    )
    work_contact_id = fields.Many2one(
        "res.partner", "Work Contact", copy=False, index="btree_not_null"
    )
    # private info
    legal_name = fields.Char(
        compute="_compute_legal_name",
        store=True,
        readonly=False,
        groups="hr.group_hr_user",
    )
    is_user_active = fields.Boolean(
        related="user_id.active", string="User's active", groups="hr.group_hr_user"
    )
    private_phone = fields.Char(string="Private Phone", groups="hr.group_hr_user")
    private_email = fields.Char(string="Private Email", groups="hr.group_hr_user")
    lang = fields.Selection(
        selection=_lang_get, string="Lang", groups="hr.group_hr_user"
    )
    place_of_birth = fields.Char(
        "Place of Birth", groups="hr.group_hr_user", tracking=True
    )
    country_of_birth = fields.Many2one(
        "res.country",
        string="Country of Birth",
        groups="hr.group_hr_user",
        tracking=True,
    )
    birthday = fields.Date("Birthday", groups="hr.group_hr_user", tracking=True)
    birthday_public_display = fields.Boolean(
        "Show to all employees", groups="hr.group_hr_user", default=False
    )
    birthday_public_display_string = fields.Char(
        "Public Date of Birth",
        compute="_compute_birthday_public_display_string",
        default="hidden",
    )
    # Personal Information
    country_id = fields.Many2one(
        "res.country", "Nationality (Country)", groups="hr.group_hr_user", tracking=True
    )
    identification_id = fields.Char(
        string="Identification No",
        help="Enter the employee's National Identification Number issued by the government (e.g., Aadhaar, SIN, NIN). This is used for official records and statutory compliance.",
        groups="hr.group_hr_user",
        tracking=True,
    )
    ssnid = fields.Char(
        "SSN No",
        help="Social Security Number",
        groups="hr.group_hr_user",
        tracking=True,
    )
    passport_id = fields.Char("Passport No", groups="hr.group_hr_user", tracking=True)
    passport_expiration_date = fields.Date(
        "Passport Expiration Date", groups="hr.group_hr_user", tracking=True
    )
    sex = fields.Selection(
        [
            ("male", "Male"),
            ("female", "Female"),
            ("other", "Other"),
        ],
        groups="hr.group_hr_user",
        tracking=True,
        help="This is the legal sex recognized by the state.",
        string="Gender",
    )

    private_street = fields.Char(
        string="Private Street", groups="hr.group_hr_user", tracking=True
    )
    private_street2 = fields.Char(
        string="Private Street2", groups="hr.group_hr_user", tracking=True
    )
    private_city = fields.Char(
        string="Private City", groups="hr.group_hr_user", tracking=True
    )
    allowed_country_state_ids = fields.Many2many(
        "res.country.state",
        compute="_compute_allowed_country_state_ids",
        groups="hr.group_hr_user",
    )
    private_state_id = fields.Many2one(
        "res.country.state",
        string="Private State",
        domain="[('id', 'in', allowed_country_state_ids)]",
        groups="hr.group_hr_user",
        tracking=True,
    )
    private_zip = fields.Char(
        string="Private Zip", groups="hr.group_hr_user", tracking=True
    )
    private_country_id = fields.Many2one(
        "res.country",
        string="Private Country",
        groups="hr.group_hr_user",
        tracking=True,
    )

    distance_home_work = fields.Integer(
        string="Home-Work Distance", groups="hr.group_hr_user", tracking=True
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
        default="kilometers",
        required=True,
        tracking=True,
    )

    marital = fields.Selection(
        selection="_get_marital_status_selection",
        string="Marital Status",
        groups="hr.group_hr_user",
        default="single",
        required=True,
        tracking=True,
    )
    spouse_complete_name = fields.Char(
        string="Spouse Legal Name", groups="hr.group_hr_user", tracking=True
    )
    spouse_birthdate = fields.Date(
        string="Spouse Birthdate", groups="hr.group_hr_user", tracking=True
    )
    children = fields.Integer(
        string="Dependent Children", groups="hr.group_hr_user", tracking=True
    )

    bank_account_ids = fields.Many2many(
        "res.partner.bank",
        relation="employee_bank_account_rel",
        column1="employee_id",
        column2="bank_account_id",
        domain="[('partner_id', '=', work_contact_id), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        groups="hr.group_hr_user",
        tracking=True,
        string="Bank Accounts",
        help="Employee bank accounts to pay salaries",
    )
    is_trusted_bank_account = fields.Boolean(
        compute="_compute_is_trusted_bank_account", groups="hr.group_hr_user"
    )
    primary_bank_account_id = fields.Many2one(
        "res.partner.bank",
        compute="_compute_primary_bank_account_id",
        groups="hr.group_hr_user",
    )
    has_multiple_bank_accounts = fields.Boolean(
        compute="_compute_has_multiple_bank_accounts",
        default=False,
        groups="hr.group_hr_user",
    )
    salary_distribution = fields.Json(
        string="Salary Distribution",
        compute="_compute_salary_distribution",
        groups="hr.group_hr_user",
        store=True,
        readonly=False,
    )
    """
    {
    `bank_account_id`: {
        'sequence': int,
        'amount': float,
        'amount_is_percentage': boolean,
        }
    }
    """

    permit_no = fields.Char("Work Permit No", groups="hr.group_hr_user", tracking=True)
    visa_no = fields.Char("Visa No", groups="hr.group_hr_user", tracking=True)
    visa_expire = fields.Date(
        "Visa Expiration Date", groups="hr.group_hr_user", tracking=True
    )
    work_permit_expiration_date = fields.Date(
        "Work Permit Expiration Date", groups="hr.group_hr_user", tracking=True
    )
    has_work_permit = fields.Binary(string="Work Permit", groups="hr.group_hr_user")
    work_permit_name = fields.Char(
        "work_permit_name",
        compute="_compute_work_permit_name",
        groups="hr.group_hr_user",
    )
    certificate = fields.Selection(
        selection="_get_certificate_selection",
        string="Certificate Level",
        groups="hr.group_hr_user",
        tracking=True,
    )
    study_field = fields.Char(
        "Field of Study", groups="hr.group_hr_user", tracking=True
    )
    study_school = fields.Char("School", groups="hr.group_hr_user", tracking=True)
    emergency_contact = fields.Char(groups="hr.group_hr_user", tracking=True)
    emergency_phone = fields.Char(groups="hr.group_hr_user", tracking=True)
    work_location_name = fields.Char(
        "Work Location Name", compute="_compute_work_location_name"
    )
    work_location_type = fields.Selection(
        [("home", "Home"), ("office", "Office"), ("other", "Other")],
        compute="_compute_work_location_type",
        tracking=True,
    )

    # All version fields needing a specific group to be accessible should also have `inherited=True` set on its definition to make sure those fields are linked to `_inherits` on `hr.version`
    # Explicitly redefined (like resource_calendar_id) so the delegate is
    # related_sudo=True: reading it must not traverse the group-restricted
    # `version_id` as the current user, which would break self-service access
    # (work_location_id is exposed in HR_WRITABLE_FIELDS / the preferences view).
    work_location_id = fields.Many2one(
        related="version_id.work_location_id",
        inherited=True,
        store=False,
        check_company=True,
    )
    contract_date_start = fields.Date(
        readonly=False,
        related="version_id.contract_date_start",
        inherited=True,
        groups="hr.group_hr_manager",
    )
    contract_date_end = fields.Date(
        readonly=False,
        related="version_id.contract_date_end",
        inherited=True,
        groups="hr.group_hr_manager",
    )
    trial_date_end = fields.Date(
        readonly=False,
        related="version_id.trial_date_end",
        inherited=True,
        groups="hr.group_hr_manager",
    )
    contract_wage = fields.Monetary(
        related="version_id.contract_wage", inherited=True, groups="hr.group_hr_manager"
    )
    date_start = fields.Date(
        related="version_id.date_start", inherited=True, groups="hr.group_hr_manager"
    )
    date_end = fields.Date(
        related="version_id.date_end", inherited=True, groups="hr.group_hr_manager"
    )
    is_current = fields.Boolean(
        related="version_id.is_current", inherited=True, groups="hr.group_hr_manager"
    )
    is_past = fields.Boolean(
        related="version_id.is_past", inherited=True, groups="hr.group_hr_manager"
    )
    is_future = fields.Boolean(
        related="version_id.is_future", inherited=True, groups="hr.group_hr_manager"
    )
    is_in_contract = fields.Boolean(
        related="version_id.is_in_contract",
        inherited=True,
        groups="hr.group_hr_manager",
    )
    structure_type_id = fields.Many2one(
        readonly=False,
        related="version_id.structure_type_id",
        inherited=True,
        groups="hr.group_hr_manager",
    )
    contract_type_id = fields.Many2one(
        readonly=False,
        related="version_id.contract_type_id",
        inherited=True,
        groups="hr.group_hr_manager",
    )

    # employee in company
    parent_id = fields.Many2one(
        "hr.employee",
        "Manager",
        tracking=True,
        index=True,
        domain="['|', ('company_id', '=', False), ('company_id', 'in', allowed_company_ids)]",
    )
    child_ids = fields.One2many(
        "hr.employee", "parent_id", string="Direct subordinates"
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
    category_ids = fields.Many2many(
        "hr.employee.category",
        "employee_category_rel",
        "employee_id",
        "category_id",
        groups="hr.group_hr_user",
        string="Tags",
    )
    tz = fields.Selection(tracking=True)
    # misc
    color = fields.Integer("Color Index", default=0)
    barcode = fields.Char(
        string="Badge ID",
        help="ID used for employee identification.",
        groups="hr.group_hr_user",
        copy=False,
    )
    pin = fields.Char(
        string="PIN",
        groups="hr.group_hr_user",
        copy=False,
        help="PIN used to Check In/Out in the Kiosk Mode of the Attendance application (if enabled in Configuration) and to change the cashier in the Point of Sale application.",
    )
    message_main_attachment_id = fields.Many2one(groups="hr.group_hr_user")
    id_card = fields.Binary(string="ID Card Copy", groups="hr.group_hr_user")
    driving_license = fields.Binary(string="Driving License", groups="hr.group_hr_user")
    private_car_plate = fields.Char(
        groups="hr.group_hr_user",
        help="If you have more than one car, just separate the plates by a space.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
        groups="hr.group_hr_user",
    )
    related_partners_count = fields.Integer(
        compute="_compute_related_partners_count", groups="hr.group_hr_user"
    )
    # properties
    employee_properties = fields.Properties(
        "Properties",
        definition="company_id.employee_properties_definition",
        precompute=False,
        groups="hr.group_hr_user",
    )

    # mixin.mail.activity
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

    # mixin.mail.thread mixin
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

    # A 9-digit draw over a badge space this sparse collides with vanishing
    # probability; the budget exists so a pathological database fails loudly
    # rather than looping.
    _BARCODE_DRAW_ATTEMPTS = 32

    _barcode_uniq = models.Constraint(
        "unique (barcode)",
        "The Badge ID must be unique, this one is already assigned to another employee.",
    )
    _user_uniq = models.Constraint(
        "unique (user_id, company_id)",
        "A user cannot be linked to multiple employees in the same company.",
    )

    @api.model
    def _is_version_delegate_field(self, fname):
        """Is ``fname`` an ``_inherits`` delegate of hr.version on this model?

        ``create``, ``new`` and ``write`` each split incoming values along this
        line; two of them used to test ``inherited`` alone, which happens to be
        equivalent only because hr.version is the sole delegate. Stating the
        target model once keeps that from being an accident.
        """
        field = self._fields.get(fname)
        return bool(
            field and field.inherited and field.related_field.model_name == "hr.version"
        )

    @api.model
    def _split_version_vals(self, vals):
        """Return ``(employee_vals, version_vals)``, leaving ``vals`` untouched."""
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
            employee_vals, version_vals = self._split_version_vals(vals)
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
        # NB: depend on the *stored* inputs that determine the primary account
        # (bank_account_ids + salary_distribution) and on those accounts'
        # allow_out_payment — never on ``primary_bank_account_id.allow_out_payment``.
        # ``primary_bank_account_id`` is a non-stored compute, so that dependency
        # path makes the ORM reverse-search hr.employee by a non-stored field when
        # allow_out_payment changes (e.g. action_toggle_primary_bank_account_trust)
        # and raise "Cannot convert ... to SQL because it is not stored".
        for employee in self:
            employee.is_trusted_bank_account = (
                employee.primary_bank_account_id.allow_out_payment
            )

    @api.depends("bank_account_ids")
    def _compute_has_multiple_bank_accounts(self):
        for employee in self:
            if employee.bank_account_ids and len(employee.bank_account_ids) > 1:
                employee.has_multiple_bank_accounts = True
            else:
                employee.has_multiple_bank_accounts = False

    @api.depends("bank_account_ids")
    def _compute_salary_distribution(self):
        for employee in self:
            current_salary_distribution = employee.salary_distribution or {}
            current_ids = set(map(int, current_salary_distribution.keys()))
            account_ids = set(employee.bank_account_ids.ids)

            added_ids = account_ids - current_ids
            removed_ids = current_ids - account_ids
            unchanged_ids = account_ids & current_ids

            # Preserve existing data and order
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

            # Redistribute removed % to first item
            removed_percentage = sum(
                current_salary_distribution[str(i)]["amount"]
                for i in removed_ids
                if str(i) in current_salary_distribution
                and current_salary_distribution[str(i)]["amount_is_percentage"]
            )
            if removed_percentage and ordered:
                first_id = str(ordered[0][0])
                if new_salary_distribution[first_id]["amount_is_percentage"]:
                    new_salary_distribution[first_id]["amount"] += removed_percentage

            # Add new entries with remaining %
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
                    amount = remaining
                new_salary_distribution[str(new_id)] = {
                    "amount": amount,
                    "amount_is_percentage": True,
                    "sequence": seq,
                }
                remaining -= amount

            employee.salary_distribution = new_salary_distribution

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
                if is_percentage:
                    check_total = True
                    total += amount

            if check_total and not float_is_zero(total - 100.0, precision_digits=4):
                raise ValidationError(
                    self.env._(
                        "Total salary distribution on bank accounts must be exactly 100%."
                    )
                )

    @api.model
    def _create(self, data_list):
        versions = [vals["stored"].pop("version_id", None) for vals in data_list]
        result = super()._create(data_list)
        # 1:1 by construction (``versions`` was built from ``data_list`` and
        # ``result`` is super()'s answer for it): assert it rather than letting a
        # mismatch silently truncate the loop.
        for employee, version_id, vals in zip(result, versions, data_list, strict=True):
            version = self.env["hr.version"].browse(version_id)
            version.employee_id = employee.id
            inherited = (vals.get("inherited") or {}).get("hr.version", {})
            version.write({**inherited, "employee_id": employee.id})
        return result

    @api.model
    @api.deprecated("Override of a deprecated method")
    def check_field_access_rights(self, operation, field_names):
        # DISCLAIMER: Dirty hack to avoid having to create a bridge module to override only a
        # groups on a field which is not prefetched (because not stored) but would crash anyway
        # if we try to read them directly (very uncommon use case). Don't add your field on this
        # list if you can specify the group on the field directly (as all the other fields).
        result = super().check_field_access_rights(operation, field_names)
        if not self.env.user.has_group("hr.group_hr_user"):
            result = [
                field
                for field in result
                if field not in self._DIRTY_HACK_PRIVATE_FIELDS
            ]
        return result

    def _has_field_access(self, field, operation):
        # DISCLAIMER: Dirty hack to avoid having to create a bridge module to override only a
        # groups on a field which is not prefetched (because not stored) but would crash anyway
        # if we try to read them directly (very uncommon use case). Don't add your field on this
        # list if you can specify the group on the field directly (as all the other fields).
        return super()._has_field_access(field, operation) and (
            self.env.su
            or self.env.user.has_group("hr.group_hr_user")
            or field.name not in self._DIRTY_HACK_PRIVATE_FIELDS
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

    def _inverse_km_home_work(self):
        for employee in self:
            employee.distance_home_work = (
                employee.km_home_work / 1.609
                if employee.distance_home_work_unit == "miles"
                else employee.km_home_work
            )

    @api.model
    def _get_marital_status_selection(self):
        return [
            ("single", self.env._("Single")),
            ("married", self.env._("Married")),
            ("cohabitant", self.env._("Legal Cohabitant")),
            ("widower", self.env._("Widower")),
            ("divorced", self.env._("Divorced")),
        ]

    @api.constrains("ssnid")
    def _check_ssnid(self):
        # By default, a Social Security Number is always valid, but each localization
        # may want to add its own constraints
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

    @api.model
    def _get_new_hire_field(self):
        return "create_date"

    @api.depends(lambda self: [self._get_new_hire_field()])
    def _compute_newly_hired(self):
        new_hire_field = self._get_new_hire_field()
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
        """
        This method compute the state defining the display icon in the kanban view.
        It can be overriden to add other possibilities, like time off or attendances recordings.
        """
        for employee in self:
            employee.hr_icon_display = "presence_" + employee.hr_presence_state
            employee.show_hr_icon_display = bool(employee.user_id)

    @api.model
    def _get_certificate_selection(self):
        return [
            ("graduate", self.env._("Graduate")),
            ("bachelor", self.env._("Bachelor")),
            ("master", self.env._("Master")),
            ("doctor", self.env._("Doctor")),
            ("other", self.env._("Other")),
        ]

    def _get_first_versions(self):
        self.ensure_one()
        versions = self.version_ids
        if self.env.context.get("before_date"):
            versions = versions.filtered(
                lambda c: c.date_start <= self.env.context["before_date"]
            )
        return versions

    def _get_first_version_date(self, no_gap=True):
        self.ensure_one()
        if not self.env.su and not self.env.user.has_group("hr.group_hr_user"):
            raise AccessError(
                self.env._(
                    "Only HR users can access first version date on an employee."
                )
            )

        def remove_gap(versions):
            # We do not consider a gap of more than 4 days to be a same occupation
            # versions are considered to be ordered correctly
            if not versions:
                return self.env["hr.version"]
            if len(versions) == 1:
                return versions
            current_version = versions[0]
            older_versions = versions[1:]
            current_date = current_version.date_start
            for i, other_version in enumerate(older_versions):
                # Consider current_version.date_end being false as an error and cut the loop
                gap = (current_date - (other_version.date_end or date(2100, 1, 1))).days
                current_date = other_version.date_start
                if gap >= 4:
                    return older_versions[0:i] + current_version
            return older_versions + current_version

        versions = self._get_first_versions().sorted("date_start", reverse=True)
        if no_gap:
            versions = remove_gap(versions)
        return min(versions.mapped("date_start")) if versions else False

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
        # Single batched query for all employees to avoid an N+1 search
        # (the cron runs this over the whole table).
        versions = self.env["hr.version"].search(
            [
                ("employee_id", "in", self.ids),
                ("date_version", "<=", fields.Date.today()),
            ],
            order="date_version asc",
        )
        # Latest matching version per employee (ascending order => last wins).
        latest_version_by_employee = {}
        for version in versions:
            latest_version_by_employee[version.employee_id.id] = version
        for employee in self:
            new_current_version = latest_version_by_employee.get(employee.id, False)
            if not new_current_version and employee.version_ids:
                new_current_version = employee.version_ids[0]
            # To not trigger computed properties if still the same version
            if employee.current_version_id != new_current_version:
                employee.current_version_id = new_current_version

    def _cron_update_current_version_id(self):
        # ``search([])`` is active-only, so archived employees' stored
        # ``current_version_id`` was never refreshed -- and hr.employee.public
        # JOINs on that column, so their public row showed a stale version
        # forever.
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
        """This is required to search for the related fields of version_id as version_id is not stored"""
        if field_expr == "version_id":
            field_expr = "current_version_id"
        return super()._field_to_sql(alias, field_expr, query)

    def _get_version(self, date=None):
        """
        Return the version that should be used for the given date.
        If no valid version is found, we return the very first version of the employee.
        """
        date = date or fields.Date.today()
        self.ensure_one()
        versions = self.version_ids.filtered_domain([("date_version", "<=", date)])
        return (
            max(versions, key=lambda v: v.date_version)
            if versions
            else self.version_ids[0]
        )

    @staticmethod
    def _to_version_date(value):
        if isinstance(value, str):
            return fields.Date.to_date(value)
        if isinstance(value, datetime):
            return value.date()
        return value

    def _get_new_version_dates(self, values):
        """``create_version``'s date normalisation and its one hard precondition.

        Returns ``(date, contract_date_start, contract_date_end, date_from,
        date_to)`` -- the last two being the contract the employee is already in
        at ``date``, which the caller needs to decide whether to propagate.
        """
        date = self._to_version_date(values.get("date_version", False))
        if not date:
            raise ValueError("date_version is required")

        date_from, date_to = self.sudo()._get_contract_dates(date)
        contract_date_start = self._to_version_date(
            values.get("contract_date_start", date_from)
        )
        contract_date_end = self._to_version_date(
            values.get("contract_date_end", date_to)
        )

        # A contract end without a start is invalid (hr_version enforces
        # check_contract_start_date_defined at the DB level). Reject it here with
        # a clear message instead of letting it surface as an opaque
        # CheckViolation deep in the create/sync below -- this happens when a
        # caller passes ``contract_date_end`` for a ``date`` at which the employee
        # is not in contract (so ``date_from`` is False).
        if contract_date_end and not contract_date_start:
            raise UserError(
                self.env._("A contract end date requires a contract start date.")
            )
        return date, contract_date_start, contract_date_end, date_from, date_to

    def _update_sibling_contract_end(
        self, employee_id, date_from, date_to, contract_date_start, contract_date_end
    ):
        """Propagate a changed end date to the versions sharing that SAME contract.

        Guarding on ``date_from`` matters: when the employee is not in contract at
        the target date it is False, and without the guard the search below
        matches *every* non-contract version (contract_date_start = False) and
        stamps an end date onto versions that have no start -- which then trips
        the hr_version_check_contract_start_date_defined constraint.
        """
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
        self.ensure_one()
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
        # to be sure even if the user has no access to certain fields, we can still copy the verison without any issues.
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
        # apply the changes on the new versions.
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
            if (
                properties_fields_vals
            ):  # make sure properties vals are correctly copied.
                new_version.sudo().write(properties_fields_vals)
            new_version.write(new_version_vals)
        return new_version

    def create_contract(self, date):
        # Here we can assume that there is no existing contract on the date given
        self.ensure_one()
        if date and isinstance(date, str):
            date = fields.Date.to_date(date)

        contracts = self._get_contract_versions(date)[self.id]
        future_contract_dates = [d for d in list(contracts.keys()) if d > date]
        new_contract_date_end = (
            min(future_contract_dates) + relativedelta(days=-1)
            if future_contract_dates
            else False
        )

        # There is already a version but with no contract defined on it so we simply write on it the dates
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

    def _get_contracts(
        self, date_start=None, date_end=None, use_latest_version=True, domain=None
    ):
        """
        Retrieve the contracts for employees within a specified date range and based
        on specified criteria, such as domain filtering and version selection.

        This method is used to collect and organize employee contracts based on their
        versions, date ranges, and other specified options. The resulting contracts are
        grouped by employee, and their selection logic depends on whether the latest
        version should be used or not. It supports flexibility in contract retrieval by
        allowing optional filters for date range and domain.

        Args:
            date_start (Optional[datetime.date]): The start date to filter the contracts
                by. If provided, only contract versions <= this date are considered
                based on the selection logic.
            date_end (Optional[datetime.date]): The end date to filter the contracts by.
                Only contract versions within the range will be retrieved. Defaults to
                None if not specified.
            domain (Optional[dict]): A dictionary representing additional filters or
                constraints to apply to the contract versions retrieved. Defaults to
                None.
            use_latest_version (bool): Indicates whether to retrieve the version
            effective at the end of the contract (or before the date_end) for each employee (True) or
            at the start of the contract (before the date_start) (False). Defaults to True.

        Returns:
            collections.defaultdict: A dictionary mapping each employee's identifier
            (employee.id) to a set of their corresponding contracts. Each set contains
            version records retrieved and filtered based on the specified criteria.
        """
        contract_versions_by_employee = self._get_contract_versions(
            date_start, date_end, domain
        )
        contracts_by_employee = defaultdict(lambda: self.env["hr.version"])
        # NOTE: the ``use_latest_version=False`` path is unimplemented and returns
        # an empty result -- pinned as such by test_hr_contract_versions, which
        # asserts the empty dict rather than a value. No production caller passes
        # it, and the intended "version effective at the contract start"
        # semantics are under-specified, so implementing it needs product
        # clarification. Returning early states that here instead of leaving it
        # to be inferred from two conditionals nobody reaches.
        if not use_latest_version:
            return contracts_by_employee
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
        """
        Retrieves contract versions for employees within the specified date range and
        domain. The function constructs a dynamic domain to filter contracts based on
        the provided arguments and retrieves grouped results. The grouping ensures
        organization by employee and date, and the results are stored in a structured
        format for ease of use.

        Args:
            date_start (datetime.date | None): The start date for filtering contracts.
            date_end (datetime.date | None): The end date for filtering contracts.
            domain (list | None): Additional domain constraints for filtering.

        Returns:
            dict: A dictionary where keys are employee IDs and values are lists of
                  contract version records organized by contract date start and date
                  range.
        """
        version_domain = Domain("contract_date_start", "!=", False)
        if self.ids:
            version_domain &= Domain("employee_id", "in", self.ids)
        elif not any(self._ids):  # onchange
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
        """
        Return a list of intervals (date_from, date_to) where the employee is in contract.
        For a permanent contract, the interval is (date_from, False).
        """
        self.ensure_one()
        return self.env["hr.version"]._read_group(
            [("employee_id", "=", self.id), ("contract_date_start", "!=", False)],
            ["contract_date_start:day", "contract_date_end:day"],
        )

    def _get_contract_dates(self, date):
        """
        Return a tuple (date_from, date_to) of the contract at the date given.
        (False, False) if the employee is not in contract at that date.
        """
        self.ensure_one()
        contains = self.env["hr.version"]._period_contains
        for date_from, date_to in self._get_all_contract_dates():
            if contains(date_from, date_to, date):
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
        # Answer with a domain on the underlying column instead of resolving
        # every newly-hired employee and inlining their ids: that put the whole
        # set into an IN list and made the cost of the filter proportional to the
        # headcount. The negative branch must also admit rows where the field is
        # NULL -- the compute calls those "not newly hired", and a bare
        # ``<= threshold`` would drop them (SQL NULL comparisons are never true).
        new_hire_field = self._get_new_hire_field()
        threshold = fields.Datetime.now() - timedelta(days=90)
        if operator == "in":
            return Domain(new_hire_field, ">", threshold)
        return Domain(new_hire_field, "<=", threshold) | Domain(
            new_hire_field, "=", False
        )

    @api.model
    def _get_valid_employee_for_user(self):
        """The employee of the current user, preferring their active company.

        Single source of truth for hr.version and hr.employee.public, which each
        carried a verbatim copy.
        """
        user = self.env.user
        # retrieve the employee of the current active company for the user
        employee = user.employee_id
        if not employee:
            # search for all employees as superadmin to not get blocked by multi-company rules
            user_employees = self.sudo().search([("user_id", "=", user.id)])
            # the default company employee is most likely the correct one, but fallback to the first if not available
            employee = (
                user_employees.filtered(lambda r: r.company_id == user.company_id)
                or user_employees[:1]
            )
        return employee

    def _create_work_contacts(self):
        if any(employee.work_contact_id for employee in self):
            raise UserError(self.env._("Some employee already have a work contact"))
        work_contacts = self.env["res.partner"].create(
            [
                {
                    "email": employee.work_email,
                    "phone": employee.work_phone,
                    "name": employee.name,
                    "image_1920": employee.image_1920,
                    "company_id": employee.company_id.id,
                }
                for employee in self
            ]
        )
        for employee, work_contact in zip(self, work_contacts, strict=True):
            employee.work_contact_id = work_contact

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

    @api.depends("work_contact_id", "work_contact_id.phone", "work_contact_id.email")
    def _compute_work_contact_details(self):
        for employee in self:
            if employee.work_contact_id:
                if len(employee.work_contact_id.employee_ids) <= 1:
                    employee.work_phone = employee.work_contact_id.phone
                    employee.work_email = employee.work_contact_id.email

    def _inverse_work_contact_details(self):
        employees_without_work_contact = self.env["hr.employee"]
        for employee in self:
            if not employee.work_contact_id:
                employees_without_work_contact += employee
            elif len(employee.work_contact_id.employee_ids) <= 1:
                employee.work_contact_id.sudo().write(
                    {
                        "email": employee.work_email,
                        "phone": employee.work_phone,
                    }
                )
        if employees_without_work_contact:
            employees_without_work_contact.sudo()._create_work_contacts()

    @api.model
    def _get_employee_working_now(self):
        """Ids of the employees their own schedule says are working in the next hour.

        sudo: ``resource_calendar_id`` is a hr.version delegate and so
        hr_user-only; only the calendar is read from it.

        One pass groups by (timezone, calendar) instead of a ``filtered()`` per
        calendar nested in a loop per timezone, and every group is measured
        against ONE instant -- ``fields.Datetime.now()`` used to be re-read
        inside the inner loop, so groups were compared against different "now"s.
        """
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
                # Fully flexible: no calendar, no attendance lines.
                # ``_work_intervals_batch`` RAISES on an empty calendar rather
                # than answering empty -- the loop this replaced never reached
                # that case because ``mapped("resource_calendar_id")`` drops the
                # empty value, so such employees were simply never reported as
                # working. Same outcome, stated instead of implied.
                continue
            zone = timezone(tz)
            work_intervals = calendar._work_intervals_batch(
                start_dt.astimezone(zone), stop_dt.astimezone(zone)
            )[False]
            if work_intervals._items:
                working_now += employees.ids
        return working_now

    @api.depends("user_id.im_status", "active")
    def _compute_hr_presence_state(self):
        """
        This method is overritten in several other modules which add additional
        presence criterions. e.g. hr_attendance, hr_holidays
        """
        # sudo: res.users - can access presence of accessible user.
        # Only employees whose company uses login-based presence control consult
        # ``working_now_list`` below, so restrict the (expensive) schedule
        # computation to them instead of running it for the whole recordset.
        employee_to_check_working = self.filtered(
            lambda e: (
                e.company_id.sudo().hr_presence_control_login
                and (e.user_id.sudo().presence_ids.status or "offline") == "offline"
            )
        )
        working_now_list = employee_to_check_working._get_employee_working_now()
        for employee in self:
            state = "out_of_working_hour"
            if employee.company_id.sudo().hr_presence_control_login:
                # sudo: res.users - can access presence of accessible user
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
    def _compute_last_activity(self):
        for employee in self:
            tz = employee.tz
            # sudo: res.users - can access presence of accessible user
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

    @api.depends("name", "user_id.avatar_1920", "image_1920")
    def _compute_avatar_1920(self):
        super()._compute_avatar_1920()

    @api.depends("name", "user_id.avatar_1024", "image_1024")
    def _compute_avatar_1024(self):
        super()._compute_avatar_1024()

    @api.depends("name", "user_id.avatar_512", "image_512")
    def _compute_avatar_512(self):
        super()._compute_avatar_512()

    @api.depends("name", "user_id.avatar_256", "image_256")
    def _compute_avatar_256(self):
        super()._compute_avatar_256()

    @api.depends("name", "user_id.avatar_128", "image_128")
    def _compute_avatar_128(self):
        super()._compute_avatar_128()

    def _update_avatar(self, avatar_field, image_field):
        employee_wo_user_and_image = self.env["hr.employee"]
        for employee in self:
            if not employee.user_id and not employee._origin[image_field]:
                employee_wo_user_and_image += employee
                continue
            avatar = employee._origin[image_field]
            if not avatar and employee.user_id:
                avatar = employee.user_id.sudo()[avatar_field]
            employee[avatar_field] = avatar
        super(HrEmployee, employee_wo_user_and_image)._update_avatar(
            avatar_field, image_field
        )

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
        return ["user_id", "work_contact_id"]

    @api.depends(lambda self: self._get_partner_count_depends())
    def _compute_related_partners_count(self):
        for employee in self:
            employee.related_partners_count = len(employee._get_related_partners())

    def _get_related_partners(self):
        return self.work_contact_id | self.user_id.partner_id

    def action_related_contacts(self):
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
        else:
            action["res_id"] = related_partners.id
        return action

    def action_create_user(self):
        self.ensure_one()
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
                "default_partner_id": self.work_contact_id.id,
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

    def _get_user_creation_notification(self, message, message_type, next_action):
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

    def _classify_for_user_creation(self):
        """Split ``self`` into what can become a user and what cannot.

        Returns ``(create_vals, blocked)``, ``blocked`` mapping a reason to the
        employee names it holds.
        """
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
        # Both columns the search matched must land in the set: on
        # ``email_normalized`` alone, a user whose *login* is this work email
        # under a different address slipped through to a raw UniqueViolation.
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
            # Normalised once and reused: this was computed three times per
            # employee, twice through ``tools.email_normalize`` and once through
            # the module-level import of the same function.
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
                    "partner_id": employee.work_contact_id.id,
                }
            )
        return create_vals, blocked

    def action_create_users(self):
        create_vals, blocked = self._classify_for_user_creation()

        next_action = {"type": "ir.actions.act_window_close"}
        if create_vals:
            self.env["res.users"].create(create_vals)
            next_action = self._get_user_creation_notification(
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

        # Each notification wraps the previous one, so this replaces four
        # near-identical ``if bucket:`` blocks with the same chain, in the same
        # order.
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
                next_action = self._get_user_creation_notification(
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

    @api.model
    def search_fetch(self, domain, field_names=None, offset=0, limit=None, order=None):
        if self.browse().has_access("read"):
            return super().search_fetch(domain, field_names, offset, limit, order)

        # HACK: retrieve publicly available values from hr.employee.public and
        # copy them to the cache of self; non-public data will be missing from
        # cache, and interpreted as an access error
        if field_names is None:
            field_names = [field.name for field in self._determine_fields_to_fetch()]
        field_names = [
            f_name for f_name in field_names if f_name != "current_version_id"
        ]
        self._check_private_fields(field_names)
        self.flush_model(field_names)
        public = self.env["hr.employee.public"].search_fetch(
            domain, field_names, offset, limit, order
        )
        employees = self.browse(public._ids)
        employees._copy_cache_from(public, field_names)
        return employees

    def fetch(self, field_names=None):
        if self.browse().has_access("read"):
            return super().fetch(field_names)

        # HACK: retrieve publicly available values from hr.employee.public and
        # copy them to the cache of self; non-public data will be missing from
        # cache, and interpreted as an access error
        if field_names is None:
            field_names = [field.name for field in self._determine_fields_to_fetch()]
        field_names = [
            f_name for f_name in field_names if f_name != "current_version_id"
        ]
        self._check_private_fields(field_names)
        self.flush_recordset(field_names)
        public = self.env["hr.employee.public"].browse(self._ids)
        public.fetch(field_names)
        # make sure all related fields from employee are in cache
        for field_name in field_names:
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
        self._copy_cache_from(public, field_names)
        return None

    def _check_access(self, operation):
        # This method override provides read access to 'hr.employee' in some
        # situations, like setting a many2many field to comodel 'hr.employee'.
        # Since Odoo 19, one must have read access to the comodel to modify the
        # relation.
        if (
            operation == "read"
            and self.env.context.get("_allow_read_hr_employee")
            is _ALLOW_READ_HR_EMPLOYEE
        ):
            return None

        return super()._check_access(operation)

    def _check_private_fields(self, field_names):
        """Check whether ``field_names`` contain private fields."""
        public_fields = self.env["hr.employee.public"]._fields
        private_fields = [fname for fname in field_names if fname not in public_fields]
        if private_fields:
            raise AccessError(
                self.env._(
                    "The fields “%s”, which you are trying to read, are not available for employee public profiles.",
                    ",".join(private_fields),
                )
            )

    def _copy_cache_from(self, public, field_names):
        # HACK: retrieve publicly available values from hr.employee.public and
        # copy them to the cache of self; non-public data will be missing from
        # cache, and interpreted as an access error
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

        # Anchor the whole run on a single "today" so every window is computed
        # against the same date, and group the companies by notice period: the
        # window is a function of the period, not of the company, so a cluster
        # that shares one setting costs one query instead of one per company.
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

        # A WINDOW, not an exact day. Matching ``= today + notice_period`` meant a
        # day the cron did not run -- server down, cron disabled, a database
        # restored from a backup, an upgrade window -- lost that expiry's
        # notification for good, because the next run's date no longer matched.
        # The window is safe precisely because ``_schedule_expiry_activity`` is
        # idempotent: it notifies on the first run inside the window and does
        # nothing on every later one.
        for notice_period, period_companies in companies_by_contract_period.items():
            employees_contract_expiring += self.env["hr.employee"].search(
                [
                    ("company_id", "in", period_companies.ids),
                    ("contract_date_start", "!=", False),
                    ("contract_date_start", "<", today),
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
        """Schedule an expiry reminder, at most once per (employee, deadline, summary).

        The cron runs daily and matches on an exact date, but nothing stopped it
        from running twice in the same day (a manual trigger, an ir.cron retry,
        a second worker, a ``--stop-after-init`` boot): every run appended
        another identical activity. Idempotence is asserted here rather than
        through a per-reason boolean flag on the employee, so both reasons are
        guarded by one mechanism.
        """
        self.ensure_one()
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
        # returning public employee data would cause a traceback when building
        # the private employee xml view
        raise RedirectWarning(
            message=self.env._(
                """You are not allowed to access "Employee" (hr.employee) records.
We can redirect you to the public employee list."""
            ),
            action=self.env.ref("hr.hr_employee_public_action").id,
            button_text=self.env._("Employees profile"),
        )

    @api.model
    def _search(
        self, domain, offset=0, limit=None, order=None, *, bypass_access=False, **kwargs
    ):
        """
        We override the _search because it is the method that checks the access rights
        This is correct to override the _search. That way we enforce the fact that calling
        search on an hr.employee returns a hr.employee recordset, even if you don't have access
        to this model, as the result of _search (the ids of the public employees) is to be
        browsed on the hr.employee model. This can be trusted as the ids of the public
        employees exactly match the ids of the related hr.employee.
        """
        if self.browse().has_access("read") or bypass_access:
            return super()._search(
                domain, offset, limit, order, bypass_access=bypass_access, **kwargs
            )
        domain = Domain(domain)
        # HACK Some fields are inherited from the `current_version_id` and may have been already
        # optimized, showing current_version_id in the domain, but public employee does not have
        # that field and may have fields directly on the model, just change the condition to `id` in
        # that case.
        domain = domain.map_conditions(
            lambda cond: (
                Domain("id", cond.operator, cond.value)
                if cond.field_expr == "current_version_id"
                else cond
            )
        )
        try:
            ids = self.env["hr.employee.public"]._search(
                domain, offset, limit, order, **kwargs
            )
        except (ValueError, RuntimeError) as e:
            # A RuntimeError is raised when the domain references a field that
            # resolves onto another model (e.g. an HR-only field related to
            # ``version_id``, optimized for hr.version) which the public model
            # cannot query: for a non-HR user that is an access violation, not an
            # internal error.
            raise AccessError(
                self.env._("You do not have access to this document.")
            ) from e
        # the result is expected from this table, so we should link tables
        return super(HrEmployee, self.sudo())._search([("id", "in", ids)], order=order)

    def _load_demo_data(self):
        dep_rd = self.env.ref("hr.dep_rd", raise_if_not_found=False)
        action_reload = {
            "type": "ir.actions.client",
            "tag": "reload",
        }
        if dep_rd:
            return action_reload
        convert.convert_file(
            env=self.sudo().env,
            module="hr",
            filename="data/scenarios/hr_scenario.xml",
            idref=None,
            mode="init",
        )
        if "resume_line_ids" in self:
            convert.convert_file(
                env=self.env,
                module="hr_skills",
                filename="data/scenarios/hr_skills_scenario.xml",
                idref=None,
                mode="init",
            )
        return action_reload

    def get_formview_id(self, access_uid=None):
        """Override this method in order to redirect many2one towards the right model depending on access_uid"""
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid).sudo()

        if user.has_group("hr.group_hr_user"):
            return super().get_formview_id(access_uid=access_uid)
        # Hardcode the form view for public employee
        return self.env.ref("hr.hr_employee_public_view_form").id

    def get_formview_action(self, access_uid=None):
        """Override this method in order to redirect many2one towards the right model depending on access_uid"""
        res = super().get_formview_action(access_uid=access_uid)
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid).sudo()

        if not user.has_group("hr.group_hr_user"):
            res["res_model"] = "hr.employee.public"

        return res

    @api.constrains("pin")
    def _verify_pin(self):
        for employee in self:
            if employee.pin and not employee.pin.isdigit():
                raise ValidationError(
                    self.env._("The PIN must be a sequence of digits.")
                )

    @api.constrains("barcode")
    def _verify_barcode(self):
        for employee in self:
            if employee.barcode:
                if not (
                    re.match(r"^[A-Za-z0-9]+$", employee.barcode)
                    and len(employee.barcode) <= 18
                ):
                    raise ValidationError(
                        self.env._(
                            "The Badge ID must be alphanumeric without any accents and no longer than 18 characters."
                        )
                    )

    @api.onchange("user_id")
    def _onchange_user(self):
        self.update(self._sync_user(self.user_id, (bool(self.image_1920))))
        if not self.name:
            self.name = self.user_id.name

    @api.onchange("resource_calendar_id")
    def _onchange_timezone(self):
        if self.resource_calendar_id and not self.tz:
            self.tz = self.resource_calendar_id.tz

    def _remove_work_contact_id(self, user, employee_company=None):
        """Remove work_contact_id for previous employee if the user is assigned to a new employee"""
        if not user:
            return
        # ``self`` is the recordset being written and may hold several
        # employees across several companies, so the target companies are
        # collected instead of read as a singleton (``self.company_id.id``
        # raised "Expected singleton" on any multi-company write). ``create``
        # calls this on the empty recordset, hence the env.company fallback --
        # without it the comparison below was against False and the stale work
        # contact was never cleared.
        if employee_company:
            companies = {employee_company}
        else:
            companies = set(self.mapped("company_id").ids) or {self.env.company.id}
        # For employees with a user_id, the constraint (user can't be linked to multiple employees) is triggered
        old_partner_employee_ids = user.partner_id.employee_ids.filtered(
            lambda e: not e.user_id and e.company_id.id in companies and e not in self
        )
        old_partner_employee_ids.work_contact_id = None

    def _sync_user(self, user, employee_has_image=False):
        vals = {"user_id": user.id}
        if user:
            vals["work_contact_id"] = user.partner_id.id
        # else: keep whatever work contact each employee already has. Reading
        # ``self.work_contact_id`` here to write it back was a no-op on a
        # singleton and raised "Expected singleton" for any multi-record write
        # (``employees.write({"user_id": False})``).
        if not employee_has_image:
            vals["image_1920"] = user.image_1920
        if user.tz:
            vals["tz"] = user.tz
        return vals

    def _prepare_resource_values(self, vals, tz):
        resource_vals = super()._prepare_resource_values(vals, tz)
        vals.pop("name", None)  # Already considered by super call but not popped
        # We need to pop it to avoid useless resource update (& write) call
        # on every newly created resource (with the correct name already)
        user_id = vals.pop("user_id", None)
        if user_id:
            resource_vals["user_id"] = user_id
        active_status = vals.get("active")
        if active_status is not None:
            resource_vals["active"] = active_status
        return resource_vals

    @api.model
    def new(self, values=None, origin=None, ref=None):
        if not values:
            values = {}
        new_vals, version_vals = self._split_version_vals(values)

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

    @api.model_create_multi
    def create(self, vals_list):
        vals_per_company = defaultdict(list)
        for idx, vals in enumerate(vals_list):
            if vals.get("user_id"):
                user = self.env["res.users"].browse(vals["user_id"])
                vals.update(self._sync_user(user, bool(vals.get("image_1920"))))
                vals["name"] = vals.get("name", user.name)
                self._remove_work_contact_id(user, vals.get("company_id"))
            # Having one create per company is necessary to pass the company in the context to correctly set it in
            # the underlying version created by the framework. Group by a normalized
            # company *id* so an explicit ``company_id`` and the ``env.company``
            # fallback for the same company land in the same batch (a record key and
            # an int key would otherwise split them).
            vals_per_company[vals.get("company_id") or self.env.company.id].append(
                (idx, vals)
            )
        index_per_employee = {}
        employees = self.env["hr.employee"]
        for company, company_vals_list in vals_per_company.items():
            idxs, company_vals_list = zip(*company_vals_list, strict=True)
            new_employees = super(HrEmployee, self.with_company(company)).create(
                company_vals_list
            )
            index_per_employee.update(dict(zip(new_employees, idxs, strict=True)))
            employees |= new_employees
        # As we do a custom batch by company, we must reorder the records to respect the original order.
        employees = employees.sorted(key=lambda employee: index_per_employee[employee])
        # Sudo in case HR officer doesn't have the Contact Creation group
        employees.filtered(
            lambda e: not e.work_contact_id
        ).sudo()._create_work_contacts()
        if self.env.context.get("salary_simulation"):
            return employees
        # creating 'svg/xml' attachments requires specific rights -- one check
        # for the batch, not one per employee
        may_write_views = self.env["ir.ui.view"].sudo(False).has_access("write")
        if may_write_views:
            for employee_sudo in employees.sudo().filtered(lambda e: not e.image_1920):
                employee_sudo.image_1920 = employee_sudo._prepare_avatar_svg()
                employee_sudo.work_contact_id.image_1920 = employee_sudo.image_1920
        employee_departments = employees.department_id
        if employee_departments:
            self.env["discuss.channel"].sudo().search(
                [("subscription_department_ids", "in", employee_departments.ids)]
            )._subscribe_users_automatically()
        onboarding_notes_bodies = {}
        hr_root_menu = self.env.ref("hr.menu_hr_root")
        for employee in employees:
            # Launch onboarding plans
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

    def write(self, vals):
        if "work_contact_id" in vals:
            self.message_unsubscribe(self.work_contact_id.ids)
        user_to_sync = None
        if "user_id" in vals:
            user_to_sync = self.env["res.users"].browse(vals["user_id"])
            # Avatar decided per employee below: ``_sync_user``'s single flag was
            # ``all(emp.image_1920 for emp in self)``, so one imageless employee
            # wiped every other image in the batch (reachable from
            # hr.view_employee_tree, which is multi_edit and exposes user_id).
            vals.update(self._sync_user(user_to_sync, employee_has_image=True))
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
            # When added to a department or changing user, subscribe to the channels auto-subscribed by department
            # Every written employee's department counts: the fallback used to
            # read ``self[:1].department_id``, so a batch spanning departments
            # subscribed only the first one's channels.
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
        # Only one write call for all the fields from hr.version
        new_vals, version_vals = self._split_version_vals(vals)
        res = super().write(new_vals)
        if "work_contact_id" in vals:
            self._repoint_bank_accounts(vals["work_contact_id"])
        if user_to_sync and user_to_sync.image_1920:
            # Seed only the employees with no image; never clear one.
            employees_without_image = self.filtered(lambda e: not e.image_1920)
            if employees_without_image:
                employees_without_image.image_1920 = user_to_sync.image_1920
        if version_vals:
            version_vals["last_modified_date"] = fields.Datetime.now()
            version_vals["last_modified_uid"] = self.env.uid
            self.version_id.write(version_vals)

            for employee in self:
                employee._track_set_log_message(
                    Markup("<b>Modified on the Version '%s'</b>")
                    % employee.version_id.display_name
                )
        if res and "resource_calendar_id" in vals:
            self._propagate_calendar_to_resources()
        return res

    def _repoint_bank_accounts(self, work_contact_id):
        """Move the employee's bank accounts onto their new work contact.

        Trust is dropped on the way: an account that changes owner must be
        re-approved, never carried over. Batched by target so a set of employees
        costs two writes rather than two per account.
        """
        accounts_sudo = (
            self.env["res.partner.bank"].sudo().browse(self.bank_account_ids.ids)
        )
        to_move = accounts_sudo.filtered(
            lambda account: account.partner_id.id != work_contact_id
        )
        if not to_move:
            return
        trusted = to_move.filtered("allow_out_payment")
        if trusted:
            trusted.allow_out_payment = False
        if work_contact_id:
            to_move.partner_id = work_contact_id

    def _propagate_calendar_to_resources(self):
        """Push a written working schedule onto resource.resource.

        Only for employees whose written version IS the current one: a schedule
        set on a past or future version must not move the resource's calendar,
        which has no notion of versions.
        """
        resources_per_calendar_id = defaultdict(lambda: self.env["resource.resource"])
        for employee in self:
            if employee.version_id == employee.current_version_id:
                resources_per_calendar_id[employee.resource_calendar_id.id] += (
                    employee.resource_id
                )
        for calendar_id, resources in resources_per_calendar_id.items():
            resources.write({"calendar_id": calendar_id})

    def unlink(self):
        resources = self.mapped("resource_id")
        result = super().unlink()
        resources.unlink()
        return result

    def _get_employee_m2o_to_empty_on_archived_employees(self):
        return ["parent_id", "coach_id"]

    def _get_user_m2o_to_empty_on_archived_employees(self):
        return []

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
            # Empty links to this employees (example: manager, coach, time off responsible, ...)
            employee_fields_to_empty = (
                self._get_employee_m2o_to_empty_on_archived_employees()
            )
            user_fields_to_empty = self._get_user_m2o_to_empty_on_archived_employees()
            employee_domain = Domain.OR(
                Domain(field, "in", archived_employees.ids)
                for field in employee_fields_to_empty
            )
            user_domain = Domain.OR(
                Domain(field, "in", archived_employees.user_id.ids)
                for field in user_fields_to_empty
            )
            employees = self.env["hr.employee"].search(employee_domain | user_domain)
            # Clear each back-reference in a single grouped write per field instead
            # of one write per (record, field) pair.
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
                    "context": {"active_id": self.id},
                    "views": [[False, "form"]],
                }
        return res

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

    # ---------------------------------------------------------
    # Business Methods
    # ---------------------------------------------------------

    def generate_random_barcode(self):
        # ``_barcode_uniq`` is a DB-level UNIQUE, so a collision used to surface
        # as a UniqueViolation rather than another draw. Probe each candidate
        # against that same unique index -- one index lookup, not a full read of
        # every badge in the table -- and remember what this call has already
        # handed out.
        # sudo + active_test=False: the constraint spans every employee, so a
        # badge taken by one this user cannot see is still taken.
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
        self.ensure_one()
        return (
            self.resource_calendar_id.tz
            or self.tz
            or self.company_id.resource_calendar_id.tz
            or "UTC"
        )

    def _get_tz_batch(self):
        # Finds the first valid timezone in his tz, his work hours tz,
        #  the company calendar tz or UTC
        # Returns a dict {employee_id: tz}
        return {emp.id: emp._get_tz() for emp in self}

    def _get_calendar_tz_batch(self, dt=None):
        """Return a mapping { employee id : employee's effective schedule's (at dt) timezone }

        ``dt`` is an instant; a naive value is read as UTC (hr_attendance's
        ``_get_day_start_and_day`` passes one). Which version -- hence which
        schedule -- is in force depends on the employee's OWN calendar date, so
        the instant must be *converted* into their zone with ``astimezone``.
        A bare ``dt.replace(tzinfo=...)`` cannot do that: it relabels the wall
        clock and leaves ``.date()`` equal to ``dt.date()`` for every zone, which
        silently made this whole per-timezone grouping a no-op and picked the
        UTC-date version for everyone.
        """
        employees_by_id = self.grouped("id")

        def timezones_at(employees, date_at=None):
            return {
                emp_id: calendar.sudo().tz or employees_by_id[emp_id].tz
                for emp_id, calendar in employees._get_calendars(date_at).items()
            }

        if not dt:
            return timezones_at(self)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        employee_timezones = {}
        # Resolve each group against ITS OWN local date, and only for its own
        # employees: the previous code passed the whole recordset on every
        # iteration, so each pass recomputed and overwrote every employee.
        for tz, employees in self.grouped(lambda emp: emp._get_tz()).items():
            employee_timezones |= timezones_at(
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
            if employee_versions_sudo:
                res[employee.id] = employee_versions_sudo[0].resource_calendar_id.sudo(
                    False
                )
        return res

    @staticmethod
    def _combine_tz(day, moment, tz):
        """Build an aware datetime at ``day``/``moment`` in the IANA zone ``tz``
        (naive if ``tz`` is falsy).

        Uses ``localize_standard`` — NEVER a bare ``.replace(tzinfo=tz)``. On the
        hour a zone repeats when DST ends, that wall time exists twice and a bare
        ``.replace`` silently takes ``fold=0``, the DST side, putting the instant
        an hour earlier than the standard side pytz's ``localize`` chose before
        the zoneinfo migration. ``time.min`` is not safe from this: Cuba,
        America/Havana and Atlantic/Azores all fold at midnight, so a period
        boundary for an employee in one of them would move by an hour once a year.
        """
        naive = datetime.combine(day, moment)
        return localize_standard(naive, tz) if tz else naive

    def _get_version_periods(self, start, stop, field=None, check_contract=False):
        # ``field`` is read off hr.version below, so it must be validated
        # against hr.version -- not against ``self`` (hr.employee). A field that
        # exists only on the employee (``barcode``, ``pin``, ...) passed the old
        # guard and then died on a raw KeyError, which is exactly the case this
        # message was written for.
        if field and field not in self.env["hr.version"]._fields:
            raise UserError(
                self.env._(
                    "This field %(field_name)s doesn't exist on this model (hr.version).",
                    field_name=field,
                )
            )
        version_periods_by_employee = defaultdict(list)
        if check_contract:
            versions = self._get_versions_with_contract_overlap_with_period(
                start.date(), stop.date()
            )
        else:
            # Compare the computed values, not a domain. date_start/date_end are
            # non-stored and their search methods are documented approximations
            # that resolve to contract_date_start/end (see hr_version.py), so a
            # version with no contract -- the ordinary case -- has
            # contract_date_start = False, matches nothing, and silently emptied
            # every period list here. hr_version's own note says not to rely on
            # those searches for exact effective-window queries; this is one.
            start_date, stop_date = start.date(), stop.date()
            versions = self.version_ids.filtered(
                lambda version: (
                    version.date_start
                    and version.date_start <= stop_date
                    and (not version.date_end or version.date_end >= start_date)
                )
            )
        for version in versions:
            # if employee is under fully flexible contract, use timezone of the employee
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
                    version[field] if field else version,
                )
            )
        return version_periods_by_employee

    def _get_calendar_periods(self, start, stop, check_contract=True):
        """
        :param datetime start: the start of the period
        :param datetime stop: the stop of the period
        """
        return self.sudo()._get_version_periods(
            start, stop, "resource_calendar_id", check_contract
        )

    @api.model
    def _get_all_versions_with_contract_overlap_with_period(self, date_from, date_to):
        """
        Returns the versions of all employees between date_from and date_to
        that have at least 1 day in contract during that period
        """
        all_employees = self.search(
            ["|", ("active", "=", True), ("active", "=", False)]
        )
        return all_employees._get_versions_with_contract_overlap_with_period(
            date_from, date_to
        )

    def _get_unusual_days(self, date_from, date_to=None):
        self.ensure_one()
        date_from_date = datetime.strptime(date_from, "%Y-%m-%d %H:%M:%S").date()
        # ``date_to`` is optional; fall back to a single-day window so neither the
        # per-version branch nor the no-version branch feeds ``None`` into
        # ``datetime.combine`` (which raises).
        date_to_date = (
            datetime.strptime(date_to, "%Y-%m-%d %H:%M:%S").date()
            if date_to
            else date_from_date
        )
        employee_versions = (
            self.env["hr.version"]
            .sudo()
            .search([("employee_id", "=", self.id)])
            .filtered(lambda v: v._is_overlapping_period(date_from_date, date_to_date))
        )
        if not employee_versions:
            # Checking the calendar directly allows to not grey out the leaves taken
            # by the employee or fallback to the company calendar
            return (
                self.resource_calendar_id or self.env.company.resource_calendar_id
            )._get_unusual_days(
                datetime.combine(date_from_date, time.min).replace(tzinfo=UTC),
                # date_to_date already falls back to date_from_date above.
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

    def _get_employee_tz(self):
        self.ensure_one()
        return timezone(self.tz) if self.tz else None

    def _get_fallback_calendar(self):
        self.ensure_one()
        return self.resource_calendar_id or self.company_id.resource_calendar_id

    def _iter_version_windows(self, start, stop, tz=None):
        """Yield ``(version, window_start, window_stop, calendar)`` per in-contract version.

        Each window is that version's effective span clamped to ``[start, stop]``.
        Three callers -- ``_employee_attendance_intervals``,
        ``_get_expected_attendances`` and ``_get_calendar_attendances`` -- each
        rebuilt this arithmetic, with slightly different bounds that were
        impossible to compare while they sat apart.
        """
        self.ensure_one()
        versions = self.sudo()._get_versions_with_contract_overlap_with_period(
            start.date(), stop.date()
        )
        for version in versions:
            window_start = self._combine_tz(version.date_start, time.min, tz)
            # Open-ended version: bound by the period end rather than building a
            # ``date.max`` datetime, which overflows in ``_combine_tz`` (tzinfo
            # attachment) for UTC-negative timezones.
            window_stop = (
                self._combine_tz(version.date_end, time.max, tz)
                if version.date_end
                else stop
            )
            calendar = (
                version.resource_calendar_id or version.company_id.resource_calendar_id
            )
            yield version, max(start, window_start), min(stop, window_stop), calendar

    def _employee_attendance_intervals(self, start, stop, lunch=False):
        self.ensure_one()
        if not lunch:
            return self._get_expected_attendances(start, stop)
        employee_tz = self._get_employee_tz()
        windows = list(self._iter_version_windows(start, stop, employee_tz))
        if not windows:
            return self._get_fallback_calendar()._attendance_intervals_batch(
                start, stop, self.resource_id, lunch=True
            )[self.resource_id.id]
        duration_data = Intervals()
        for _version, window_start, window_stop, calendar in windows:
            duration_data |= calendar._attendance_intervals_batch(
                window_start,
                window_stop,
                resources=self.resource_id,
                lunch=True,
            )[self.resource_id.id]
        return duration_data

    def _get_expected_attendances(self, date_from, date_to):
        self.ensure_one()
        employee_tz = self._get_employee_tz()
        windows = list(self._iter_version_windows(date_from, date_to, employee_tz))
        if not windows:
            # NOTE: this branch does NOT carry the ``time_type = leave`` clause
            # the per-version branch below passes, so the two paths subtract
            # different sets of resource.calendar.leaves. Preserved as shipped --
            # reconciling them changes computed attendance and wants product
            # input -- but they are not the same computation.
            return self._get_fallback_calendar()._work_intervals_batch(
                date_from,
                date_to,
                tz=employee_tz,
                resources=self.resource_id,
                compute_leaves=True,
                domain=[("company_id", "in", [False, self.company_id.id])],
            )[self.resource_id.id]
        duration_data = Intervals()
        for index, (version, window_start, window_stop, calendar) in enumerate(windows):
            if index == 0:
                # The earliest version in the period reaches back to its CONTRACT
                # start, so a contract that began before its first version's
                # effective date is not left uncovered. This used to be spelled
                # as ``version_start if version_prev < version_start else
                # contract_start`` with a ``version_prev`` that was assigned once
                # and never advanced -- so it read as "compare with the previous
                # version" while it only ever meant "is this the first one".
                window_start = max(
                    date_from,
                    self._combine_tz(
                        version.contract_date_start, time.min, employee_tz
                    ),
                )
            duration_data |= calendar._work_intervals_batch(
                window_start,
                window_stop,
                tz=employee_tz,
                resources=self.resource_id,
                compute_leaves=True,
                domain=[
                    ("company_id", "in", [False, self.company_id.id]),
                    ("time_type", "=", "leave"),
                ],
            )[self.resource_id.id]
        return duration_data

    def _get_calendar_attendances(self, date_from, date_to):
        self.ensure_one()
        employee_tz = self._get_employee_tz()
        windows = list(self._iter_version_windows(date_from, date_to, employee_tz))
        if not windows:
            return (
                self._get_fallback_calendar()
                .with_context(employee_timezone=employee_tz)
                .get_work_duration_data(
                    date_from,
                    date_to,
                    domain=[("company_id", "in", [False, self.company_id.id])],
                )
            )
        duration_data = {"days": 0, "hours": 0}
        for version, window_start, window_stop, calendar in windows:
            # NOTE: scoped to the VERSION's company, unlike the no-version branch
            # above and unlike _get_expected_attendances, which both use the
            # employee's. Preserved as shipped.
            version_duration_data = calendar.with_context(
                employee_timezone=employee_tz
            ).get_work_duration_data(
                window_start,
                window_stop,
                domain=[("company_id", "in", [False, version.company_id.id])],
            )
            duration_data["days"] += version_duration_data["days"]
            duration_data["hours"] += version_duration_data["hours"]
        return duration_data

    @api.model
    def get_import_templates(self):
        return [
            {
                "label": self.env._("Import Template for Employees"),
                "template": "/hr/static/xls/hr_employee.xls",
            }
        ]

    def _get_age(self, target_date=None):
        self.ensure_one()
        if target_date is None:
            target_date = fields.Date.context_today(self.env.user)
        return relativedelta(target_date, self.birthday).years if self.birthday else 0

    def _get_departure_date(self):
        # Primarily used in the archive wizard
        # to pick a good default for the departure date
        self.ensure_one()
        if self.date_end and self.date_end < fields.Date.today():
            return self.departure_date
        return False

    def _get_versions_with_contract_overlap_with_period(self, date_from, date_to):
        """
        Returns the versions of the employee between date_from and date_to
        that have at least 1 day in contract during that period
        """
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

    # ---------------------------------------------------------
    # Messaging
    # ---------------------------------------------------------

    def _phone_get_number_fields(self):
        return ["mobile_phone"]

    def action_open_versions(self):
        self.ensure_one()
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
            # job_title is not a field of hr.employee.public, but it is a field of hr.employee
            employee_fields.append("job_title")
        # HACK: fetch the employee fields from employees to retrieve hr.employee.public fields if no access to hr.employee
        if len(self) > 0:
            self.fetch(
                [
                    field.field_name if isinstance(field, Store.Attr) else field
                    for field in employee_fields
                ]
            )
        return employee_fields

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

    def get_accounts_with_fixed_allocations(self):
        self.ensure_one()
        distribution = self.salary_distribution or {}
        return self.bank_account_ids.filtered(
            lambda a: (
                not distribution.get(str(a.id), {}).get("amount_is_percentage", True)
            )
        )

    def get_bank_account_salary_allocation(self, account_id):
        ba_info = (self.salary_distribution or {}).get(str(account_id), {})
        # Default to percentage (True), consistent with the other getters and
        # _compute_salary_distribution, rather than None for a missing entry.
        return ba_info.get("amount", 0), ba_info.get("amount_is_percentage", True)

    def get_remaining_percentage(self):
        self.ensure_one()
        distribution = self.salary_distribution or {}
        allocated = 0.0

        for vals in distribution.values():
            if vals.get("amount_is_percentage"):
                allocated += vals.get("amount", 0.0)

        remaining = 100.0 - allocated
        return max(0.0, remaining)

    def action_open_allocation_wizard(self):
        self.ensure_one()
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

    def action_toggle_primary_bank_account_trust(self):
        self.ensure_one()
        current_val = self.primary_bank_account_id.allow_out_payment
        self.primary_bank_account_id.allow_out_payment = not current_val
