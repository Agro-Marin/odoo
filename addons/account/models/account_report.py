import ast
import re
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain

FIGURE_TYPE_SELECTION_VALUES = [
    ("monetary", "Monetary"),
    ("percentage", "Percentage"),
    ("integer", "Integer"),
    ("float", "Float"),
    ("date", "Date"),
    ("datetime", "Datetime"),
    ("boolean", "Boolean"),
    ("string", "String"),
]

DOMAIN_REGEX = re.compile(r"(-?sum)\((.*)\)")
CROSS_REPORT_REGEX = re.compile(r"^cross_report\((.+)\)$")

ACCOUNT_CODES_ENGINE_SPLIT_REGEX = re.compile(r"(?=[+-])")
ACCOUNT_CODES_ENGINE_TERM_REGEX = re.compile(
    r"^(?P<sign>[+-]?)"
    r"(?P<prefix>([A-Za-z\d.]*|tag\([\w.]+\))((?=\\)|(?<=[^CD])))"
    r"(\\\((?P<excluded_prefixes>([A-Za-z\d.]+,)*[A-Za-z\d.]*)\))?"
    r"(?P<balance_character>[DC]?)$"
)

NUMBER_REGEX = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
REPORT_LINE_CODE_REGEX = r"[+-]?[\s(]*[^().\s*/+\-]+\.[^().\s*/+\-]+"
OPERATOR_REGEX = r"[\s*/+\-]"
SUM_CHILDREN_FORMULA = "sum_children"
HARD_FORMULAS = (SUM_CHILDREN_FORMULA,)
AGGREGATION_ENGINE_FORMULA_REGEX = re.compile(
    f"{'|'.join(HARD_FORMULAS)}|"
    rf"[\s(]*(?:{NUMBER_REGEX}|{REPORT_LINE_CODE_REGEX})[\s)]*"
    rf"(?:{OPERATOR_REGEX}[\s(]*(?:{NUMBER_REGEX}|{REPORT_LINE_CODE_REGEX})[\s)]*)*"
)
AGGREGATION_TERM_SPLIT_REGEX = re.compile(r"[-+/*]")
AGGREGATION_NUMBER_TERM_REGEX = re.compile(rf"^{NUMBER_REGEX}$")
AGGREGATION_CODE_TERM_REGEX = re.compile(
    r"^(?P<line_code>[^.]+)\.(?P<expr_label>[^.]+)$"
)
IF_OTHER_EXPR_SUBFORMULA_REGEX = re.compile(
    r"if_other_expr_(above|below)\((?P<line_code>.+)[.](?P<expr_label>.+),.+\)"
)

AUDITABLE_ENGINES = frozenset(
    {"tax_tags", "domain", "account_codes", "external", "aggregation"}
)

REPORT_OPTION_FILTER_DEPENDS = ("root_report_id", "section_main_report_ids")


def report_option_filter_field(field_type, field_name, string, default=False, **kwargs):
    # One compute per field, deliberately: fields sharing a compute form one group in
    # registry.field_computed, and create() protects the whole group as soon as any one
    # member appears in vals -- so a report whose XML sets a single filter would lose the
    # inherited values of all the others.
    return field_type(
        string=string,
        compute=lambda records: records._compute_report_option_filter(
            field_name, default
        ),
        precompute=True,
        readonly=False,
        store=True,
        depends=list(REPORT_OPTION_FILTER_DEPENDS),
        **kwargs,
    )


