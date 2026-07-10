import logging
from typing import TYPE_CHECKING, Any

from lxml import etree
from lxml.builder import E

from odoo import api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools import _, config, frozendict

# ir_ui_view is imported before ir_ui_view_base (see models/__init__.py) and
# never imports back, so reusing its compiled XPath here is cycle-free.
from .ir_ui_view import _xpath_descendant_field

if TYPE_CHECKING:
    from lxml.etree import _Element

_logger = logging.getLogger(__name__)


class Base(models.AbstractModel):
    _inherit = "base"

    _date_name = "date"  #: field to use for default calendar view

    def _get_access_action(
        self, access_uid: int | None = None, force_website: bool = False
    ) -> dict[str, Any]:
        """Return an action to open the document (its form view by default).

        Meant to be overridden in addons giving specific access to the document.

        :param access_uid: the user accessing the document, if different from the
            current user (an access may be computed for someone else)
        :param force_website: force frontend redirection if available on self;
            used in portal / website overrides
        """
        self.ensure_one()
        return self.get_formview_action(access_uid=access_uid)

    @api.model
    def get_empty_list_help(self, help_message: str) -> str:
        """Hook to customize the help shown in empty list/kanban views.

        :param help_message: ir.actions.act_window help content
        :return: the help message to display (the action help by default)
        """
        return help_message

    @api.model
    def view_header_get(self, view_id: int | None, view_type: str) -> str | bool:
        """Return the window title for the given view, or False.

        Override this method if you need a window title that depends on the context.
        """
        return False

    @api.model
    def _get_default_form_view(self) -> _Element:
        """Generate a default form view using all fields of the model."""
        sheet = E.sheet(string=self._description)
        main_group = E.group()
        left_group = E.group()
        right_group = E.group()
        for fname, field in self._fields.items():
            if (
                fname in models.MAGIC_COLUMNS
                or (fname == "display_name" and field.readonly)
                or (
                    field.type == "binary"
                    and not isinstance(field, fields.Image)
                    and not field.store
                )
            ):
                continue
            if field.type in ("one2many", "many2many", "text", "html"):
                # x2many/text/html get a full-width oneline group; flush any
                # pending left/right columns first.
                if len(left_group) > 0:
                    main_group.append(left_group)
                    left_group = E.group()
                if len(right_group) > 0:
                    main_group.append(right_group)
                    right_group = E.group()
                if len(main_group) > 0:
                    sheet.append(main_group)
                    main_group = E.group()
                sheet.append(E.group(E.field(name=fname)))
            elif len(left_group) > len(right_group):
                right_group.append(E.field(name=fname))
            else:
                left_group.append(E.field(name=fname))
        if len(left_group) > 0:
            main_group.append(left_group)
        if len(right_group) > 0:
            main_group.append(right_group)
        sheet.append(main_group)
        sheet.append(E.group(E.separator()))
        return E.form(sheet)

    @api.model
    def _get_default_search_view(self) -> _Element:
        """Generate a single-field search view, based on _rec_name."""
        element = E.field(name=self._rec_name_fallback())
        return E.search(element, string=self._description)

    @api.model
    def _get_default_list_view(self) -> _Element:
        """Generate a single-field list view, based on _rec_name."""
        element = E.field(name=self._rec_name_fallback())
        return E.list(element, string=self._description)

    @api.model
    def _get_default_pivot_view(self) -> _Element:
        """Generate an empty pivot view."""
        return E.pivot(string=self._description)

    @api.model
    def _get_default_kanban_view(self) -> _Element:
        """Generate a single-field kanban view, based on _rec_name."""

        field = E.field(name=self._rec_name_fallback())
        kanban_card = E.t(field, {"t-name": "card"})
        templates = E.templates(kanban_card)
        return E.kanban(templates, string=self._description)

    @api.model
    def _get_default_graph_view(self) -> _Element:
        """Generate a single-field graph view, based on _rec_name."""
        element = E.field(name=self._rec_name_fallback())
        return E.graph(element, string=self._description)

    @api.model
    def _get_default_calendar_view(self) -> _Element:
        """Generate a default calendar view, inferring calendar fields from a
        set of pre-set attribute names.
        """

        def set_first_of(seq: list[str], in_: dict, to: str) -> bool:
            """Set the ``to`` attribute of the closed-over ``view`` to the first
            value of ``seq`` also found in ``in_``; return whether one was found.
            """
            for item in seq:
                if item in in_ and in_[item]._description_searchable:
                    view.set(to, item)
                    return True
            return False

        view = E.calendar(string=self._description)
        view.append(E.field(name=self._rec_name_fallback()))

        if not set_first_of(
            [self._date_name, "date", "date_start", "x_date", "x_date_start"],
            self._fields,
            "date_start",
        ):
            raise UserError(_("Insufficient fields for Calendar View!"))

        set_first_of(
            ["user_id", "partner_id", "x_user_id", "x_partner_id"],
            self._fields,
            "color",
        )

        if not set_first_of(
            ["date_stop", "date_end", "x_date_stop", "x_date_end"],
            self._fields,
            "date_stop",
        ):
            if not set_first_of(
                [
                    "date_delay",
                    "planned_hours",
                    "x_date_delay",
                    "x_planned_hours",
                ],
                self._fields,
                "date_delay",
            ):
                raise UserError(
                    _(
                        "Insufficient fields to generate a Calendar View for %s, missing a date_stop or a date_delay",
                        self._name,
                    )
                )

        return view

    @api.model
    @api.readonly
    def get_views(
        self,
        views: list[list[int | str]],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the fields_views of the given views, the model's fields, and
        optionally its filters for the given action.

        The result may only depend on the requested view types, access rights,
        view access rules, options, context lang and TYPE_view_ref (no other
        context values).

        :param views: list of [view_id, view_type]
        :param options: optional boolean flags:

            ``toolbar``
                include contextual actions when loading fields_views
            ``load_filters``
                return the model's filters
            ``action_id``
                id of the action to get the filters, else the global filters

        :return: dict with ``views`` and ``models`` keys (filters, when
            requested, are nested under ``views['search']['filters']``)
        """
        options = options or {}
        result = {}

        result["views"] = {
            v_type: self.get_view(v_id, v_type, **options) for [v_id, v_type] in views
        }

        view_models = {}
        for view in result["views"].values():
            for model, model_fields in view.pop("models").items():
                view_models.setdefault(model, set()).update(model_fields)

        result["models"] = {}

        for model, model_fields in view_models.items():
            result["models"][model] = {
                "fields": self.env[model].fields_get(
                    allfields=model_fields,
                    attributes=self._get_view_field_attributes(),
                )
            }

        # Add related action information if asked
        if options.get("toolbar"):
            for view in result["views"].values():
                view["toolbar"] = {}

            bindings = self.env["ir.actions.actions"].get_bindings(self._name)
            for action_type, key in (("report", "print"), ("action", "action")):
                for action in bindings.get(action_type, []):
                    view_types = (
                        action["binding_view_types"].split(",")
                        if action.get("binding_view_types")
                        else result["views"].keys()
                    )
                    for view_type in view_types:
                        if view_type in result["views"]:
                            result["views"][view_type]["toolbar"].setdefault(
                                key, []
                            ).append(action)

        if options.get("load_filters") and "search" in result["views"]:
            result["views"]["search"]["filters"] = self.env["ir.filters"].get_filters(
                self._name,
                options.get("action_id"),
                options.get("embedded_action_id"),
                options.get("embedded_parent_res_id"),
            )

        return result

    @api.model
    def _get_view(
        self,
        view_id: int | None = None,
        view_type: str = "form",
        **options: Any,
    ) -> tuple[_Element, Any]:
        """Return the view's combined architecture (view plus inheriting views)
        and the ir.ui.view record used.

        :param view_id: id of the view, or None
        :param str view_type: view type when view_id is None (``'form'``,
            ``'list'``, ...)
        :param options: ``mobile`` (bool) uses kanban instead of list views for
            x2many fields
        :rtype: tuple[_Element, Any]
        :raise UserError: if no view exists and no ``_get_default_<view_type>_view``
            method exists for the type
        """
        IrUiView = self.env["ir.ui.view"].sudo()

        # try to find a view_id if none provided
        if not view_id:
            # <view_type>_view_ref in context can be used to override the default view
            view_ref_key = view_type + "_view_ref"
            view_ref = self.env.context.get(view_ref_key)
            if view_ref:
                if "." in view_ref:
                    # Use the ormcached xmlid resolver (not a raw ir_model_data
                    # query) and warn instead of silently falling back when the
                    # reference is dangling or points to another model.
                    ref_model, ref_res_id = self.env[
                        "ir.model.data"
                    ]._xmlid_to_res_model_res_id(view_ref, raise_if_not_found=False)
                    if ref_model == "ir.ui.view":
                        view_id = ref_res_id
                    elif ref_model:
                        _logger.warning(
                            "%r=%r for model %s refers to a %s record, not an "
                            "ir.ui.view; falling back on the default view.",
                            view_ref_key,
                            view_ref,
                            self._name,
                            ref_model,
                        )
                    else:
                        _logger.warning(
                            "%r=%r for model %s does not match any record; "
                            "falling back on the default view.",
                            view_ref_key,
                            view_ref,
                            self._name,
                        )
                else:
                    _logger.warning(
                        "%r requires a fully-qualified external id (got: %r for model %s). "
                        "Please use the complete `module.view_id` form instead.",
                        view_ref_key,
                        view_ref,
                        self._name,
                    )

            if not view_id:
                # otherwise try to find the lowest priority matching ir.ui.view
                view_id = IrUiView.default_view(self._name, view_type)

        if view_id:
            # read the view with inherited views applied
            view = IrUiView.browse(view_id)
            arch = view._get_combined_arch()
        else:
            # fallback on default views methods if no ir.ui.view could be found
            view = IrUiView.browse()
            method = getattr(self, f"_get_default_{view_type}_view", None)
            if method is None:
                raise UserError(
                    _("No default view of type '%s' could be found!", view_type)
                )
            arch = method()
        return arch, view

    def _get_view_postprocessed(
        self, view: Any, arch: _Element, **options: Any
    ) -> tuple[str, dict[str, set[str]]]:
        """Return the post-processed view architecture and the fields it uses.

        Delegates to the view's ``postprocess_and_fields``: applies access
        control, field modifiers and tag logic, embeds x2many subviews, and
        collects the fields used across the view and its subviews.

        :param view: an ``ir.ui.view`` record
        :param arch: the view architecture as an etree node
        :param options: ``mobile`` (bool) uses kanban instead of list views for
            x2many fields
        :return: (post-processed arch as a string, {model: fields used})
        :rtype: tuple[str, dict[str, set[str]]]
        """
        return view.postprocess_and_fields(arch, model=self._name, **options)

    @api.model
    def _get_view_cache_key(
        self,
        view_id: int | None = None,
        view_type: str = "form",
        **options: Any,
    ) -> tuple:
        """Return the cache key for `_get_view_cache`.

        Meant to be overridden by models needing additional keys.

        :param view_id: id of the view, or None
        :param str view_type: view type when view_id is None (``'form'``, ...)
        :param options: ``mobile`` (bool) uses kanban instead of list views for
            x2many fields
        :rtype: tuple
        """
        # sorted: context insertion order must not leak into the cache key,
        # otherwise the same *_view_ref combination spelled in a different
        # order creates duplicate templates-cache entries
        return (
            view_id,
            view_type,
            options.get("mobile"),
            self.env.lang,
        ) + tuple(
            sorted(
                (key, value)
                for key, value in self.env.context.items()
                if key.endswith("_view_ref")
            )
        )

    @api.model
    @tools.conditional(
        "xml" not in config["dev_mode"],
        tools.ormcache(
            "self._get_view_cache_key(view_id, view_type, **options)",
            cache="templates",
        ),
    )
    def _get_view_cache(
        self,
        view_id: int | None = None,
        view_type: str = "form",
        **options: Any,
    ) -> frozendict:
        """Return the cacheable view information.

        The cached view is postprocessed for ALL groups, so group-restricted
        blocks must be removed after this call for users not in those groups.

        :param view_id: id of the view, or None
        :param str view_type: view type when view_id is None (``'form'``, ...)
        :param options: ``mobile`` (bool) uses kanban instead of list views for
            x2many fields
        :return: a frozendict with ``arch`` (postprocessed, all groups), ``id``,
            ``model``, and ``models`` (fields per model, including sub-views)
        :rtype: frozendict
        """
        arch, view = self._get_view(view_id, view_type, **options)
        arch, view_models = self._get_view_postprocessed(view, arch, **options)
        view_models = self._get_view_fields(view_type or view.type, view_models)
        result = {
            "arch": arch,
            # TODO: only `web_studio` seems to require this. I guess this is acceptable to keep it.
            "id": view.id,
            # TODO: only `web_studio` seems to require this. But this one on the other hand should be eliminated:
            # you just called `get_views` for that model, so obviously the web client already knows the model.
            "model": self._name,
            # frozendict + tuple so the cached value cannot be mutated.
            "models": frozendict(
                {model: tuple(fields) for model, fields in view_models.items()}
            ),
        }

        return frozendict(result)

    @api.model
    @api.readonly
    def get_view(
        self,
        view_id: int | None = None,
        view_type: str = "form",
        **options: Any,
    ) -> dict[str, Any]:
        """Return the detailed composition of the requested view (model, arch,
        inherited views and extensions).

        The result may only depend on the requested view types, access rights,
        view access rules, options, context lang and TYPE_view_ref (no other
        context values).

        :param view_id: id of the view, or None
        :param str view_type: view type when view_id is None (``'form'``, ...)
        :param options: ``mobile`` (bool) uses kanban instead of list views for
            x2many fields
        :rtype: dict[str, Any]
        :raise ValueError:

            * if an inherited view has a position other than 'before', 'after',
              'inside', 'replace'
            * if a tag other than 'position' is found in a parent view
        :raise ValidationError: if an inherited view has an invalid xpath
        """
        self.browse().check_access("read")

        result = dict(self._get_view_cache(view_id, view_type, **options))

        node = etree.fromstring(result["arch"])
        node = self.env["ir.ui.view"]._postprocess_access_rights(node)
        node = self.env["ir.ui.view"]._postprocess_debug(node)
        # No .replace("\t", "") here: the cached arch is already tab-stripped by
        # postprocess_and_fields, and neither postprocess step reintroduces tabs.
        result["arch"] = etree.tostring(node, encoding="unicode")

        return result

    @api.model
    def _get_view_fields(
        self, view_type: str, view_models: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the field names the web client needs to load the views, per view type.

        Meant to be overridden by modules requiring additional fields.

        :param str view_type: type of the view
        :param dict[str, Any] view_models: models and fields used in the arch
        :return: models and fields required by the web client for this view type
        :rtype: dict[str, Any]
        """
        match view_type:
            case "kanban" | "list" | "form":
                for model, model_fields in view_models.items():
                    model_fields.add("id")
                    if "write_date" in self.env[model]._fields:
                        model_fields.add("write_date")
            case "search":
                # a set, like every other branch (.update()/.add() on sets)
                view_models[self._name] = set(self._fields)
            case "graph":
                view_models[self._name].update(
                    fname
                    for fname, field in self._fields.items()
                    if field.type in ("integer", "float", "monetary")
                )
            case "pivot":
                view_models[self._name].update(
                    fname
                    for fname, field in self._fields.items()
                    if field._description_groupable(self.env)
                )
        return view_models

    @api.model
    def _get_view_field_attributes(self) -> list[str]:
        """Return the field attributes the web client needs to load the views.

        Meant to be overridden by modules requiring additional field attributes.

        :rtype: list[str]
        """
        return [
            "change_default",
            "context",
            "currency_field",
            "definition_record",
            "definition_record_field",
            "digits",
            "min_display_digits",
            "domain",
            "aggregator",
            "groups",
            "help",
            "model_field",
            "name",
            "readonly",
            "related",
            "relation",
            "relation_field",
            "required",
            "searchable",
            "selection",
            "size",
            "sortable",
            "store",
            "string",
            "translate",
            "trim",
            "type",
            "groupable",
            "falsy_value_label",
        ]

    @api.readonly
    def get_formview_id(self, access_uid: int | None = None) -> int | bool:
        """Return a view id to open the document ``self`` with.

        Meant to be overridden in addons giving specific view ids.

        :param access_uid: the user accessing the form view, if different from
            the current environment user
        """
        return False

    @api.readonly
    def get_formview_action(self, access_uid: int | None = None) -> dict[str, Any]:
        """Return an action to open the document ``self``.

        Meant to be overridden in addons giving specific view ids.

        :param access_uid: the user accessing the document, if different from the
            current user
        """
        view_id = self.sudo().get_formview_id(access_uid=access_uid)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "views": [(view_id, "form")],
            "target": "current",
            "res_id": self.id,
            "context": dict(self.env.context),
        }

    def _get_records_action(self, **kwargs: Any) -> dict[str, Any]:
        """Return an action to open the given records: a list for several, a
        form otherwise. Keyword arguments override the defaults.
        """
        match self.ids:  # `self.ids` will silently filter out new records (`NewId`s)
            case []:
                length_dependent = {"views": [(False, "form")]}
            case [res_id]:
                length_dependent = {
                    "views": [(False, "form")],
                    "res_id": res_id,
                }
            case ids:
                length_dependent = {
                    "views": [(False, "list"), (False, "form")],
                    "domain": [("id", "in", ids)],
                }
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "target": "current",
            "context": dict(self.env.context),
            **length_dependent,
            **kwargs,
        }

    @api.model
    def _onchange_spec(
        self, view_info: dict[str, Any] | None = None
    ) -> dict[str, str | None]:
        """Return the onchange spec from a view description; defaults to
        ``self.get_view()`` when *view_info* is not given.
        """
        result = {}

        def process(node: _Element, info: dict[str, Any] | None, prefix: str) -> None:
            if node.tag == "field":
                name = node.attrib["name"]
                names = f"{prefix}.{name}" if prefix else name
                if not result.get(names):
                    result[names] = node.attrib.get("on_change")
                # traverse the subviews included in relational fields
                for child_view in _xpath_descendant_field(node):
                    process(child_view, None, names)
            else:
                for child in node:
                    process(child, info, prefix)

        if view_info is None:
            view_info = self.get_view()
        process(etree.fromstring(view_info["arch"]), view_info, "")
        return result

    @api.model
    def _get_fields_spec(
        self, view_info: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Return the fields specification from a view description; defaults to
        ``self.get_view()`` when *view_info* is not given.
        """

        def fill_spec(node: _Element, model: Any, fields_spec: dict[str, Any]) -> None:
            if node.tag == "field":
                field_name = node.attrib["name"]
                field_spec = fields_spec.setdefault(field_name, {})
                field = model._fields.get(field_name)
                if field is not None:
                    sub_fields_spec = {}
                    if field.type == "many2one":
                        sub_fields_spec.setdefault("display_name", {})
                    if field.relational:
                        comodel = model.env[field.comodel_name]
                        for child in node:
                            fill_spec(child, comodel, sub_fields_spec)
                    if field.type == "one2many":
                        sub_fields_spec.pop(field.inverse_name, None)
                    if sub_fields_spec:
                        field_spec.setdefault("fields", {}).update(sub_fields_spec)
            else:
                for child in node:
                    fill_spec(child, model, fields_spec)

        if view_info is None:
            view_info = self.get_view()

        result = {}
        fill_spec(etree.fromstring(view_info["arch"]), self, result)
        return result
