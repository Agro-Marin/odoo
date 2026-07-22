import logging
from ast import literal_eval
from collections import OrderedDict
from random import randint

from lxml import etree, html

from odoo import _, api, fields, models
from odoo.exceptions import MissingError, ValidationError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class WebsiteSnippetFilter(models.Model):
    _name = "website.snippet.filter"
    _inherit = ["website.published.multi.mixin"]
    _description = "Website Snippet Filter"
    _order = "name ASC"

    name = fields.Char(required=True, translate=True)
    action_server_id = fields.Many2one(
        "ir.actions.server", "Server Action", ondelete="cascade"
    )
    field_names = fields.Char(
        help="A list of comma-separated field names", required=True, default=""
    )
    filter_id = fields.Many2one("ir.filters", "Filter", ondelete="cascade")
    limit = fields.Integer(
        help="The limit is the maximum number of records retrieved", required=True
    )
    website_id = fields.Many2one("website", string="Website", ondelete="cascade")
    model_name = fields.Char(string="Model name", compute="_compute_model_name")
    help = fields.Text(
        string="Description",
        help="Optional help text describing the filter usage and/or purpose.",
        translate=True,
    )

    @api.depends("filter_id", "action_server_id")
    def _compute_model_name(self):
        for snippet_filter in self:
            if snippet_filter.filter_id:
                snippet_filter.model_name = snippet_filter.filter_id.model_id
            else:  # self.action_server_id
                snippet_filter.model_name = (
                    snippet_filter.action_server_id.model_id.model
                )

    @api.constrains("action_server_id", "filter_id")
    def _check_data_source_is_provided(self):
        for record in self:
            if bool(record.action_server_id) == bool(record.filter_id):
                raise ValidationError(
                    _("Either action_server_id or filter_id must be provided.")
                )

    @api.constrains("limit")
    def _check_limit(self):
        """Limit must be between 1 and 16."""
        for record in self:
            if not 0 < record.limit <= 16:
                raise ValidationError(_("The limit must be between 1 and 16."))

    @api.constrains("field_names")
    def _check_field_names(self):
        for record in self:
            for field_name in record.field_names.split(","):
                if not field_name.strip():
                    raise ValidationError(
                        _("Empty field name in “%s”", record.field_names)
                    )

    def _render(
        self,
        template_key=None,
        limit=None,
        search_domain=None,
        with_sample=False,
        res_model=None,
        res_id=None,
        **custom_template_data,
    ):
        """Renders the website dynamic snippet items

        Every argument reaches this method straight from an unauthenticated
        JSON-RPC caller (``/website/snippet/filters``), so nothing here may
        assume a well-formed payload: a missing or malformed argument must
        produce the same empty result as any other guard below, never an
        exception. ``template_key`` and ``limit`` therefore default to ``None``
        rather than being required positionals — omitting them used to raise
        ``TypeError`` and a bad ``template_key`` used to raise ``ValueError``,
        both of which surfaced as an unauthenticated traceback.
        """
        self and self.ensure_one()

        if not template_key or ".dynamic_filter_template_" not in template_key:
            return []
        if search_domain is None:
            search_domain = []

        # Return [] (not "") on the guard branches: the normal path returns a
        # list of html strings, and the controller passes this straight to the
        # JSON-RPC client, which shouldn't have to handle two shapes.
        if (
            self.website_id
            and self.env["website"].get_current_website() != self.website_id
        ):
            return []

        if self.model_name and self.model_name.replace(".", "_") not in template_key:
            return []

        records = self._prepare_values(
            limit=limit, search_domain=search_domain, res_model=res_model, res_id=res_id
        )
        is_sample = with_sample and not records
        if is_sample:
            records = self._prepare_sample(limit, res_model=res_model)
        content = (
            self.env["ir.qweb"]
            .with_context(inherit_branding=False)
            ._render(
                template_key,
                dict(
                    records=records,
                    is_sample=is_sample,
                    **custom_template_data,
                ),
            )
        )
        return [
            etree.tostring(el, encoding="unicode", method="html")
            for el in list(html.fromstring("<root>%s</root>" % str(content)))
        ]

    @staticmethod
    def _coerce_positive_int(value):
        """Return ``value`` as a positive int, or ``None`` if it isn't one.

        JSON-RPC delivers whatever the caller typed, so ``limit``/``res_id`` can
        arrive as a string, a float, a bool or a list. Feeding those to ``min()``
        or to a domain leaf raises deep inside the ORM; normalise once instead.
        """
        if isinstance(value, bool) or not isinstance(value, (int, str, float)):
            return None
        try:
            value = int(value)
        except TypeError, ValueError:
            return None
        return value if value > 0 else None

    def _prepare_values(self, limit=None, search_domain=None, **options):
        """Gets the data and returns it the right format for render."""
        self and self.ensure_one()

        # ``res_model`` / ``res_id`` / ``limit`` are client-supplied on the
        # public route. A saved filter's model is NOT negotiable: letting
        # ``res_model`` win here ran the designer's domain, sort and context
        # against a model of the visitor's choosing (a filter bound to
        # ``res.country`` would happily return ``res.lang`` records), and an
        # unknown model name reached ``self.env[...]`` as an unauthenticated
        # ``KeyError``. ``res_model`` only selects the model for the
        # single-record lookup, which is the flow that has no filter to take it
        # from.
        model_name = self.filter_id.sudo().model_id or options.get("res_model")
        res_id = self._coerce_positive_int(options.get("res_id"))
        # The "limit" field is there to prevent loading an arbitrary number of
        # records asked by the client side. This here makes sure you can always
        # load at least 16 records as it is what the editor allows.
        max_limit = max(self.limit, 16)
        limit = self._coerce_positive_int(limit)
        limit = (limit and min(limit, max_limit)) or max_limit
        single_record_filter = limit == 1 and model_name and res_id

        # Either a multi-record filter is provided, or a single record is specified.
        if self.filter_id or single_record_filter:
            # Checked here and not earlier: the ``action_server_id`` branch below
            # has no model of its own and must stay reachable.
            if model_name not in self.env:
                return []
            model = self.env[model_name]
            filter_sudo = self.filter_id.sudo()
            if single_record_filter:
                # A specific record was requested by id (res_model/res_id come
                # straight from the client). We must NOT trust that id to bypass
                # publication / website / company scoping and record rules:
                # restrict the search to that id and apply the exact same scoping
                # (and caller access rights) as the multi-record path below.
                domain = Domain("id", "=", res_id)
                context = {}
                order = None
            else:
                domain = Domain(filter_sudo._get_eval_domain())
                context = literal_eval(filter_sudo.context)
                order = ",".join(literal_eval(filter_sudo.sort)) or None
            if "website_id" in model:
                domain &= self.env["website"].get_current_website().website_domain()
            if "company_id" in model:
                website = self.env["website"].get_current_website()
                domain &= Domain("company_id", "in", [False, website.company_id.id])
            if "is_published" in model:
                domain &= Domain("is_published", "=", True)
            if search_domain:
                search_domain = Domain(search_domain)
                # ``search_domain`` is client-supplied on the public route.
                # Only allow leaves that reference a *direct* field of the
                # target model. A dotted path (e.g. ``create_uid.login``) passed
                # the old ``split(".")[0]`` check and let a public visitor filter
                # on fields of related — possibly unpublished — records, turning
                # the published result set into a boolean oracle over them.
                for condition in search_domain.iter_conditions():
                    field_expr = condition.field_expr
                    if "." in field_expr or field_expr not in model._fields:
                        raise ValueError(
                            _("Invalid field %r in search domain") % field_expr
                        )
                domain &= search_domain
            try:
                records = (
                    model.sudo(False)
                    .with_context(**context)
                    .search(domain, order=order, limit=limit)
                )
                return self._filter_records_to_values(
                    records.sudo(), res_model=model_name
                )
            except MissingError:
                if not single_record_filter:
                    _logger.warning(
                        "The provided domain %s in 'ir.filters' generated a MissingError in '%s'",
                        domain,
                        self._name,
                    )
                return []
        elif self.action_server_id:
            try:
                return (
                    self.action_server_id.with_context(
                        dynamic_filter=self,
                        limit=limit,
                        search_domain=search_domain,
                    )
                    .sudo()
                    .run()
                    or []
                )
            except MissingError:
                _logger.warning(
                    "The provided domain %s in 'ir.actions.server' generated a MissingError in '%s'",
                    search_domain,
                    self._name,
                )
                return []
        return None

    def _get_field_name_and_type(self, model, field_name):
        """
        Separates the name and the widget type

        @param model: Model to which the field belongs, without it type is deduced from field_name
        @param field_name: Name of the field possibly followed by a colon and a forced field type

        @return Tuple containing the field name and the field type
        """
        # Not `_` for the separator: that name is the module-level translation
        # function, and rebinding it here would make any `_()` added to this
        # method blow up with "str object is not callable".
        field_name, _sep, field_widget = field_name.partition(":")
        if field_widget:
            return field_name, field_widget
        field = model._fields.get(field_name)
        if field:
            field_type = field.type
        elif "image" in field_name:
            field_type = "image"
        elif "price" in field_name:
            field_type = "monetary"
        else:
            field_type = "text"
        return field_name, field_type

    def _get_filter_meta_data(self, model):
        """
        Extracts the meta data of each field

        @return OrderedDict containing the widget type for each field name
        """
        meta_data = OrderedDict({})
        field_names = self.field_names or self.with_context(
            model=model._name
        ).default_get(["field_names"]).get("field_names")
        for field_name in (field_names or "").split(","):
            # Skip blanks and trim surrounding space. `field_names` defaults to
            # "" — and `default_get` returns "" on the filter-less single-record
            # path — so a bare split yields one empty name, which ends up as
            # `record[""]` and raises KeyError on a public, unauthenticated
            # route. `_check_field_names` only guards *stored* values, and it
            # does not strip, so " email" would fail the same way.
            field_name = field_name.strip()
            if not field_name:
                continue
            field_name, field_widget = self._get_field_name_and_type(model, field_name)
            meta_data[field_name] = field_widget
        return meta_data

    def _prepare_sample(self, length=6, **options):
        """
        Generates sample data and returns it the right format for render.

        @param length: Number of sample records to generate
        @param options: Additional options:
        - res_model (str): The name of the targeted model.

        @return Array of objets with a value associated to each name in field_names
        """
        if not length:
            return []
        records = self._prepare_sample_records(length, **options)
        options["is_sample"] = True
        return self._filter_records_to_values(records, **options)

    def _prepare_sample_records(self, length, **options):
        """
        Generates sample records.

        @param length: Number of sample records to generate
        @param options: Additional options:
        - res_model (str): The name of the targeted model.

        @return List of of sample records
        """
        if not length:
            return []

        sample = []
        model = self.env[(self.model_name or options.get("res_model"))]
        sample_data = self._get_hardcoded_sample(model)
        if sample_data:
            for index in range(length):
                single_sample_data = sample_data[index % len(sample_data)].copy()
                self._fill_sample(model, single_sample_data, index)
                sample.append(model.new(single_sample_data))
        return sample

    def _fill_sample(self, model, sample, index):
        """
        Fills the missing fields of a sample

        @param sample: Data structure to fill with values for each name in field_names
        @param index: Index of the sample within the dataset
        """
        meta_data = self._get_filter_meta_data(model)
        for field_name, field_widget in meta_data.items():
            if field_name not in sample and field_name in model:
                if field_widget in ("image", "binary"):
                    sample[field_name] = None
                elif field_widget == "monetary":
                    sample[field_name] = randint(100, 10000) / 10.0
                elif field_widget in ("integer", "float"):
                    sample[field_name] = index
                else:
                    sample[field_name] = _("Sample %s", index + 1)
        return sample

    def _get_hardcoded_sample(self, model):
        """
        Returns a hard-coded sample

        @param model: Model of the currently rendered view

        @return Sample data records with field values
        """
        return [{}]

    def _filter_records_to_values(self, records, **options):
        """
        Extract the fields from the data source 'records' and put them into a dictionary of values

        @param records: Model records returned by the filter
        @param options: Additional options:
        - res_model (str): The name of the targeted model.
        - is_sample (bool): True if conversion is for sample records.

        @return List of dict associating the field value to each field name
        """
        self and self.ensure_one()
        model = self.env[self.model_name or options.get("res_model")]
        meta_data = self._get_filter_meta_data(model)

        values = []
        Website = self.env["website"]
        for record in records:
            data = {}
            for field_name, field_widget in meta_data.items():
                field = model._fields.get(field_name)
                if field and field.type in ("binary", "image"):
                    if options.get("is_sample"):
                        data[field_name] = (
                            record[field_name].decode("utf8")
                            if field_name in record
                            else "/web/image"
                        )
                    else:
                        data[field_name] = Website.image_url(record, field_name)
                elif field_widget == "monetary":
                    model_currency = None
                    if field and field.type == "monetary":
                        model_currency = record[field.get_currency_field(record)]
                    elif "currency_id" in model._fields:
                        model_currency = record["currency_id"]
                    if model_currency:
                        website_currency = self._get_website_currency()
                        data[field_name] = model_currency._convert(
                            record[field_name],
                            website_currency,
                            Website.get_current_website().company_id,
                            fields.Date.today(),
                        )
                    else:
                        data[field_name] = record[field_name]
                else:
                    data[field_name] = record[field_name]

            data["call_to_action_url"] = (
                "website_url" in record and record["website_url"]
            )
            data["_record"] = record
            values.append(data)
        return values

    @api.model
    def _get_website_currency(self):
        company = self.env["website"].get_current_website().company_id
        return company.currency_id