class AccountReport(models.Model):
    _name = "account.report"
    _description = "Accounting Report"
    _order = "sequence, id"

    name = fields.Char(string="Name", required=True, translate=True)
    sequence = fields.Integer(string="Sequence")
    active = fields.Boolean(string="Active", default=True)
    line_ids = fields.One2many(
        string="Lines", comodel_name="account.report.line", inverse_name="report_id"
    )
    column_ids = fields.One2many(
        string="Columns", comodel_name="account.report.column", inverse_name="report_id"
    )
    root_report_id = fields.Many2one(
        string="Root Report",
        comodel_name="account.report",
        index="btree_not_null",
        help="The report this report is a variant of.",
    )
    variant_report_ids = fields.One2many(
        string="Variants", comodel_name="account.report", inverse_name="root_report_id"
    )
    section_report_ids = fields.Many2many(
        string="Sections",
        comodel_name="account.report",
        relation="account_report_section_rel",
        column1="main_report_id",
        column2="sub_report_id",
    )
    section_main_report_ids = fields.Many2many(
        string="Section Of",
        comodel_name="account.report",
        relation="account_report_section_rel",
        column1="sub_report_id",
        column2="main_report_id",
    )
    use_sections = fields.Boolean(
        string="Composite Report",
        compute="_compute_use_sections",
        store=True,
        readonly=False,
        help="Create a structured report with multiple sections for convenient navigation and simultaneous printing.",
    )
    chart_template = fields.Selection(
        string="Chart of Accounts",
        selection=lambda self: self.env[
            "account.chart.template"
        ]._select_chart_template(),
    )
    country_id = fields.Many2one(string="Country", comodel_name="res.country")
    only_tax_exigible = report_option_filter_field(
        fields.Boolean, "only_tax_exigible", "Only Tax Exigible Lines"
    )
    availability_condition = fields.Selection(
        string="Availability",
        selection=[
            ("country", "Country Matches"),
            ("coa", "Chart of Accounts Matches"),
            ("always", "Always"),
        ],
        compute="_compute_availability_condition",
        readonly=False,
        store=True,
    )
    load_more_limit = fields.Integer(string="Load More Limit")
    search_bar = fields.Boolean(string="Search Bar")
    prefix_groups_threshold = fields.Integer(
        string="Prefix Groups Threshold", default=4000
    )
    integer_rounding = fields.Selection(
        string="Integer Rounding",
        selection=[("HALF-UP", "Nearest"), ("UP", "Up"), ("DOWN", "Down")],
    )
    allow_foreign_vat = report_option_filter_field(
        fields.Boolean, "allow_foreign_vat", "Allow Foreign VAT"
    )

    default_opening_date_filter = report_option_filter_field(
        fields.Selection,
        "default_opening_date_filter",
        "Default Opening",
        default="previous_month",
        selection=[
            ("this_year", "This Year"),
            ("this_quarter", "This Quarter"),
            ("this_month", "This Month"),
            ("today", "Today"),
            ("previous_month", "Last Month"),
            ("previous_quarter", "Last Quarter"),
            ("previous_year", "Last Year"),
            ("this_return_period", "This Return Period"),
            ("previous_return_period", "Last Return Period"),
        ],
    )

    currency_translation = report_option_filter_field(
        fields.Selection,
        "currency_translation",
        "Currency Translation",
        default="cta",
        selection=[
            ("current", "Use the most recent rate at the date of the report"),
            ("cta", "Use CTA"),
        ],
    )

    filter_multi_company = report_option_filter_field(
        fields.Selection,
        "filter_multi_company",
        "Multi-Company",
        default="selector",
        selection=[
            ("selector", "Use Company Selector"),
            ("tax_units", "Use Tax Units"),
        ],
    )
    filter_date_range = report_option_filter_field(
        fields.Boolean, "filter_date_range", "Date Range", default=True
    )
    filter_show_draft = report_option_filter_field(
        fields.Boolean, "filter_show_draft", "Draft Entries", default=True
    )
    filter_unreconciled = report_option_filter_field(
        fields.Boolean, "filter_unreconciled", "Unreconciled Entries", default=False
    )
    filter_unfold_all = report_option_filter_field(
        fields.Boolean, "filter_unfold_all", "Unfold All"
    )
    filter_hide_0_lines = report_option_filter_field(
        fields.Selection,
        "filter_hide_0_lines",
        "Hide lines at 0",
        default="optional",
        selection=[
            ("by_default", "Enabled by Default"),
            ("optional", "Optional"),
            ("never", "Never"),
        ],
    )
    filter_period_comparison = report_option_filter_field(
        fields.Boolean, "filter_period_comparison", "Period Comparison", default=True
    )
    filter_growth_comparison = report_option_filter_field(
        fields.Boolean, "filter_growth_comparison", "Growth Comparison", default=True
    )
    filter_journals = report_option_filter_field(
        fields.Boolean, "filter_journals", "Journals"
    )
    filter_analytic = report_option_filter_field(
        fields.Boolean, "filter_analytic", "Analytic Filter"
    )
    filter_hierarchy = report_option_filter_field(
        fields.Selection,
        "filter_hierarchy",
        "Account Groups",
        default="optional",
        selection=[
            ("by_default", "Enabled by Default"),
            ("optional", "Optional"),
            ("never", "Never"),
        ],
    )
    filter_account_type = report_option_filter_field(
        fields.Selection,
        "filter_account_type",
        "Account Types",
        default="disabled",
        selection=[
            ("both", "Payable and receivable"),
            ("payable", "Payable"),
            ("receivable", "Receivable"),
            ("disabled", "Disabled"),
        ],
    )
    filter_partner = report_option_filter_field(
        fields.Boolean, "filter_partner", "Partners"
    )
    filter_aml_ir_filters = report_option_filter_field(
        fields.Boolean,
        "filter_aml_ir_filters",
        "Favorite Filters",
        help="If activated, user-defined filters on journal items can be selected on this report",
    )

    filter_budgets = report_option_filter_field(
        fields.Boolean, "filter_budgets", "Budgets"
    )

    def _compute_report_option_filter(self, field_name, default_value=False):
        accessible_report_ids = self._get_accessible_report_ids()
        for report in self.sorted(lambda x: not x.section_report_ids):
            is_accessible = report.id in accessible_report_ids
            is_variant = bool(report.root_report_id)
            if (is_accessible or is_variant) and report.section_main_report_ids:
                continue
            if is_variant:
                source_report = report.root_report_id
            elif len(report.section_main_report_ids) == 1 and not is_accessible:
                source_report = report.section_main_report_ids
            else:
                source_report = None
            report[field_name] = (
                source_report[field_name]
                if source_report is not None
                else default_value
            )

    def _get_accessible_report_ids(self):
        candidate_ids = {report.id for report in self if isinstance(report.id, int)}
        if not candidate_ids:
            return set()
        contexts = (
            self.env["ir.actions.client"]
            .search([("tag", "=", "account_report")])
            .mapped("context")
        )
        return candidate_ids & {
            report_id
            for report_id in map(self._read_action_report_id, contexts)
            if report_id is not None
        }

    @staticmethod
    def _read_action_report_id(context):
        try:
            parsed_context = ast.literal_eval(context or "{}")
        except ValueError, SyntaxError, MemoryError, RecursionError:
            return None
        if not isinstance(parsed_context, dict):
            return None
        report_id = parsed_context.get("report_id")
        return report_id if isinstance(report_id, int) else None

    @api.depends("root_report_id", "country_id")
    def _compute_availability_condition(self):
        for report in self:
            if report.root_report_id and report.country_id:
                report.availability_condition = "country"
            elif not report.availability_condition:
                report.availability_condition = "always"

    @api.depends("section_report_ids")
    def _compute_use_sections(self):
        for report in self:
            report.use_sections = bool(report.section_report_ids)

    @api.constrains("root_report_id")
    def _check_root_report_id(self):
        for report in self:
            if report.root_report_id.root_report_id:
                raise ValidationError(
                    _(
                        "Only a report without a root report of its own can be selected as root report."
                    )
                )

    @api.constrains("line_ids")
    def _check_parent_sequence(self):
        previous_lines = self.env["account.report.line"]
        for line in self.line_ids.sorted("sequence"):
            if line.parent_id and line.parent_id not in previous_lines:
                raise ValidationError(
                    _(
                        'Line "%(line)s" defines line "%(parent_line)s" as its parent, but appears before it in the report. '
                        "The parent must always come first.",
                        line=line.name,
                        parent_line=line.parent_id.name,
                    )
                )
            previous_lines |= line

    @api.constrains("section_report_ids")
    def _check_section_report_ids(self):
        for record in self:
            if any(section.section_report_ids for section in record.section_report_ids):
                raise ValidationError(
                    _(
                        "The sections defined on a report cannot have sections themselves."
                    )
                )

    @api.constrains("availability_condition", "country_id")
    def _check_availability_condition(self):
        for record in self:
            if record.availability_condition == "country" and not record.country_id:
                raise ValidationError(
                    _(
                        "The Availability is set to 'Country Matches' but the field Country is not set."
                    )
                )

    @api.onchange("availability_condition")
    def _onchange_availability_condition(self):
        if self.availability_condition != "country":
            self.country_id = None

    def write(self, vals):
        if "country_id" in vals:
            self._move_tax_tags_to_country(vals["country_id"])
        return super().write(vals)

    def _move_tax_tags_to_country(self, country_id):
        moving_reports = self.filtered(lambda x: x.country_id.id != country_id)
        tax_tags_expressions = moving_reports.line_ids.expression_ids.filtered(
            lambda x: x.engine == "tax_tags"
        )
        if not tax_tags_expressions:
            return

        tag_model = self.env["account.account.tag"].with_context(
            active_test=False, lang="en_US"
        )
        source_tags = tax_tags_expressions._get_matching_tags()
        if not source_tags:
            return

        reports_by_tag = defaultdict(self.env["account.report"].browse)
        for expression in source_tags._get_related_tax_report_expressions():
            report = expression.report_line_id.report_id
            reports_by_tag[(expression.formula.lstrip("-"), report.country_id.id)] |= (
                report
            )

        destination_names = set(
            tag_model.search(
                [
                    ("applicability", "=", "taxes"),
                    ("country_id", "=", country_id),
                    ("name", "in", source_tags.mapped("name")),
                ]
            ).mapped("name")
        )

        tags_to_move = tag_model.browse()
        for tag in source_tags:
            # Moving a tag whose name already exists in the destination country would
            # violate account_account_tag_name_src_uniq; moving one that a report
            # staying behind still points at would take the tag away from that report.
            users = reports_by_tag[(tag.name, tag.country_id.id)]
            if tag.name not in destination_names and users <= moving_reports:
                tags_to_move += tag
        tags_to_move.write({"country_id": country_id})

        missing_names = (
            set(source_tags.mapped("name"))
            - destination_names
            - set(tags_to_move.mapped("name"))
        )
        expression_model = self.env["account.report.expression"]
        tag_model.create(
            [
                tag_vals
                for name in sorted(missing_names)
                for tag_vals in expression_model._get_tags_create_vals(name, country_id)
            ]
        )

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        return [
            dict(vals, name=report._get_copied_name())
            for report, vals in zip(self, vals_list, strict=True)
        ]

    def copy(self, default=None):
        new_reports = super().copy(default=default)
        for old_report, new_report in zip(self, new_reports, strict=True):
            code_mapping = old_report.line_ids._copy_hierarchy(new_report)

            for expression in new_report.line_ids.expression_ids:
                if expression.engine == "aggregation":
                    expression.formula = self._replace_codes_in_formula(
                        expression.formula, code_mapping
                    )
                    if expression.subformula:
                        expression.subformula = self._replace_codes_in_formula(
                            expression.subformula, code_mapping
                        )

            old_report.column_ids.copy({"report_id": new_report.id})
        return new_reports

    @staticmethod
    def _replace_codes_in_formula(formula, code_mapping):
        if not code_mapping:
            return formula
        alternatives = "|".join(
            re.escape(old_code)
            for old_code in sorted(code_mapping, key=len, reverse=True)
        )
        return re.sub(
            rf"(?<=\W)(?:{alternatives})(?=\W)",
            lambda match: code_mapping[match.group()],
            f" {formula} ",
        ).strip()

    @api.ondelete(at_uninstall=False)
    def _unlink_if_no_variant(self):
        if self.variant_report_ids:
            raise UserError(_("You can't delete a report that has variants."))
        # Same hook as the guard above on purpose. ondelete methods are collected
        # with inspect.getmembers, so they run in alphabetical order of their name:
        # a separate hook would destroy these lines before the guard refused the
        # delete. The lines have to go through the ORM because the database cascade
        # on report_id bypasses their own ondelete and leaves their tax tags behind.
        self.line_ids.unlink()

    def _get_copied_name(self):
        self.ensure_one()
        base_name = f"{self.name} {_('(copy)')}"
        taken = set(
            self.with_context(active_test=False)
            .search([("name", "=like", f"{base_name}%")])
            .mapped("name")
        )
        if base_name not in taken:
            return base_name
        counter = 2
        while f"{base_name} {counter}" in taken:
            counter += 1
        return f"{base_name} {counter}"

    @api.depends("name", "country_id")
    def _compute_display_name(self):
        for report in self:
            if report.name:
                report.display_name = report.name + (
                    f" ({report.country_id.code})" if report.country_id else ""
                )
            else:
                report.display_name = False


class AccountReportLine(models.Model):
    _name = "account.report.line"
    _description = "Accounting Report Line"
    _order = "sequence, id"

    name = fields.Char(string="Name", translate=True, required=True)
    expression_ids = fields.One2many(
        string="Expressions",
        comodel_name="account.report.expression",
        inverse_name="report_line_id",
    )
    report_id = fields.Many2one(
        string="Parent Report",
        comodel_name="account.report",
        compute="_compute_report_id",
        store=True,
        readonly=False,
        required=True,
        recursive=True,
        precompute=True,
        index=True,
        ondelete="cascade",
    )
    hierarchy_level = fields.Integer(
        string="Level",
        compute="_compute_hierarchy_level",
        store=True,
        readonly=False,
        recursive=True,
        required=True,
        precompute=True,
    )
    parent_id = fields.Many2one(
        string="Parent Line",
        comodel_name="account.report.line",
        ondelete="set null",
        index="btree_not_null",
    )
    children_ids = fields.One2many(
        string="Child Lines",
        comodel_name="account.report.line",
        inverse_name="parent_id",
    )
    groupby = fields.Char(
        string="Group By",
        help="Comma-separated list of fields from account.move.line (Journal Item). When set, this line will generate sublines grouped by those keys.",
    )
    user_groupby = fields.Char(
        string="User Group By",
        compute="_compute_user_groupby",
        store=True,
        readonly=False,
        precompute=True,
        help="Comma-separated list of fields from account.move.line (Journal Item). When set, this line will generate sublines grouped by those keys.",
    )
    sequence = fields.Integer(string="Sequence")
    code = fields.Char(string="Code", help="Unique identifier for this line.")
    foldable = fields.Boolean(
        string="Foldable",
        help="By default, we always unfold the lines that can be. If this is checked, the line won't be unfolded by default, and a folding button will be displayed.",
    )
    print_on_new_page = fields.Boolean(
        "Print On New Page",
        help="When checked this line and everything after it will be printed on a new page.",
    )
    action_id = fields.Many2one(
        string="Action",
        comodel_name="ir.actions.actions",
        help="Setting this field will turn the line into a link, executing the action when clicked.",
    )
    hide_if_zero = fields.Boolean(
        string="Hide if Zero",
        help="This line and its children will be hidden when all of their columns are 0.",
    )
    domain_formula = fields.Char(
        string="Domain Formula Shortcut",
        help="Internal field to shorten expression_ids creation for the domain engine",
        inverse="_inverse_domain_formula",
        store=False,
    )
    account_codes_formula = fields.Char(
        string="Account Codes Formula Shortcut",
        help="Internal field to shorten expression_ids creation for the account_codes engine",
        inverse="_inverse_account_codes_formula",
        store=False,
    )
    aggregation_formula = fields.Char(
        string="Aggregation Formula Shortcut",
        help="Internal field to shorten expression_ids creation for the aggregation engine",
        inverse="_inverse_aggregation_formula",
        store=False,
    )
    external_formula = fields.Char(
        string="External Formula Shortcut",
        help="Internal field to shorten expression_ids creation for the external engine",
        inverse="_inverse_external_formula",
        store=False,
    )
    horizontal_split_side = fields.Selection(
        string="Horizontal Split Side",
        selection=[("left", "Left"), ("right", "Right")],
        compute="_compute_horizontal_split_side",
        readonly=False,
        store=True,
        recursive=True,
    )
    tax_tags_formula = fields.Char(
        string="Tax Tags Formula Shortcut",
        help="Internal field to shorten expression_ids creation for the tax_tags engine",
        inverse="_inverse_tax_tags_formula",
        store=False,
    )

    _code_uniq = models.Constraint(
        "unique (report_id, code)",
        "A report line with the same code already exists.",
    )

    @api.depends("parent_id.hierarchy_level")
    def _compute_hierarchy_level(self):
        for report_line in self:
            if report_line.parent_id:
                increase_level = 3 if report_line.parent_id.hierarchy_level == 0 else 2
                report_line.hierarchy_level = (
                    report_line.parent_id.hierarchy_level + increase_level
                )
            else:
                report_line.hierarchy_level = 1

    @api.depends("parent_id.report_id")
    def _compute_report_id(self):
        for report_line in self:
            if report_line.parent_id:
                report_line.report_id = report_line.parent_id.report_id

    @api.depends("parent_id.horizontal_split_side")
    def _compute_horizontal_split_side(self):
        for report_line in self:
            if report_line.parent_id:
                report_line.horizontal_split_side = (
                    report_line.parent_id.horizontal_split_side
                )

    def _compute_user_groupby(self):
        # Seeded once, at create. There is no @api.depends on purpose: a later recompute
        # could only either leave the value alone or overwrite the user's own grouping,
        # and the try/except that used to sit here could not repair anything -- whatever
        # it assigned, _check_groupby re-raised on the same write.
        for report_line in self:
            report_line.user_groupby = report_line.groupby

    @api.constrains("parent_id")
    def _check_groupby_no_child(self):
        for report_line in self:
            if report_line.parent_id.groupby or report_line.parent_id.user_groupby:
                raise ValidationError(
                    _(
                        "A line cannot have both children and a groupby value (line '%s').",
                        report_line.parent_id.name,
                    )
                )

    @api.constrains("groupby", "user_groupby")
    def _check_groupby(self):
        self.expression_ids._check_engine()

    @api.constrains("parent_id", "report_id")
    def _check_parent_report(self):
        for line in self:
            if line.parent_id and line.parent_id.report_id != line.report_id:
                raise ValidationError(
                    _(
                        'Line "%(line)s" belongs to report "%(report)s" but its parent '
                        '"%(parent)s" belongs to "%(parent_report)s". A line and its '
                        "parent must be in the same report.",
                        line=line.name,
                        report=line.report_id.display_name,
                        parent=line.parent_id.name,
                        parent_report=line.parent_id.report_id.display_name,
                    )
                )

    @api.constrains("parent_id")
    def _check_parent_line(self):
        for line in self.filtered(lambda x: x.parent_id == x):
            raise ValidationError(
                _('Line "%s" defines itself as its parent.', line.name)
            )
        if self._has_cycle("parent_id"):
            raise ValidationError(
                _("Report lines cannot form a recursive parent hierarchy.")
            )

    def _copy_hierarchy(self, copied_report):
        # _check_parent_report keeps a line and its parent in one report, so every
        # parent is inside `self`. Rows predating that constraint are copied as roots
        # rather than dropped, which is what the recursive walk this replaced did.
        line_ids = set(self.ids)
        lines_by_parent_id = defaultdict(self.browse)
        for line in self:
            parent_id = line.parent_id.id if line.parent_id.id in line_ids else False
            lines_by_parent_id[parent_id] |= line

        code_mapping = {}
        taken_codes = set()

        def allocate_codes(line):
            if line.code:
                code = f"{line.code}_COPY"
                while code in taken_codes:
                    code = f"{code}_COPY"
                taken_codes.add(code)
                code_mapping[line.code] = code
            for child in lines_by_parent_id[line.id]:
                allocate_codes(child)

        for root in lines_by_parent_id[False]:
            allocate_codes(root)

        copied_line_by_id = {}
        generation = lines_by_parent_id[False]
        while generation:
            vals_list = generation.copy_data()
            for line, vals in zip(generation, vals_list, strict=True):
                vals["report_id"] = copied_report.id
                vals["parent_id"] = (
                    copied_line_by_id[line.parent_id.id].id
                    if line.parent_id.id in copied_line_by_id
                    else False
                )
                vals["code"] = code_mapping.get(line.code, False)
            for line, copied_line in zip(
                generation, self.create(vals_list), strict=True
            ):
                copied_line_by_id[line.id] = copied_line
            next_generation = self.browse()
            for line in generation:
                next_generation |= lines_by_parent_id[line.id]
            generation = next_generation

        source_expressions = self.expression_ids
        if source_expressions:
            vals_list = source_expressions.copy_data()
            for expression, vals in zip(source_expressions, vals_list, strict=True):
                vals["report_line_id"] = copied_line_by_id[
                    expression.report_line_id.id
                ].id
            self.env["account.report.expression"].create(vals_list)

        return code_mapping

    def _inverse_domain_formula(self):
        self._create_report_expression(engine="domain")

    def _inverse_aggregation_formula(self):
        self._create_report_expression(engine="aggregation")

    def _inverse_tax_tags_formula(self):
        self._create_report_expression(engine="tax_tags")

    def _inverse_account_codes_formula(self):
        self._create_report_expression(engine="account_codes")

    def _inverse_external_formula(self):
        self._create_report_expression(engine="external")

    def _create_report_expression(self, engine):
        vals_list = []
        xml_ids = self.expression_ids.filtered(
            lambda exp: exp.label == "balance"
        ).get_external_id()
        for report_line in self:
            if engine == "domain" and report_line.domain_formula:
                domain_match = DOMAIN_REGEX.match(report_line.domain_formula)
                if not domain_match:
                    raise ValidationError(
                        _(
                            "Invalid domain formula %(formula)r on report line "
                            "%(line)r. Expected the form 'sum(<domain>)' "
                            "(optionally '-sum(<domain>)').",
                            formula=report_line.domain_formula,
                            line=report_line.name,
                        )
                    )
                subformula, formula = domain_match.groups()
                formula = re.sub(
                    r"""\bref\((?P<quote>['"])(?P<xmlid>.+?)(?P=quote)\)""",
                    lambda m: str(self.env.ref(m["xmlid"]).id),
                    formula,
                )
            elif engine == "account_codes" and report_line.account_codes_formula:
                subformula, formula = None, report_line.account_codes_formula
            elif engine == "aggregation" and report_line.aggregation_formula:
                subformula, formula = None, report_line.aggregation_formula
            elif engine == "external" and report_line.external_formula:
                subformula, formula = "editable", "most_recent"
                if report_line.external_formula == "percentage":
                    subformula = "editable;rounding=0"
                elif report_line.external_formula == "monetary":
                    formula = "sum"
            elif engine == "tax_tags" and report_line.tax_tags_formula:
                subformula, formula = None, report_line.tax_tags_formula
            else:
                report_line.expression_ids.filtered(
                    lambda exp: (
                        exp.engine == engine
                        and exp.label == "balance"
                        and not xml_ids.get(exp.id)
                    )
                ).unlink()
                continue

            vals = {
                "report_line_id": report_line.id,
                "label": "balance",
                "engine": engine,
                "formula": formula,
                "subformula": subformula,
            }
            if engine == "external" and report_line.external_formula:
                vals["figure_type"] = report_line.external_formula

            balance_expression = report_line.expression_ids.filtered(
                lambda exp: exp.label == "balance"
            )
            if not balance_expression:
                vals_list.append(vals)
            elif xml_ids.get(balance_expression.id):
                balance_expression.unlink()
                vals_list.append(vals)
            else:
                balance_expression.write(vals)

        if vals_list:
            self.env["account.report.expression"].create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_child_expressions(self):
        self.expression_ids.unlink()


class AccountReportExpression(models.Model):
    _name = "account.report.expression"
    _description = "Accounting Report Expression"
    _rec_name = "report_line_name"

    report_line_id = fields.Many2one(
        string="Report Line",
        comodel_name="account.report.line",
        required=True,
        index=True,
        ondelete="cascade",
    )
    report_line_name = fields.Char(
        string="Report Line Name", related="report_line_id.name"
    )
    label = fields.Char(string="Label", required=True, copy=True)
    engine = fields.Selection(
        string="Computation Engine",
        selection=[
            ("domain", "Odoo Domain"),
            ("tax_tags", "Tax Tags"),
            ("aggregation", "Aggregate Other Formulas"),
            ("account_codes", "Prefix of Account Codes"),
            ("external", "External Value"),
            ("custom", "Custom Python Function"),
        ],
        required=True,
    )
    formula = fields.Char(string="Formula", required=True)
    subformula = fields.Char(string="Subformula")
    date_scope = fields.Selection(
        string="Date Scope",
        selection=[
            ("from_beginning", "From the very start"),
            ("from_fiscalyear", "From the start of the fiscal year"),
            ("to_beginning_of_fiscalyear", "At the beginning of the fiscal year"),
            ("to_beginning_of_period", "At the beginning of the period"),
            ("strict_range", "Strictly on the given dates"),
            ("previous_return_period", "From previous return period"),
        ],
        required=True,
        default="strict_range",
    )
    figure_type = fields.Selection(
        string="Figure Type", selection=FIGURE_TYPE_SELECTION_VALUES
    )
    green_on_positive = fields.Boolean(
        string="Is Growth Good when Positive", default=True
    )
    blank_if_zero = fields.Boolean(
        string="Blank if Zero",
        help="When checked, 0 values will not show when displaying this expression's value.",
    )
    auditable = fields.Boolean(
        string="Auditable", store=True, readonly=False, compute="_compute_auditable"
    )

    carryover_target = fields.Char(
        string="Carry Over To",
        help="Formula in the form line_code.expression_label. This allows setting the target of the carryover for this expression "
        "(on a _carryover_*-labeled expression), in case it is different from the parent line.",
    )

    _domain_engine_subformula_required = models.Constraint(
        "CHECK(engine != 'domain' OR subformula IS NOT NULL)",
        "Expressions using 'domain' engine should all have a subformula.",
    )
    _line_label_uniq = models.Constraint(
        "UNIQUE(report_line_id,label)",
        "The expression label must be unique per report line.",
    )

    @api.constrains("carryover_target", "label")
    def _check_carryover_target(self):
        for expression in self:
            if not expression.carryover_target:
                continue
            if not expression.label.startswith("_carryover_"):
                raise ValidationError(
                    _(
                        "You cannot use the field carryover_target in an expression that does not have the label starting with _carryover_"
                    )
                )
            _line_code, target_label = expression._parse_carryover_target()
            if not target_label.startswith("_applied_carryover_"):
                raise ValidationError(
                    _(
                        "When targeting an expression for carryover, the label of that expression must start with _applied_carryover_"
                    )
                )

    def _parse_carryover_target(self):
        self.ensure_one()
        parts = self.carryover_target.split(".")
        if len(parts) != 2 or not all(parts):
            raise ValidationError(
                _(
                    "The carryover target of expression '%(label)s' must have the form "
                    "'line_code.expression_label', but is '%(target)s'.",
                    label=self.label,
                    target=self.carryover_target,
                )
            )
        return parts[0], parts[1]

    @api.constrains("formula")
    def _check_formula(self):
        def raise_formula_error(expression, cause=None):
            raise ValidationError(
                self.env._(
                    "Invalid formula for expression '%(label)s' of line '%(line)s': %(formula)s",
                    label=expression.label,
                    line=expression.report_line_name,
                    formula=expression.formula,
                )
            ) from cause

        expressions_by_engine = self.grouped("engine")
        for expression in expressions_by_engine.get("domain", []):
            try:
                domain = ast.literal_eval(expression.formula)
                self.env["account.move.line"]._search(domain)
            except Exception as error:
                raise_formula_error(expression, error)

        for expression in expressions_by_engine.get("account_codes", []):
            for token in ACCOUNT_CODES_ENGINE_SPLIT_REGEX.split(
                expression.formula.replace(" ", "")
            ):
                if token:
                    token_match = ACCOUNT_CODES_ENGINE_TERM_REGEX.match(token)
                    prefix = token_match and token_match["prefix"]
                    if not prefix:
                        raise_formula_error(expression)

        for expression in expressions_by_engine.get("aggregation", []):
            if not AGGREGATION_ENGINE_FORMULA_REGEX.fullmatch(expression.formula):
                raise_formula_error(expression)

    @api.depends("engine")
    def _compute_auditable(self):
        auditable_engines = self._get_auditable_engines()
        for expression in self:
            expression.auditable = expression.engine in auditable_engines

    @api.constrains("engine", "report_line_id")
    def _check_engine(self):
        for expression in self:
            if expression.engine in ("aggregation", "external") and (
                expression.report_line_id.groupby
                or expression.report_line_id.user_groupby
            ):
                engine_description = dict(
                    expression._fields["engine"]._description_selection(self.env)
                )
                raise ValidationError(
                    _(
                        "Groupby feature isn't supported by '%(engine)s' engine. Please remove the groupby value on '%(report_line)s'",
                        engine=engine_description[expression.engine],
                        report_line=expression.report_line_id.display_name,
                    )
                )

    def _get_auditable_engines(self):
        return AUDITABLE_ENGINES

    @staticmethod
    def _strip_formula(formula):
        return re.sub(r"\s+", " ", formula.strip())

    def _create_missing_tax_tags(self, formula_override=None):
        tag_names_by_country_id = defaultdict(set)
        for expression in self:
            country_id = expression.report_line_id.report_id.country_id.id
            tag_name = formula_override or expression.formula
            tag_names_by_country_id[country_id].add(tag_name.lstrip("-"))

        existing_keys = self._get_existing_tax_tag_keys(tag_names_by_country_id)
        tags_create_vals = [
            tag_vals
            for country_id, tag_names in tag_names_by_country_id.items()
            for tag_name in tag_names
            if (tag_name, country_id) not in existing_keys
            for tag_vals in self._get_tags_create_vals(tag_name, country_id)
        ]
        if tags_create_vals:
            self.env["account.account.tag"].create(tags_create_vals)

    def _get_existing_tax_tag_keys(self, tag_names_by_country_id):
        tag_model = self.env["account.account.tag"]
        or_domains = [
            Domain(tag_model._get_tax_tags_domain(tag_name, country_id))
            for country_id, tag_names in tag_names_by_country_id.items()
            for tag_name in tag_names
        ]
        if not or_domains:
            return set()
        existing_tags = tag_model.with_context(active_test=False, lang="en_US").search(
            Domain.OR(or_domains)
        )
        return {(tag.name, tag.country_id.id) for tag in existing_tags}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if isinstance(vals.get("formula"), str):
                vals["formula"] = self._strip_formula(vals["formula"])

        result = super().create(vals_list)
        result.filtered(lambda x: x.engine == "tax_tags")._create_missing_tax_tags()
        return result

    def write(self, vals):
        if isinstance(vals.get("formula"), str):
            vals["formula"] = self._strip_formula(vals["formula"])

        tax_tags_expressions = self.filtered(lambda x: x.engine == "tax_tags")

        if vals.get("engine") == "tax_tags":
            (self - tax_tags_expressions)._create_missing_tax_tags(
                formula_override=vals.get("formula")
            )

        if "formula" not in vals or (
            vals.get("engine") and vals["engine"] != "tax_tags"
        ):
            return super().write(vals)

        former_formulas_by_country = defaultdict(list)
        for expr in tax_tags_expressions:
            former_formulas_by_country[expr.report_line_id.report_id.country_id].append(
                expr.formula
            )

        result = super().write(vals)
        new_formula = vals["formula"]
        tag_model = self.env["account.account.tag"]
        for country, former_formulas_list in former_formulas_by_country.items():
            new_tag_exists = bool(tag_model._get_tax_tags(new_formula, country.id))
            for former_formula in former_formulas_list:
                if new_tag_exists:
                    break
                former_tax_tags = tag_model._get_tax_tags(former_formula, country.id)
                if former_tax_tags and all(
                    tag_expr in self
                    for tag_expr in former_tax_tags._get_related_tax_report_expressions()
                ):
                    former_tax_tags._update_field_translations(
                        "name", {"en_US": new_formula.lstrip("-")}
                    )
                else:
                    tag_model.create(
                        self._get_tags_create_vals(new_formula, country.id)
                    )
                new_tag_exists = True

        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_archive_used_tags(self):
        expressions_tags = self._get_matching_tags().with_context(lang="en_US")
        if not expressions_tags:
            return

        still_referenced_keys = {
            (
                expression.formula.lstrip("-"),
                expression.report_line_id.report_id.country_id.id,
            )
            for expression in expressions_tags.sudo()._get_related_tax_report_expressions()
            - self
        }
        orphan_tags = expressions_tags.filtered(
            lambda tag: (tag.name, tag.country_id.id) not in still_referenced_keys
        )
        if not orphan_tags:
            return

        tags_used_by_aml_ids = {
            tag.id
            for [tag] in self.env["account.move.line"]
            .sudo()
            ._read_group(
                [("tax_tag_ids", "in", orphan_tags.ids)], groupby=["tax_tag_ids"]
            )
        }
        tags_to_archive = orphan_tags.filtered(
            lambda tag: tag.id in tags_used_by_aml_ids
        )
        tags_to_unlink = orphan_tags - tags_to_archive

        if tags_to_archive or tags_to_unlink:
            rep_lines_with_tag = (
                self.env["account.tax.repartition.line"]
                .sudo()
                .search([("tag_ids", "in", (tags_to_archive + tags_to_unlink).ids)])
            )
            rep_lines_with_tag.write(
                {
                    "tag_ids": [
                        Command.unlink(tag.id)
                        for tag in tags_to_archive + tags_to_unlink
                    ]
                }
            )
            tags_to_archive.active = False
            tags_to_unlink.unlink()

    @api.depends("report_line_name", "label")
    def _compute_display_name(self):
        for expr in self:
            expr.display_name = f"{expr.report_line_name} [{expr.label}]"

    def _expand_aggregations(self):
        result = self

        to_expand = self.filtered(lambda x: x.engine == "aggregation")
        while to_expand:
            domains = []
            sub_expressions = self.env["account.report.expression"]

            for candidate_expr in to_expand:
                if candidate_expr.formula == SUM_CHILDREN_FORMULA:
                    sub_expressions |= candidate_expr.report_line_id.children_ids.expression_ids.filtered(
                        lambda e, label=candidate_expr.label: e.label == label
                    )
                else:
                    labels_by_code = candidate_expr._get_aggregation_terms_details()

                    if (
                        candidate_expr.subformula
                        and candidate_expr.subformula.startswith("cross_report")
                    ):
                        report_id = candidate_expr._get_cross_report_id()
                    else:
                        report_id = candidate_expr.report_line_id.report_id.id
                    cross_report_domain = [("report_line_id.report_id", "=", report_id)]

                    for line_code, expr_labels in labels_by_code.items():
                        dependency_domain = [
                            ("report_line_id.code", "=", line_code),
                            ("label", "in", tuple(expr_labels)),
                        ] + cross_report_domain
                        domains.append(dependency_domain)

            if domains:
                sub_expressions |= self.env["account.report.expression"].search(
                    Domain.OR(domains)
                )

            seen_ids = set(result.ids)
            to_expand = sub_expressions.filtered(
                lambda x, seen_ids=seen_ids: (
                    x.engine == "aggregation" and x.id not in seen_ids
                )
            )
            result |= sub_expressions

        return result

    def _get_cross_report_id(self):
        self.ensure_one()
        error_context = {
            "report_name": self.report_line_id.report_id.display_name,
            "line_name": self.report_line_name,
            "label": self.label,
        }
        subformula_match = CROSS_REPORT_REGEX.match(self.subformula or "")
        if not subformula_match:
            raise UserError(
                _(
                    "In report '%(report_name)s', on line '%(line_name)s', with label '%(label)s',\n"
                    "The format of the cross report expression is invalid. \n"
                    "Expected: cross_report(<report_id>|<xml_id>)"
                    "Example:  cross_report(my_module.my_report) or cross_report(123)",
                    **error_context,
                )
            )

        # Both spellings have to end at a report that exists: a dangling id used to be
        # returned as-is, and env.ref resolves any model, so the aggregation silently
        # totalled nothing instead of saying the target was wrong.
        cross_report_value = subformula_match.group(1)
        if cross_report_value.isdigit():
            target_report = (
                self.env["account.report"].browse(int(cross_report_value)).exists()
            )
        else:
            target_report = self.env.ref(cross_report_value, raise_if_not_found=False)
            if target_report and target_report._name != "account.report":
                target_report = None

        if not target_report:
            raise UserError(
                _(
                    "In report '%(report_name)s', on line '%(line_name)s', with label '%(label)s',\n"
                    "Failed to parse the cross report id or xml_id.\n",
                    **error_context,
                )
            )
        if target_report == self.report_line_id.report_id:
            raise UserError(_("You cannot use cross report on itself"))
        return target_report.id

    @staticmethod
    def _split_aggregation_formula_terms(formula):
        return AGGREGATION_TERM_SPLIT_REGEX.split(re.sub(r"[\s()]", "", formula))

    @staticmethod
    def _match_aggregation_code_term(term):
        if not term or AGGREGATION_NUMBER_TERM_REGEX.match(term):
            return None
        return AGGREGATION_CODE_TERM_REGEX.match(term)

    def _get_aggregation_terms_details(self):
        totals_by_code = defaultdict(set)
        for expression in self:
            if expression.engine != "aggregation":
                raise UserError(
                    _(
                        "Cannot get aggregation details from a line not using 'aggregation' engine"
                    )
                )

            for term in self._split_aggregation_formula_terms(expression.formula):
                term_match = self._match_aggregation_code_term(term)
                if term_match:
                    totals_by_code[term_match["line_code"]].add(
                        term_match["expr_label"]
                    )

            if expression.subformula:
                if_other_expr_match = IF_OTHER_EXPR_SUBFORMULA_REGEX.match(
                    expression.subformula
                )
                if if_other_expr_match:
                    totals_by_code[if_other_expr_match["line_code"]].add(
                        if_other_expr_match["expr_label"]
                    )

        return totals_by_code

    def _get_matching_tags(self):
        tag_expressions = self.filtered(lambda x: x.engine == "tax_tags")
        if not tag_expressions:
            return self.env["account.account.tag"]

        or_domains = []
        for tag_expression in tag_expressions:
            country = tag_expression.report_line_id.report_id.country_id
            or_domains.append(
                self.env["account.account.tag"]._get_tax_tags_domain(
                    tag_expression.formula, country.id
                )
            )

        return (
            self.env["account.account.tag"]
            .with_context(active_test=False, lang="en_US")
            .search(Domain.OR(or_domains))
        )

    @api.model
    def _get_tags_create_vals(self, tag_name, country_id):
        return [
            {
                "name": tag_name.lstrip("-"),
                "applicability": "taxes",
                "country_id": country_id,
            }
        ]

    def _get_carryover_target_expression(self, options):
        self.ensure_one()

        if self.carryover_target:
            line_code, expr_label = self._parse_carryover_target()
            return self.env["account.report.expression"].search(
                [
                    ("report_line_id.code", "=", line_code),
                    ("label", "=", expr_label),
                    ("report_line_id.report_id", "=", self.report_line_id.report_id.id),
                ],
                limit=1,
            )

        main_expr_label = re.sub(r"^_carryover_", "", self.label)
        target_label = "_applied_carryover_%s" % main_expr_label
        auto_chosen_target = self.report_line_id.expression_ids.filtered(
            lambda x: x.label == target_label
        )

        if not auto_chosen_target:
            raise UserError(
                _(
                    "Could not determine carryover target automatically for expression %s.",
                    self.label,
                )
            )

        return auto_chosen_target


class AccountReportColumn(models.Model):
    _name = "account.report.column"
    _description = "Accounting Report Column"
    _order = "sequence, id"

    name = fields.Char(string="Name", translate=True, required=True)
    expression_label = fields.Char(string="Expression Label", required=True)
    sequence = fields.Integer(string="Sequence")
    report_id = fields.Many2one(
        string="Report",
        comodel_name="account.report",
        index="btree_not_null",
        ondelete="cascade",
    )
    sortable = fields.Boolean(string="Sortable")
    figure_type = fields.Selection(
        string="Figure Type",
        selection=FIGURE_TYPE_SELECTION_VALUES,
        default="monetary",
        required=True,
    )
    blank_if_zero = fields.Boolean(
        string="Blank if Zero",
        help="When checked, 0 values will not show in this column.",
    )
    custom_audit_action_id = fields.Many2one(
        string="Custom Audit Action", comodel_name="ir.actions.act_window"
    )


class AccountReportExternalValue(models.Model):
    _name = "account.report.external.value"
    _description = "Accounting Report External Value"
    _check_company_auto = True
    _order = "date, id"

    name = fields.Char(required=True)
    value = fields.Float(string="Numeric Value")
    text_value = fields.Char(string="Text Value")
    date = fields.Date(required=True)

    target_report_expression_id = fields.Many2one(
        string="Target Expression",
        comodel_name="account.report.expression",
        required=True,
        index=True,
        ondelete="cascade",
    )
    target_report_line_id = fields.Many2one(
        string="Target Line", related="target_report_expression_id.report_line_id"
    )
    target_report_expression_label = fields.Char(
        string="Target Expression Label", related="target_report_expression_id.label"
    )
    report_country_id = fields.Many2one(
        string="Country", related="target_report_line_id.report_id.country_id"
    )

    company_id = fields.Many2one(
        string="Company",
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
    )

    carryover_origin_expression_label = fields.Char(string="Origin Expression Label")
    carryover_origin_report_line_id = fields.Many2one(
        string="Origin Line", comodel_name="account.report.line"
    )
