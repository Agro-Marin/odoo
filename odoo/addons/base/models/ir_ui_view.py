import ast
import collections
import functools
import inspect
import logging
import pprint
import re
import types
import typing
import uuid
from collections.abc import Callable, Collection
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Self

from lxml import etree
from lxml.builder import E
from lxml.etree import _Element
from markupsafe import Markup

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import (
    AccessError,
    MissingError,
    UserError,
    ValidationError,
)
from odoo.fields import Domain
from odoo.modules.module import get_resource_from_path
from odoo.tools import SQL, _, config, frozendict, partition, unique
from odoo.tools.convert import _fix_multiple_roots
from odoo.tools.misc import ConstantMapping, file_path
from odoo.tools.template_inheritance import apply_inheritance_specs, locate_node
from odoo.tools.translate import TRANSLATED_ATTRS, xml_translate
from odoo.tools.view_validation import (
    att_names,
    check_class_accessibility,
    check_dropdown_menu,
    check_fa_class_accessibility,
    check_progress_bar,
    get_dict_asts,
    get_domain_value_names,
    get_expression_field_names,
    valid_view,
)

from .ir_ui_view_name_manager import NameManager

if TYPE_CHECKING:
    from collections.abc import Sequence

_logger = logging.getLogger(__name__)

MOVABLE_BRANDING = [
    "data-oe-model",
    "data-oe-id",
    "data-oe-field",
    "data-oe-xpath",
    "data-oe-source-id",
]
VIEW_MODIFIERS = ("column_invisible", "invisible", "readonly", "required")

# Attributes on a <calendar> view whose value names a field on the view's model.
# Shared by calendar postprocessing and validation to keep them in sync.
CALENDAR_DATE_ATTRS = ("date_start", "date_delay", "date_stop", "color", "all_day")

# View types embeddable as a nested subview under a relational field node.
# Shared by _postprocess_tag_field and _validate_tag_field.
_NESTED_VIEW_TAGS = frozenset({"form", "list", "graph", "kanban", "calendar"})

# Writing any of these fields changes how views resolve into combined archs or
# compiled templates, so it must invalidate the "templates" ormcache. Other
# fields (name, arch_prev, arch_updated, arch_fs, ...) leave templates valid.
_TEMPLATE_CACHE_FIELDS = frozenset(
    {
        "arch",
        "arch_base",
        "arch_db",
        "active",
        "inherit_id",
        "mode",
        "priority",
        "key",
        "model",
        "group_ids",
    }
)

# `__comp__` is a reserved keyword in the owl template generated from an arch,
# giving access to the component instance. Forbid it in dynamic attributes so
# implementation details don't leak into archs.
COMP_REGEX = re.compile(r"(^|[^\w])\s*__comp__\s*([^\w]|$)")

ref_re = re.compile(
    r"""
# first match 'form_view_ref' key, backrefs are used to handle single or
# double quoting of the value
(['"])(?P<view_type>\w+_view_ref)\1
# colon separator (with optional spaces around)
\s*:\s*
# open quote for value
(['"])
(?P<view_id>
    # we'll just match stuff which is normally part of an xid:
    # word and "." characters
    [.\w]+
)
# close with same quote as opening
\3
""",
    re.VERBOSE,
)


def _hasclass(context: Any, *cls: str) -> bool:
    """Checks if the context node has all the classes passed as arguments"""
    node_classes = set(context.context_node.attrib.get("class", "").split())
    return node_classes.issuperset(cls)


# Suffix appended to a view's xmlid when it is created from a model that
# inherits ir.ui.view (see the _inherits parent-xmlid generation in
# odoo/orm/models/mixins/load.py).
_IR_UI_VIEW_XMLID_SUFFIX = "_ir_ui_view"


def get_view_arch_from_file(filepath: str, xmlid: str) -> str | None:
    """Return the arch of the view identified by ``xmlid`` inside ``filepath``.

    The file is parsed only once, even when the lookup follows ``view_id``
    references to other records in the same file.
    """
    return _extract_view_arch(etree.parse(filepath), xmlid, filepath)


def _extract_view_arch(
    document: etree._ElementTree, xmlid: str, filepath: str
) -> str | None:
    if "." not in xmlid:
        raise ValueError(f"Invalid xmlid {xmlid!r}: expected 'module.name' format")
    module, view_id = xmlid.split(".", 1)

    # Candidate id values to match. They are passed to xpath() as variables
    # (never string-interpolated) so that a quote in an id cannot corrupt the
    # expression.
    candidate_ids = [xmlid, view_id]
    # when a view is created from a model that inherits ir.ui.view, the xmlid
    # has been suffixed by '_ir_ui_view'; also search without that suffix.
    if view_id.endswith(_IR_UI_VIEW_XMLID_SUFFIX):
        end = -len(_IR_UI_VIEW_XMLID_SUFFIX)
        candidate_ids += [xmlid[:end], view_id[:end]]

    predicate = " or ".join(f"@id=$id{i}" for i in range(len(candidate_ids)))
    variables = {f"id{i}": value for i, value in enumerate(candidate_ids)}

    for node in document.xpath(f"//*[{predicate}]", **variables):
        if node.tag == "record":
            field_arch = node.find('field[@name="arch"]')
            if field_arch is not None:
                _fix_multiple_roots(field_arch)
                inner = "".join(
                    etree.tostring(child, encoding="unicode")
                    for child in field_arch.iterchildren()
                )
                return (field_arch.text or "") + inner

            field_view = node.find('field[@name="view_id"]')
            if field_view is not None:
                ref = field_view.attrib.get("ref")
                if ref is None:
                    return None
                ref_module, _, ref_view_id = ref.rpartition(".")
                ref_xmlid = f"{ref_module or module}.{ref_view_id}"
                # reuse the already-parsed document instead of re-reading the file
                return _extract_view_arch(document, ref_xmlid, filepath)

            return None

        elif node.tag == "template":
            # The following dom operations has been copied from convert.py's _tag_template()
            if not node.get("inherit_id"):
                node.set("t-name", xmlid)
                node.tag = "t"
            else:
                node.tag = "data"
            node.attrib.pop("id", None)
            return etree.tostring(node, encoding="unicode")

    _logger.warning(
        "Could not find view arch definition in file '%s' for xmlid '%s'",
        filepath,
        xmlid,
    )
    return None


xpath_utils = etree.FunctionNamespace(None)
xpath_utils["hasclass"] = _hasclass

TRANSLATED_ATTRS_RE = re.compile(rf"@({'|'.join(TRANSLATED_ATTRS)})\b")
WRONGCLASS = re.compile(r"(@class\s*=|=\s*@class|contains\(@class)")

# XML encoding declaration, e.g. <?xml version="1.0" encoding="utf-8"?>.
_XML_ENCODING_DECL_RE = re.compile(r"<\?xml[^>]*encoding=.*?\?>", re.IGNORECASE)

# External-id reference inside a file arch, e.g. %(module.record)s or %(record)d.
_ARCH_FS_REF_RE = re.compile(r"(?<!%)%\((?P<xmlid>.*?)\)[ds]")

# Tooltip-related attribute forbidden in archs (optionally t-att-/t-attf- prefixed).
_TOOLTIP_ATTR_RE = re.compile(r"^(t-att-|t-attf-)?data-tooltip(-template|-info)?$")

# Owl/qweb directives allowed to appear verbatim in an arch (matched prefix-
# anchored). Views compiling to an owl template (kanban) accept the extended set.
_QWEB_DIRECTIVES_ALLOWED = re.compile(r"t-translation")
_QWEB_DIRECTIVES_ALLOWED_TEMPLATE = re.compile(
    r"t-(?:translation|name|esc|out|set|value|if|else|elif|foreach|as|key|att|call|debug)"
)

# Pre-compiled XPath expressions for view-processing hot paths. ETXPath objects
# are document-independent and thread-safe, so they can be module-level constants.
_xpath_position = etree.ETXPath("//*[@position]")
_xpath_attrs = etree.ETXPath("//*[@attrs]")
_xpath_states = etree.ETXPath("//*[@states]")
_xpath_validate = etree.ETXPath("//*[@__validate__]")
_xpath_groups_key = etree.ETXPath("//*[@__groups_key__]")
_xpath_model_access = etree.ETXPath("//*[@model_access_rights]")
_xpath_groups = etree.ETXPath("//*[@groups]")
_xpath_debug = etree.ETXPath("//*[@__debug__]")
_xpath_descendant_field = etree.ETXPath("./*[descendant::field]")


class IrUiView(models.Model):
    _name = "ir.ui.view"
    _description = "View"
    _order = "priority,name,id"
    _allow_sudo_commands = False

    name = fields.Char(string="View Name", required=True)
    model = fields.Char(index=True)
    key = fields.Char(index="btree_not_null")
    priority = fields.Integer(string="Sequence", default=16, required=True)
    type = fields.Selection(
        [
            ("list", "List"),
            ("form", "Form"),
            ("graph", "Graph"),
            ("pivot", "Pivot"),
            ("calendar", "Calendar"),
            ("kanban", "Kanban"),
            ("search", "Search"),
            ("qweb", "QWeb"),
        ],
        string="View Type",
    )
    arch = fields.Text(
        compute="_compute_arch",
        inverse="_inverse_arch",
        string="View Architecture",
        help="""This field should be used when accessing view arch. It will use translation.
                               Note that it will read `arch_db` or `arch_fs` if in dev-xml mode.""",
    )
    arch_base = fields.Text(
        compute="_compute_arch_base",
        inverse="_inverse_arch_base",
        string="Base View Architecture",
        help="This field is the same as `arch` field without translations",
    )
    arch_db = fields.Text(
        string="Arch Blob",
        translate=xml_translate,
        help="This field stores the view arch.",
    )
    arch_fs = fields.Char(
        string="Arch Filename",
        help="""File from where the view originates.
                                                          Useful to (hard) reset broken views or to read arch from file in dev-xml mode.""",
    )
    arch_updated = fields.Boolean(string="Modified Architecture")
    arch_prev = fields.Text(
        string="Previous View Architecture",
        help="""This field will save the current `arch_db` before writing on it.
                                                                         Useful to (soft) reset a broken view.""",
    )
    inherit_id = fields.Many2one(
        "ir.ui.view", string="Inherited View", ondelete="restrict", index=True
    )
    inherit_children_ids = fields.One2many(
        "ir.ui.view", "inherit_id", string="Views which inherit from this one"
    )
    model_data_id = fields.Many2one(
        "ir.model.data",
        string="Model Data",
        compute="_compute_model_data_id",
        search="_search_model_data_id",
    )
    xml_id = fields.Char(
        string="External ID",
        compute="_compute_model_data_id",
        help="ID of the view defined in xml file",
    )
    group_ids = fields.Many2many(
        "res.groups",
        "ir_ui_view_group_rel",
        "view_id",
        "group_id",
        string="Groups",
        help="If this field is empty, the view applies to all users. Otherwise, the view applies to the users of those groups only.",
    )
    mode = fields.Selection(
        [("primary", "Base view"), ("extension", "Extension View")],
        string="View inheritance mode",
        default="primary",
        required=True,
        help="Only applies if this view inherits from an other one"
        " (inherit_id is not False/Null).\n\n"
        "* if extension (default), if this view is requested the closest primary view"
        " is looked up (via inherit_id), then all views inheriting from it with this"
        " view's model are applied\n"
        "* if primary, the closest primary view is fully resolved (even if it uses a"
        " different model than this one), then this view's inheritance specs"
        " (<xpath/>) are applied, and the result is used as if it were this view's"
        " actual arch.",
    )

    warning_info = fields.Html(
        string="Warning information", compute="_compute_warning_info"
    )

    # The "active" field is not updated on <template>-defined views (see
    # _tag_template). Don't rely on it for qweb views anyway: COW-duplicated
    # frontend views always need upgrade scripts to change their "active" default.
    active = fields.Boolean(
        default=True,
        help="If this view is inherited,\n\n"
        "* if True, the view always extends its parent\n"
        "* if False, the view currently does not extend its parent but can be enabled",
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Model of the view",
        compute="_compute_model_id",
        inverse="_inverse_compute_model_id",
    )

    invalid_locators = fields.Json(compute="_compute_invalid_locators")

    @api.depends("arch_db", "arch_fs", "arch_updated")
    @api.depends_context(
        "read_arch_from_file", "lang", "edit_translations", "check_translations"
    )
    def _compute_arch(self) -> None:
        def resolve_external_ids(arch_fs: str, view_xml_id: str) -> str:
            def replacer(m: re.Match[str]) -> str:
                xmlid = m.group("xmlid")
                if "." not in xmlid:
                    xmlid = f"{view_xml_id.split('.', maxsplit=1)[0]}.{xmlid}"
                return str(self.env["ir.model.data"]._xmlid_to_res_id(xmlid))

            # Negative look-behind on '%' leaves an escaped "%%(...)" untouched.
            return _ARCH_FS_REF_RE.sub(replacer, arch_fs)

        lang = self.env.lang or "en_US"
        env_en = self.with_context(
            edit_translations=None, lang="en_US", check_translations=True
        ).env
        env_lang = self.with_context(lang=lang, check_translations=True).env
        field_arch_db = self._fields["arch_db"]
        read_from_file_ctx = self.env.context.get("read_arch_from_file")
        dev_xml = "xml" in config["dev_mode"]
        for view in self:
            arch_fs = None
            read_file = read_from_file_ctx or (dev_xml and not view.arch_updated)
            if read_file and view.arch_fs and (view.xml_id or view.key):
                xml_id = view.xml_id or view.key
                try:
                    # reading the file will raise an OSError if it is unreadable
                    arch_fs = get_view_arch_from_file(
                        file_path(view.arch_fs, check_exists=False), xml_id
                    )
                except OSError:
                    _logger.warning(
                        "View %s: Full path [%s] cannot be found.",
                        xml_id,
                        view.arch_fs,
                    )
                    arch_fs = False

                # replace %(xml_id)s, %(xml_id)d, %%(xml_id)s, %%(xml_id)d by the res_id
                if arch_fs:
                    arch_fs = resolve_external_ids(arch_fs, xml_id).replace("%%", "%")
                    translation_dictionary = field_arch_db.get_translation_dictionary(
                        view.with_env(env_en).arch_db,
                        {lang: view.with_env(env_lang).arch_db},
                    )
                    arch_fs = field_arch_db.translate(
                        lambda term, td=translation_dictionary, _lang=lang: td[term][
                            _lang
                        ],
                        arch_fs,
                    )
            view.arch = arch_fs or view.arch_db

    def _inverse_arch(self) -> None:
        for view in self:
            self._validate_xml_encoding(view.arch)
            data = {"arch_db": view.arch}
            if "install_filename" in self.env.context:
                # we store the relative path to the resource instead of the absolute path, if found
                # (it will be missing e.g. when importing data-only modules using base_import_module)
                path_info = get_resource_from_path(self.env.context["install_filename"])
                if path_info:
                    data["arch_fs"] = "/".join(path_info[0:2])
                    data["arch_updated"] = False
            view.write(data)
            # the xml_translate will clean the arch_db when write (e.g. ('<div>') -> ('<div></div>'))
            # view.arch should be reassigned here
            view.arch = view.arch_db
        # 'arch' depends on the context and was implicitly modified in all
        # languages; invalidate so no stale value survives in another env.
        self.invalidate_recordset(["arch"])

    @api.depends("arch")
    @api.depends_context("read_arch_from_file")
    def _compute_arch_base(self) -> None:
        # 'arch_base' is the same as 'arch' without translation
        for view, view_wo_lang in zip(self, self.with_context(lang=None), strict=True):
            view.arch_base = view_wo_lang.arch

    def _inverse_arch_base(self) -> None:
        for view, view_wo_lang in zip(self, self.with_context(lang=None), strict=True):
            self._validate_xml_encoding(view.arch_base)
            view_wo_lang.arch = view.arch_base

    def reset_arch(self, mode: str = "soft") -> None:
        """Reset the view arch to its previous arch (soft) or its XML file arch
        if exists (hard).
        """
        for view in self:
            arch = False
            write_dict = None
            if mode == "soft":
                arch = view.arch_prev
                write_dict = {"arch_db": arch}
            elif mode == "hard" and view.arch_fs:
                arch = view.with_context(read_arch_from_file=True, lang=None).arch
                write_dict = {
                    "arch_db": arch,
                    "arch_prev": False,
                    "arch_updated": False,
                }
            if arch and write_dict:
                # Don't save current arch in previous since we reset, this arch is probably broken
                view.with_context(no_save_prev=True, lang=None).write(write_dict)

    def _get_ir_model_data_rows(self) -> dict[int, list[dict[str, Any]]]:
        """Return the ir.model.data rows pointing at the views in ``self``,
        grouped by ``res_id`` and kept in ir.model.data._order.

        Used by :meth:`_compute_model_data_id` to assign ``model_data_id`` and
        ``xml_id`` from the same rows, so they agree on which external id wins.
        """
        rows_by_view: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        domain = [("model", "=", "ir.ui.view"), ("res_id", "in", self.ids)]
        for data in (
            self.env["ir.model.data"]
            .sudo()
            .search_read(domain, ["module", "name", "res_id"])
        ):
            rows_by_view[data["res_id"]].append(data)
        return rows_by_view

    @api.depends("write_date")
    def _compute_model_data_id(self) -> None:
        # Compute model_data_id and xml_id together from the same query so they
        # can't disagree (first row per view wins).
        rows_by_view = self._get_ir_model_data_rows()
        for view in self:
            rows = rows_by_view.get(view.id)
            view.model_data_id = rows[0]["id"] if rows else False
            view.xml_id = f"{rows[0]['module']}.{rows[0]['name']}" if rows else ""

    def _search_model_data_id(
        self, operator: str, value: Any
    ) -> list[tuple[str, str, Any]] | types.NotImplementedType:
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        name = "name" if isinstance(value, str) else "id"
        domain = [("model", "=", "ir.ui.view"), (name, operator, value)]
        query = self.env["ir.model.data"].sudo()._search(domain)
        return [("id", "in", query.subselect("res_id"))]

    @api.depends("model")
    def _compute_model_id(self) -> None:
        for record in self:
            record.model_id = self.env["ir.model"]._get(record.model)

    def _inverse_compute_model_id(self) -> None:
        for record in self:
            record.model = record.model_id.model

    @api.depends("arch", "inherit_id")
    def _compute_invalid_locators(self) -> None:
        def assess_locator(source: _Element, spec: _Element) -> dict[str, Any] | None:
            node = None
            with suppress(ValidationError):  # Syntax error
                # If locate_node returns None here:
                # Invalid expression: Ok Syntax, but cannot be anchored to the parent view.
                node = self.locate_node(source, spec)

            if node is None:
                return {
                    "tag": spec.tag,
                    "attrib": dict(spec.attrib),
                    "sourceline": spec.sourceline,
                }
            return None

        self.invalid_locators = False
        for view in self:
            if not view.inherit_id or not view.arch:
                continue
            try:
                # An ancestor arch may be invalid (e.g. a bad xpath forced in via
                # SQL or during upgrade); don't raise, keep using the form view.
                source = view.with_context(
                    ir_ui_view_tree_cut_off_view=view
                )._get_combined_arch()
            except (
                ValidationError,
                ValueError,
            ):  # invalid xpath syntax, or xpath element not found
                # Flag the field with debugging info; it must be non-falsy to
                # display in the Form view.
                view.invalid_locators = [{"broken_hierarchy": True}]
                continue

            invalid_locators = []
            specs = collections.deque([etree.fromstring(view.arch)])
            while specs:
                spec = specs.popleft()
                if isinstance(spec, etree._Comment):
                    continue
                if spec.tag == "data":
                    specs.extend(spec)
                    continue

                if invalid_locator := assess_locator(source, spec):
                    invalid_locators.append(invalid_locator)
                else:
                    position, mode = spec.get("position"), spec.get("mode")
                    for sub_spec in spec:
                        sub_position = sub_spec.get("position")
                        if sub_position == "move" and (
                            position != "replace" or mode != "inner"
                        ):
                            if invalid_move := assess_locator(source, sub_spec):
                                invalid_locators.append(invalid_move)
                        elif sub_position:
                            invalid_locators.append(
                                {
                                    "tag": sub_spec.tag,
                                    "attrib": dict(sub_spec.attrib),
                                    "sourceline": sub_spec.sourceline,
                                }
                            )

                    # Subsequent xpaths may depend on previous ones, so apply the
                    # spec. ValueError signals an invalid spec; ignore it here.
                    with suppress(ValueError):
                        source = apply_inheritance_specs(source, spec)
            view.invalid_locators = invalid_locators or False

    def _valid_inheritance(self, arch: _Element) -> None:
        """Check whether view inheritance is based on translated attribute."""
        for node in _xpath_position(arch):
            # inheritance may not use a translated attribute as selector
            if node.tag == "xpath":
                match = TRANSLATED_ATTRS_RE.search(node.get("expr", ""))
                if match:
                    message = f"View inheritance may not use attribute {match.group(1)!r} as a selector."
                    self._raise_view_error(message, node)
                if WRONGCLASS.search(node.get("expr", "")):
                    _logger.warning(
                        "Error-prone use of @class in view %s (%s): use the "
                        "hasclass(*classes) function to filter elements by "
                        "their classes",
                        self.name,
                        self.xml_id,
                    )
            else:
                for attr in TRANSLATED_ATTRS:
                    if node.get(attr):
                        message = f"View inheritance may not use attribute {attr!r} as a selector."
                        self._raise_view_error(message, node)

    def _check_xml(self) -> bool:
        # Sanity checks: the view should not break anything upon rendering!
        # Any exception raised below will cause a transaction rollback.
        partial_validation = self.env.context.get("ir_ui_view_partial_validation")
        views = self.with_context(
            validate_view_ids=(self._ids if partial_validation else True)
        )

        for view in views:
            if partial_validation and not view.arch:
                continue
            try:
                # verify the view is valid xml and that the inheritance resolves
                if view.inherit_id:
                    view_arch = etree.fromstring(view.arch or "<data/>")
                    view._valid_inheritance(view_arch)

                combined_arch = view._get_combined_arch()

                # check that the primary views extending this current view can
                # still be combined (skippable to avoid marking too many views
                # as failed during an upgrade)
                if not self.env.context.get("_skip_primary_extensions_check") and (
                    view.inherit_id or view.inherit_children_ids
                ):
                    self._check_sibling_primary_views(view)

                if view.type == "qweb":
                    continue
            except (etree.ParseError, ValueError) as e:
                err = ValidationError(
                    _(
                        "Error while parsing or validating view (%(view)s):\n\n%(error)s",
                        error=e,
                        view=view.key or view.id,
                    )
                ).with_traceback(e.__traceback__)
                err.context = getattr(e, "context", None)
                raise err from None

            try:
                # verify that all fields used are valid, etc.
                view._validate_view(combined_arch, view.model)

                if _xpath_attrs(combined_arch) or _xpath_states(combined_arch):
                    view_name = view._view_display_name()
                    err = ValidationError(
                        _(
                            'Since 17.0, the "attrs" and "states" attributes are no longer used.\nView: %(name)s in %(file)s',
                            name=view_name,
                            file=view.arch_fs,
                        )
                    )
                    err.context = {"name": "invalid view"}
                    raise err

                # A <data> element wraps multiple root nodes: validate each of
                # its children; otherwise validate the single root node.
                if combined_arch.tag == "data":
                    view_archs = list(combined_arch)
                else:
                    view_archs = [combined_arch]
                for view_arch in view_archs:
                    for node in _xpath_validate(view_arch):
                        del node.attrib["__validate__"]
                    check = valid_view(view_arch, env=self.env, model=view.model)
                    if not check:
                        view_name = view._view_display_name()
                        raise ValidationError(
                            _(
                                "Invalid view %(name)s definition in %(file)s",
                                name=view_name,
                                file=view.arch_fs,
                            )
                        )
            except ValueError as e:
                self._reraise_view_validation_error(e, view, combined_arch)

        return True

    def _reraise_view_validation_error(
        self, error: ValueError, view: Self, combined_arch: _Element
    ) -> typing.NoReturn:
        """Re-raise a ``_validate_view`` failure as a ``ValidationError``,
        preserving the original error's location context and traceback.

        Three error shapes are handled, in order: an error carrying a ``context``
        dict with a ``line`` (quote the arch lines around it); an error wrapping
        another exception (surface that cause); otherwise report it as-is.
        """
        if hasattr(error, "context"):
            lines = etree.tostring(combined_arch, encoding="unicode").splitlines(
                keepends=True
            )
            fivelines = "".join(
                lines[max(0, error.context["line"] - 3) : error.context["line"] + 2]
            )
            err = ValidationError(
                _(
                    "Error while validating view near:\n\n%(fivelines)s\n%(error)s",
                    fivelines=fivelines,
                    error=error,
                )
            )
            err.context = error.context
            raise err.with_traceback(error.__traceback__) from None
        if error.__context__:
            err = ValidationError(
                _(
                    "Error while validating view (%(view)s):\n\n%(error)s",
                    view=view.key or view.id,
                    error=error.__context__,
                )
            )
            err.context = {"name": "invalid view"}
            raise err.with_traceback(error.__context__.__traceback__) from None
        raise ValidationError(
            _(
                "Error while validating view (%(view)s):\n\n%(error)s",
                view=view.key or view.id,
                error=error,
            )
        ) from None

    def _check_sibling_primary_views(self, view: Self) -> None:
        """Verify that the primary views extending ``view`` (or a view on its
        ancestor chain) can still be combined, raising otherwise.

        Called from :meth:`_check_xml`; ``self`` is the ``_check_xml`` receiver
        and ``view`` the view being checked.
        """
        root = view
        while root.inherit_id and root.mode != "primary":
            root = root.inherit_id
        sibling_primary_views = self.env["ir.ui.view"]
        stack = [root]
        while stack:
            root = stack.pop()
            for child in root.inherit_children_ids:
                if child.mode == "primary":
                    sibling_primary_views += child
                else:
                    stack.append(child)

        # During an upgrade, we can only use the views that have been
        # fully upgraded already.
        if self.pool._init and sibling_primary_views and self.pool._init_modules:
            sibling_primary_views = sibling_primary_views._filter_loaded_views(
                include_loaded_xmlids=True
            )

        # Check if we know how to apply inheritances
        sibling_primary_views._get_combined_archs()

    @api.constrains("group_ids", "inherit_id", "mode")
    def _check_groups(self) -> None:
        for view in self:
            if view.group_ids and view.inherit_id and view.mode != "primary":
                raise ValidationError(
                    _(
                        "Inherited view cannot have 'Groups' define on the record. Use 'groups' attributes inside the view definition"
                    )
                )

    @api.constrains("inherit_id")
    def _check_000_inheritance(self) -> None:
        # Constraint methods run alphabetically; this must run before the others
        # to avoid an infinite loop in `_get_combined_arch`.
        if self._has_cycle("inherit_id"):
            raise ValidationError(_("You cannot create recursive inherited views."))

    _inheritance_mode = models.Constraint(
        "CHECK (mode != 'extension' OR inherit_id IS NOT NULL)",
        "Invalid inheritance mode: if the mode is 'extension', the view must extend an other view",
    )
    _qweb_required_key = models.Constraint(
        "CHECK (type != 'qweb' OR key IS NOT NULL)",
        "Invalid key: QWeb view should have a key",
    )
    _model_type_inherit_id = models.Index("(model, inherit_id)")

    def _compute_defaults(self, values: dict[str, Any]) -> dict[str, Any]:
        if "inherit_id" in values:
            # Do not automatically change the mode if the view already has an inherit_id,
            # and the user change it to another.
            if not values["inherit_id"] or all(not view.inherit_id for view in self):
                values.setdefault(
                    "mode", "extension" if values["inherit_id"] else "primary"
                )
        return values

    @api.depends("arch")
    def _compute_warning_info(self) -> None:
        for view in self:
            view.warning_info = ""
            if not view.arch:
                continue
            try:
                if view.inherit_id:
                    view_arch = etree.fromstring(view.arch)
                    view._valid_inheritance(view_arch)
                combined_arch = view._get_combined_arch()
                if view.type != "qweb":
                    name_manager = view._postprocess_view(
                        combined_arch, view.model, preserve_groups=True
                    )
                    view.warning_info = name_manager.warning
            except (etree.ParseError, ValueError) as e:
                view.warning_info = str(e)

    def _group_inconsistency_warning(
        self, name_manager: NameManager, missing_fields: dict[str, Any]
    ) -> Markup:
        """Assemble the "access rights inconsistency" HTML shown in
        ``warning_info`` from the fields postprocessing had to append because
        they were missing.
        """
        warning = Markup("")
        for name, (missing_groups, reasons) in missing_fields.items():
            error_message = name_manager._error_message_group_inconsistency(
                name, missing_groups, reasons
            )[0]
            if error_message:
                if warning:
                    warning += Markup("<br/>\n<br/>\n")
                warning += error_message.replace("\n", Markup("<br/>\n"))
        return warning

    def _validate_xml_encoding(self, text: str | None) -> None:
        if isinstance(text, str) and _XML_ENCODING_DECL_RE.search(text):
            raise UserError(
                _(
                    "Unicode strings with encoding declaration are not supported in XML.\n"
                    "Remove the encoding declaration."
                )
            )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        if not vals_list:
            # nothing to create: don't wipe the registry-wide templates cache
            return self.browse()
        # single source of truth for the valid view types (see _editable_node)
        valid_types = self._get_view_type_tags()
        # Prefetch parent view types in batch to avoid N+1 queries
        inherit_ids = {
            v["inherit_id"]
            for v in vals_list
            if v.get("inherit_id") and not v.get("type")
        }
        parent_types = {}
        if inherit_ids:
            parents = self.browse(inherit_ids)
            parent_types = {p.id: p.type for p in parents}

        for values in vals_list:
            if "arch_db" in values and not values["arch_db"]:
                # delete empty arch_db to avoid triggering _check_xml before _inverse_arch_base is called
                del values["arch_db"]

            if not values.get("type"):
                if values.get("inherit_id"):
                    values["type"] = parent_types.get(values["inherit_id"])
                else:
                    try:
                        if not values.get("arch") and not values.get("arch_base"):
                            raise ValidationError(_("Missing view architecture."))
                        values["type"] = etree.fromstring(
                            values.get("arch") or values.get("arch_base")
                        ).tag
                        if values["type"] not in valid_types:
                            raise ValidationError(
                                _(
                                    "Invalid view type: '%(view_type)s'.\n"
                                    "You might have used an invalid starting tag in the architecture.\n"
                                    "Allowed types are: %(valid_types)s",
                                    view_type=values["type"],
                                    valid_types=", ".join(sorted(valid_types)),
                                )
                            )
                    except etree.ParseError, ValueError:
                        # don't raise here, the explicit `self._check_xml()`
                        # call right after create() will do the job properly.
                        pass
            if not values.get("key") and values.get("type") == "qweb":
                values["key"] = f"gen_key.{str(uuid.uuid4())[:6]}"
            if not values.get("name"):
                model = values.get("model")
                values["name"] = (
                    f"{model} {values['type']}" if model else values["type"]
                )
            # Create might be called with either `arch` (xml files), `arch_base` (form view) or `arch_db`.
            values["arch_prev"] = (
                values.get("arch_base") or values.get("arch_db") or values.get("arch")
            )
            # write on arch: bypass _inverse_arch()
            if "arch" in values:
                values["arch_db"] = values.pop("arch")
                if "install_filename" in self.env.context:
                    # we store the relative path to the resource instead of the absolute path, if found
                    # (it will be missing e.g. when importing data-only modules using base_import_module)
                    path_info = get_resource_from_path(
                        self.env.context["install_filename"]
                    )
                    if path_info:
                        values["arch_fs"] = "/".join(path_info[0:2])
                        values["arch_updated"] = False
            self._compute_defaults(values)

        self.env.registry.clear_cache("templates")
        result = super().create(vals_list)
        result.with_context(ir_ui_view_partial_validation=True)._check_xml()
        return result

    def write(self, vals: dict[str, Any]) -> bool:
        # Keep track if view was modified. That will be useful for the --dev mode
        # to prefer modified arch over file arch.
        if (
            "arch_updated" not in vals
            and ("arch" in vals or "arch_base" in vals)
            and "install_filename" not in self.env.context
        ):
            vals["arch_updated"] = True

        # These are exactly the fields that change how a view resolves into a
        # combined arch / compiled template (see _TEMPLATE_CACHE_FIELDS).
        if _TEMPLATE_CACHE_FIELDS.intersection(vals):
            # Drop view customizations (e.g. dashboards), else not all users see
            # the update. A customization is an alternate arch, so it only goes
            # stale when the resolved arch changes; a pure metadata write must
            # not silently discard it.
            custom_view = (
                self.env["ir.ui.view.custom"]
                .sudo()
                .search([("ref_id", "in", self.ids)])
            )
            if custom_view:
                custom_view.unlink()

            self.env.registry.clear_cache("templates")
        if "arch_db" in vals and not self.env.context.get("no_save_prev"):
            for view in self:
                super(IrUiView, view).write({"arch_prev": view.arch_db})

        res = super().write(self._compute_defaults(vals))

        # Check the xml of the view if it gets re-activated or changed.
        if "active" in vals or "arch_db" in vals or "inherit_id" in vals:
            self._check_xml()

        return res

    def unlink(self) -> bool:
        if not self:
            # nothing to unlink: don't wipe the registry-wide templates cache
            return True
        # if in uninstall mode and has children views, emulate an ondelete cascade
        if self.env.context.get("_force_unlink", False) and self.inherit_children_ids:
            self.inherit_children_ids.unlink()
        self.env.registry.clear_cache("templates")
        return super().unlink()

    def _update_field_translations(
        self,
        field_name: str,
        translations: dict[str, str | typing.Literal[False] | dict[str, str]],
        digest: Callable[[str], str] | None = None,
        source_lang: str = "",
    ) -> bool:
        return super(
            IrUiView, self.with_context(no_save_prev=True)
        )._update_field_translations(
            field_name, translations, digest=digest, source_lang=source_lang
        )

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        # Regenerate the key only when the caller passed an explicit default
        # without one. A bare copy() keeps the original key: qweb views share a
        # key across website COW copies.
        has_default_without_key = default and "key" not in default
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for view, vals in zip(self, vals_list, strict=True):
            if view.key and has_default_without_key:
                vals["key"] = f"{view.key}_{str(uuid.uuid4())[:6]}"
        return vals_list

    # default view selection
    @api.model
    def default_view(self, model: str, view_type: str) -> int | bool:
        """Fetch the default view for ``(model, view_type)``: the primary view
        with the lowest priority.

        :return: id of the default view, or False if none found
        """
        return self.search(self._get_default_view_domain(model, view_type), limit=1).id

    @api.model
    def _get_default_view_domain(self, model: str, view_type: str) -> Domain:
        return Domain(
            [
                ("model", "=", model),
                ("type", "=", view_type),
                ("mode", "=", "primary"),
            ]
        )

    # ------------------------------------------------------
    # Inheritance mechanism
    # ------------------------------------------------------
    @api.model
    def _get_inheriting_views_domain(self) -> Domain:
        """Return a domain to filter the sub-views to inherit from."""
        tree_cut_off_view = self.env.context.get("ir_ui_view_tree_cut_off_view")
        domain = Domain("active", "=", True)
        if tree_cut_off_view:
            return domain | Domain("id", "=", tree_cut_off_view.id)
        return domain

    @api.model
    def _get_filter_xmlid_query(self) -> str:
        """This method is meant to be overridden by other modules."""
        return """SELECT res_id FROM ir_model_data
                  WHERE res_id IN %(res_ids)s AND model = 'ir.ui.view' AND module IN %(modules)s
               """

    def _get_inheriting_views(self) -> Self:
        """Return the views that inherit from ``self``, ordered by priority then id."""
        if not self.ids:
            return self.browse()
        domain = self._get_inheriting_views_domain()
        query = self._search(domain)
        where_clause = query.where_clause
        # Load-bearing invariant: the recursive SQL below hardcodes "ir_ui_view"
        # as its FROM table, so a _search() override injecting a JOIN/alias would
        # build wrong SQL. Guard with a real raise (assert is stripped by -O).
        if query.from_clause != SQL.identifier("ir_ui_view"):
            raise AssertionError(f"Unexpected from clause: {query.from_clause}")

        field_names = [
            f.name for f in self._fields.values() if f.prefetch is True and not f.groups
        ]
        aliased_names = SQL(", ").join(
            SQL(
                "%s AS %s",
                self._field_to_sql("ir_ui_view", name),
                SQL.identifier(name),
            )
            for name in field_names
        )

        query = SQL(
            """
            WITH RECURSIVE ir_ui_view_inherits AS (
                SELECT ir_ui_view.id, %(aliased_names)s
                FROM ir_ui_view
                WHERE id IN %(ids)s AND (%(where_clause)s)
            UNION
                SELECT ir_ui_view.id, %(aliased_names)s
                FROM ir_ui_view
                INNER JOIN ir_ui_view_inherits parent ON parent.id = ir_ui_view.inherit_id
                WHERE coalesce(ir_ui_view.model, '') = coalesce(parent.model, '')
                      AND ir_ui_view.mode = 'extension'
                      AND (%(where_clause)s)
            )
            SELECT
                v.id, %(field_names)s
            FROM ir_ui_view_inherits as v
            ORDER BY v.priority, v.id
        """,
            aliased_names=aliased_names,
            field_names=SQL(", ").join(SQL.identifier("v", f) for f in field_names),
            ids=tuple(self.ids),
            where_clause=where_clause,
        )
        # ORDER BY v.priority, v.id:
        # 1/ priority: developer-set knob to force a view to combine earlier or
        #    later (e.g. studio views use priority=99 to load last).
        # 2/ id: insertion order (e.g. base views before stock ones).

        rows = self.env.execute_query(query)
        if not rows:
            return self.browse()

        ids, *columns = zip(*rows, strict=False)
        views = self.browse(ids)

        # optimization: fill in cache of retrieved fields
        for fname, column in zip(field_names, columns, strict=True):
            self._fields[fname]._insert_cache(views, column)

        return views

    def _filter_loaded_views(
        self,
        check_view_ids: Collection[int] = (),
        include_loaded_xmlids: bool = False,
    ) -> Self:
        """Filter ``self`` down to views whose module code is already loaded.

        During a module upgrade a view may exist in the database while the fields
        it relies on are not fully loaded; custom DB-only views load only after
        module init finishes. Single source of truth shared by
        :meth:`_get_combined_archs` and :meth:`_check_sibling_primary_views`.

        :param check_view_ids: view ids to consider loaded regardless of their
            external id (typically the views currently being combined)
        :param include_loaded_xmlids: also consider loaded the views whose
            external id was already processed in this upgrade
            (``pool.loaded_xmlids``)
        """
        # check that all found ids have a corresponding xml_id in a loaded module
        ids_to_check = [vid for vid in self.ids if vid not in check_view_ids]
        if not ids_to_check:
            return self
        install_module = self.env.context.get("install_module")
        loaded_modules = tuple(self.pool._init_modules)
        if install_module:
            loaded_modules += (install_module,)
        query = self._get_filter_xmlid_query()
        sql = SQL(query, res_ids=tuple(ids_to_check), modules=loaded_modules)
        valid_view_ids = {id_ for (id_,) in self.env.execute_query(sql)} | set(
            check_view_ids
        )
        if include_loaded_xmlids:
            valid_view_ids.update(
                id_
                for id_, xid in self.browse(
                    vid for vid in ids_to_check if vid not in valid_view_ids
                )
                .get_external_id()
                .items()
                if xid in self.pool.loaded_xmlids
            )
        return self.browse(vid for vid in self.ids if vid in valid_view_ids)

    def _check_view_access(self) -> bool:
        """Verify that a view is accessible by the current user based on the
        groups attribute. Views with no groups are considered private.
        """
        if self.inherit_id and self.mode != "primary":
            return self.inherit_id._check_view_access()
        if set(self.group_ids.ids) & set(self.env.user._get_group_ids()):
            return True
        if self.group_ids:
            error = _(
                "View '%(name)s' accessible only to groups %(groups)s ",
                name=self.key,
                groups=", ".join([g.name for g in self.group_ids]),
            )
        else:
            error = _("View '%(name)s' is private", name=self.key)
        raise AccessError(error)

    def _view_display_name(self) -> str:
        """Return a human-readable view label ("name (xml_id)" when the view
        has an external id, otherwise just its name) for use in error messages.

        Kept lazy on purpose: ``xml_id`` triggers an ``ir.model.data`` lookup,
        so it is only resolved on the (rare) error paths that call this.
        """
        self.ensure_one()
        return f"{self.name} ({self.xml_id})" if self.xml_id else self.name

    def _view_error_context(self, node: _Element | None) -> dict[str, Any]:
        """Build the contextual view information attached to view errors and
        warnings (single source of truth for _raise_view_error and
        _log_view_warning).
        """
        return {
            "view": self,
            "name": getattr(self, "name", None),
            "xmlid": self.env.context.get("install_xmlid") or self.xml_id,
            "view.model": self.model,
            "view.parent": self.inherit_id,
            "file": self.env.context.get("install_filename"),
            "line": node.sourceline if node is not None else 1,
        }

    def _raise_view_error(
        self,
        message: str,
        node: _Element | None = None,
        *,
        from_exception: BaseException | None = None,
        from_traceback: Any = None,
    ) -> typing.NoReturn:
        """Handle a view error by raising an exception.

        :param str message: message to raise or log, augmented with contextual
                            view information
        :param node: the lxml element where the error is located (if any)
        :param BaseException | None from_exception:
            when raising an exception, chain it to the provided one (default:
            disable chaining)
        :param Any from_traceback:
            when raising an exception, start with this traceback (default: start
            at exception creation)
        """
        err = ValueError(message).with_traceback(from_traceback)
        err.context = self._view_error_context(node)
        raise err from from_exception

    def _log_view_warning(self, message: str, node: _Element) -> None:
        """Log a view issue as a warning, augmented with contextual view info.

        :param str message: message to log
        :param node: the lxml element where the issue is located
        """
        _logger.warning(
            "%s\nView error context:\n%s",
            message,
            pprint.pformat(self._view_error_context(node)),
        )

    def locate_node(self, arch: _Element, spec: _Element) -> _Element | None:
        """Return the node in ``arch`` matching ``spec`` (a modifying node from
        an inheriting view), or None if there is no match.

        :param arch: the source (parent) architecture to search
        :param spec: a modifying node in an inheriting view
        :return: the matching node in the source, or None
        """
        return locate_node(arch, spec)

    def inherit_branding(self, specs_tree: _Element) -> _Element:
        for node in specs_tree.iterchildren(tag=etree.Element):
            if node.tag in {"data", "xpath"} or node.get("position"):
                self.inherit_branding(node)
            elif node.get("t-field"):
                node.set("data-oe-xpath", node.getroottree().getpath(node))
                self.inherit_branding(node)
            else:
                node.set("data-oe-id", str(self.id))
                node.set("data-oe-xpath", node.getroottree().getpath(node))
                node.set("data-oe-model", "ir.ui.view")
                node.set("data-oe-field", "arch")
        return specs_tree

    def _add_validation_flag(
        self,
        combined_arch: _Element,
        view: Self | None = None,
        arch: _Element | None = None,
    ) -> None:
        """Add a validation flag on elements in ``combined_arch`` or ``arch``.
        This is part of the partial validation of views.

        :param _Element combined_arch: the architecture to be modified by ``arch``
        :param view: an optional view inheriting ``self``
        :param _Element | None arch: an optional modifying architecture from inheriting
            view ``view``
        """
        # validate_view_ids is either falsy (no validation), True (full
        # validation) or a collection of ids (partial validation)
        validate_view_ids = self.env.context.get("validate_view_ids")
        if not validate_view_ids:
            return

        if validate_view_ids is True or self.id in validate_view_ids:
            # optimization, flag the root node
            combined_arch.set("__validate__", "1")
            return

        if view is None or view.id not in validate_view_ids:
            return

        for node in _xpath_position(arch):
            if node.get("position") in ("after", "before", "inside"):
                # validate the elements being inserted, except the ones that
                # specify a move, as in:
                #   <field name="foo" position="after">
                #       <field name="bar" position="move"/>
                #   </field>
                for child in node.iterchildren(tag=etree.Element):
                    if not child.get("position"):
                        child.set("__validate__", "1")
            if node.get("position") == "replace":
                # validate everything, since this impacts the whole arch
                combined_arch.set("__validate__", "1")
                break
            if node.get("position") == "attributes":
                # validate the element being modified by adding
                # attribute "__validate__" on it:
                #   <field name="foo" position="attributes">
                #       <attribute name="readonly">1</attribute>
                #       <attribute name="__validate__">1</attribute>    <!-- add this -->
                #   </field>
                node.append(E.attribute("1", name="__validate__"))

    @api.model
    def apply_inheritance_specs(
        self, source: _Element, specs_tree: _Element, pre_locate: Any = None
    ) -> _Element:
        """Apply an inheriting view's spec nodes to a source architecture.

        :param _Element source: a parent architecture to modify
        :param _Element specs_tree: a modifying architecture in an inheriting view
        :param Any pre_locate: optional function run before locating a node;
                               receives an arch as argument
        :return: the modified source with the specs applied
        :rtype: _Element
        """
        try:
            source = apply_inheritance_specs(
                source,
                specs_tree,
                inherit_branding=self.env.context.get("inherit_branding"),
                pre_locate=pre_locate,
            )
        except ValueError as e:
            self._raise_view_error(str(e), specs_tree)
        return source

    def _combine(self, hierarchy: dict[Self, list[Self]]) -> _Element:
        """
        Return self's arch combined with its inherited views archs.

        :param hierarchy: mapping from parent views to their child views
        :return: combined architecture
        :rtype: _Element
        """
        self.ensure_one()
        if self.mode != "primary":
            raise ValueError(
                f"_combine() requires a primary view, got mode={self.mode!r}"
            )

        # We achieve a pre-order depth-first hierarchy traversal where
        # primary views (and their children) are traversed after all the
        # extensions for the current primary view have been visited.
        #
        # https://en.wikipedia.org/wiki/Tree_traversal#Depth-first_search_of_binary_tree
        #
        # Example:                  hierarchy = {
        #                               1: [2, 3],  # primary view
        #             1*                2: [4, 5],
        #            / \                3: [],
        #           2   3               4: [6],     # primary view
        #          / \                  5: [7, 8],
        #         4*  5                 6: [],
        #        /   / \                7: [],
        #       6   7   8               8: [],
        #                           }  # noqa: ERA001, RUF100
        #
        # Tree traversal order (`view` and `queue` at the `while` stmt):
        #   1 [2, 3]
        #   2 [5, 3, 4]
        #   5 [7, 8, 3, 4]
        #   7 [8, 3, 4]
        #   8 [3, 4]
        #   3 [4]
        #   4 [6]
        #   6 []
        combined_arch = etree.fromstring(self.arch)
        if self.env.context.get("inherit_branding"):
            combined_arch.attrib.update(
                {
                    "data-oe-model": "ir.ui.view",
                    "data-oe-id": str(self.id),
                    "data-oe-field": "arch",
                }
            )
        self._add_validation_flag(combined_arch)

        # Depth-first traversal via a double-ended queue used mostly as a stack:
        # a view's children are pushed on the left (visited next), except primary
        # views which are pushed on the right so they apply after all extensions.
        # extensions first, then primary children (see the traversal note above)
        queue = collections.deque(
            sorted(hierarchy[self], key=lambda v: v.mode == "primary")
        )
        tree_cut_off_view = self.env.context.get("ir_ui_view_tree_cut_off_view")
        while queue:
            view = queue.popleft()
            if view == tree_cut_off_view:
                break
            arch = etree.fromstring(view.arch or "<data/>")
            if view.env.context.get("inherit_branding"):
                view.inherit_branding(arch)
            self._add_validation_flag(combined_arch, view, arch)
            combined_arch = view.apply_inheritance_specs(combined_arch, arch)

            for child_view in reversed(hierarchy[view]):
                if child_view.mode == "primary":
                    queue.append(child_view)
                else:
                    queue.appendleft(child_view)

        return combined_arch

    def get_combined_arch(self) -> str:
        """Return the arch of ``self`` (as a string) combined with its inherited views."""
        return etree.tostring(self._get_combined_arch(), encoding="unicode")

    def _get_combined_arch(self) -> _Element:
        self.ensure_one()
        return self._get_combined_archs()[0]

    def _get_combined_archs(self) -> list[_Element]:
        """Return each record's arch (as an etree) combined with its inherited views."""
        parented = []
        roots = self.env["ir.ui.view"]
        for root in self:
            parented.append(view_ids := [])
            while True:
                view_ids.append(root.id)
                if not root.inherit_id:
                    roots += root
                    break
                root = root.inherit_id
        views = self.env["ir.ui.view"].browse(
            unique(view_id for view_ids in parented for view_id in view_ids)
        )

        # Add the views being combined (self plus ancestors) to "check_view_ids"
        # so _filter_loaded_views treats them as available during an upgrade,
        # even before their xmlids are registered. Build a fresh list rather than
        # mutating the (nominally immutable) context list in place.
        check_view_ids = views.env.context.get("check_view_ids") or []
        views = views.with_context(check_view_ids=[*check_view_ids, *views.ids])

        # Map each node to its children nodes. All children nodes are
        # part of a single prefetch set, which is all views to combine.
        all_tree_views = views._get_inheriting_views()

        # During an upgrade, we can only use the views that have been
        # fully upgraded already.
        if self.pool._init and not self.env.context.get("load_all_views"):
            all_tree_views = all_tree_views._filter_loaded_views(
                set(views.env.context["check_view_ids"])
            )

        # get the global children views then get hierarchy for each views
        children_views = collections.defaultdict(list)
        for view in all_tree_views:
            children_views[view.inherit_id].append(view)

        def get_hierarchy(
            root: Self,
            parented_ids: list[int],
            _hierarchy: dict[Self, list[Self]] | None = None,
        ) -> dict[Self, list[Self]]:
            if _hierarchy is None:
                _hierarchy = collections.defaultdict(list)
            _hierarchy[root.inherit_id].append(root)
            for child in children_views[root]:
                if child.id in parented_ids or child.mode != "primary":
                    get_hierarchy(child, parented_ids, _hierarchy)
            return _hierarchy

        roots = roots.with_prefetch(all_tree_views._prefetch_ids)

        return [
            root._combine(get_hierarchy(root, parented_ids))
            for root, parented_ids in zip(roots, parented, strict=True)
        ]

    def _get_view_refs(self, node: _Element) -> dict[str, str]:
        """Extract the ``[view_type]_view_ref`` keys/values from the node's
        context attribute, giving the views to use for a field node.

        :param node: the field node as an etree
        :return: mapping of ``[view_type]_view_ref`` key to the view's xmlid
        """
        context = node.get("context")
        if not context:
            return {}
        return {
            m.group("view_type"): m.group("view_id") for m in ref_re.finditer(context)
        }

    # ------------------------------------------------------
    # Get views and cache
    # ------------------------------------------------------

    @api.model
    def _get_cached_template_prefetched_keys(self) -> list[str]:
        return ["id", "key", "active"]

    def _get_template_minimal_cache_keys(self) -> tuple[bool]:
        return (bool(self.env.context.get("active_test", True)),)

    @api.model
    @tools.ormcache(
        "id_or_xmlid",
        "isinstance(id_or_xmlid, str) and self._get_template_minimal_cache_keys()",
        cache="templates",
    )
    def _get_cached_template_info(
        self,
        id_or_xmlid: int | str,
        _view: Self | None = None,
        _error: Exception | None = None,
    ) -> frozendict:
        """Return cached info for the view ``id_or_xmlid`` (prefetched keys plus ``error``).

        ``_view`` and ``_error`` are warm-push helpers for
        :meth:`_fetch_template_views`, both excluded from the ormcache key.
        """
        view = None
        error = False
        if _error is not None:
            # warm push of a known-missing template: cache the error so that
            # _get_template_view raises instead of returning an empty recordset
            error = _error
        elif _view is not None:
            view = _view
        elif isinstance(id_or_xmlid, int):
            view = self.env["ir.ui.view"].sudo().browse(id_or_xmlid)
            try:
                _ = view.key
            except MissingError:
                view = None
                error = MissingError(
                    self.env._("Template not found: '%s'", id_or_xmlid)
                )
        else:
            preload = self.sudo()._preload_views([id_or_xmlid])
            if id_or_xmlid in preload:
                info = preload[id_or_xmlid]
                view = info["view"]
                error = info["error"]
            else:
                error = SyntaxError("Error compiling template")
        info = {
            f: view[f] if view else None
            for f in self._get_cached_template_prefetched_keys()
        }
        info["error"] = error
        # frozendict: the value lives in the shared "templates" ormcache (like
        # _get_view_cache's), so it must not be mutable by callers
        return frozendict(info)

    @api.model
    def _get_template_view(
        self, id_or_xmlid: int | str, raise_if_not_found: bool = True
    ) -> Self:
        info = self._get_cached_template_info(id_or_xmlid)
        if info["error"] and raise_if_not_found:
            raise info["error"]
        return self.env["ir.ui.view"].browse(info["id"])

    @api.model
    def _get_template_domain(self, xmlids: list[str]) -> Domain:
        return Domain("key", "in", xmlids)

    @api.model
    def _get_template_order(self) -> str:
        return "priority, id"

    @api.model
    def _fetch_template_views(
        self, ids_or_xmlids: Sequence[int | str]
    ) -> dict[int | str, Self | Exception]:
        """Return a mapping of each reference in ``ids_or_xmlids`` (a view ID or
        XML ID) to its view, or to an exception if it was not found. May be
        overridden for other kinds of template values.
        """
        IrUiView = (
            self.env["ir.ui.view"]
            .sudo()
            .with_context(load_all_views=True, raise_if_not_found=True)
        )

        ids, xmlids = partition(lambda v: isinstance(v, int), ids_or_xmlids)

        # search view in ir.ui.view
        view_by_id = {}
        field_names = [f.name for f in IrUiView._fields.values() if f.prefetch is True]
        if xmlids:
            domain = Domain("id", "in", ids) | Domain(self._get_template_domain(xmlids))
            views = IrUiView.search_fetch(
                domain, field_names, order=self._get_template_order()
            )
        else:
            views = IrUiView.browse(ids)

        for view in views:
            try:
                if view.key in view_by_id:
                    # keeps views according to their priority order
                    continue
            except MissingError:
                continue
            view_by_id[view.id] = view
            if view.key:
                view_by_id[view.key] = view

        # search missing view from xmlid in ir.model.data
        missing_xmlid_views = [
            xmlid for xmlid in xmlids if "." in xmlid and xmlid not in view_by_id
        ]
        if missing_xmlid_views:
            domain = Domain.OR(
                Domain("model", "=", "ir.ui.view")
                & Domain("module", "=", res[0])
                & Domain("name", "=", res[1])
                for xmlid in missing_xmlid_views
                if (res := xmlid.split(".", 1))
            )

            model_data_records = self.env["ir.model.data"].sudo().search(domain)
            all_views = IrUiView.browse(model_data_records.mapped("res_id")).exists()
            existing_ids = set(all_views._ids)
            view_map = {v.id: v for v in all_views}
            for model_data in model_data_records:
                if model_data.res_id in existing_ids:
                    view = view_map[model_data.res_id]
                    view_by_id[view.id] = view
                    xmlid = f"{model_data.module}.{model_data.name}"
                    view_by_id[xmlid] = view
                    if view.key:
                        view_by_id[view.key] = view

        for key, view in view_by_id.items():
            # push information in cache
            self._get_cached_template_info(key, _view=view)

        # create data and errors
        for view_id in ids:
            if view_id not in view_by_id:
                error = MissingError(
                    self.env._(
                        "Template does not exist or has been deleted: %s",
                        view_id,
                    )
                )
                # push the error in cache
                self._get_cached_template_info(view_id, _error=error)
                view_by_id[view_id] = error
        for xmlid in xmlids:
            if xmlid not in view_by_id:
                error = MissingError(self.env._("Template not found: '%s'", xmlid))
                # push the error in cache
                self._get_cached_template_info(xmlid, _error=error)
                view_by_id[xmlid] = error
        return view_by_id

    @tools.ormcache(cache="templates")
    def _clear_preload_views_cache_if_needed(self) -> None:
        """Invalidate the local cache when the orm cache is cleared"""
        self.env.cr.cache.pop("_compile_batch_", None)

    def _preload_views(
        self, refs: Sequence[int | str]
    ) -> dict[int | str, dict[str, Any]]:
        """
        Preload view information for the given references.

        :param refs: list of id or xmlid
        :return: dictionary of preloaded information {id or xmlid: {xmlid, ref, view, error}}
        """
        self._clear_preload_views_cache_if_needed()

        # Reuse ir.qweb's cache signature (falsy context values collapse to
        # False) rather than a raw .get(k) that would key the same context twice.
        cache_key = self.env["ir.qweb"]._template_cache_signature()

        compile_batch = self.env.cr.cache.setdefault("_compile_batch_", {}).setdefault(
            cache_key, {}
        )

        refs = [
            int(ref) if isinstance(ref, int) or ref.isdigit() else ref for ref in refs
        ]
        missing_refs = [ref for ref in refs if ref and ref not in compile_batch]
        if not missing_refs:
            return compile_batch

        unknown_views = self._fetch_template_views(missing_refs)

        # add in cache
        for id_or_xmlid, view in unknown_views.items():
            if isinstance(view, models.BaseModel):
                compile_batch[view.id] = compile_batch[id_or_xmlid] = {
                    "xmlid": view.key or id_or_xmlid,
                    "ref": view.id,
                    "view": view,
                    "error": False,
                }
            else:
                compile_batch[id_or_xmlid] = {
                    "xmlid": id_or_xmlid,
                    "view": None,
                    "ref": None,
                    "error": view,  # MissingError
                }

        return compile_batch

    # ------------------------------------------------------
    # Postprocessing: translation, groups and modifiers
    # ------------------------------------------------------
    # TODO: remove group processing from ir_qweb
    # ------------------------------------------------------
    def postprocess_and_fields(
        self, node: _Element, model: str | None = None, **options: Any
    ) -> tuple[str, dict[str, set[str]]]:
        """Return an architecture and a description of all the fields.

        The field description combines the result of fields_get() and
        _postprocess_view().

        :param node: the architecture as an etree
        :param model: the view's reference model name
        :return: a tuple (arch, fields) where arch is ``node`` serialized to a
            string and fields is the description of all the fields
        """
        self and self.ensure_one()  # self is at most one view

        name_manager = self._postprocess_view(node, model or self.model, **options)
        # Strip indentation tabs from the serialized arch. Note this also removes
        # tabs from text-node content (attribute-value tabs are already
        # normalized to spaces by the XML parser, so they are unaffected).
        arch = etree.tostring(node, encoding="unicode").replace("\t", "")

        # Breadth-first walk over the name manager and its nested (comodel)
        # children, collecting every model's available fields.
        fields_by_model: dict[str, set[str]] = {}
        queue = collections.deque([name_manager])
        while queue:
            manager = queue.popleft()
            fields_by_model.setdefault(manager.model._name, set()).update(
                manager.available_fields
            )
            queue.extend(manager.children)

        return arch, fields_by_model

    def _postprocess_access_rights(self, tree: _Element) -> _Element:
        """Apply group restrictions and compute per-node access rights.

        Elements with a 'groups' attribute are removed for non-members. Access
        rights are set per node based on view type; specific views may add
        their own (e.g. columns for many2one-based grouping views).
        """
        group_definitions = self.env["res.groups"]._get_group_definitions()

        user_group_ids = self.env.user._get_group_ids()

        # check the read/visibility access
        @functools.cache
        def has_access(groups_key: str) -> bool:
            groups = group_definitions.from_key(groups_key)
            return groups.matches(user_group_ids)

        # check the read/visibility access
        for node in _xpath_groups_key(tree):
            if not has_access(node.attrib.pop("__groups_key__")):
                tail = node.tail
                parent = node.getparent()
                previous = node.getprevious()
                parent.remove(node)
                if tail:
                    if previous is not None:
                        previous.tail = (previous.tail or "") + tail
                    elif parent is not None:
                        parent.text = (parent.text or "") + tail
            elif node.tag == "t" and not node.attrib:
                # Move content of <t groups=""> blocks
                # and remove the <t> node.
                # This is to keep the structure
                # <group>
                #   <field name="foo"/>
                #   <field name="bar"/>
                # <group>
                # so the web client adds the label as expected.
                # This is also to avoid having <t> nodes in list views
                # e.g.
                # <list>
                #   <field name="foo"/>
                #   <t groups="foo">
                #     <field name="bar" groups="bar"/>
                #   </t>
                # </list>
                for child in reversed(node):
                    node.addnext(child)
                node.getparent().remove(node)

        # check the create and write access
        for node in _xpath_model_access(tree):
            model = self.env[node.attrib.pop("model_access_rights")]
            if node.tag == "field":
                can_create = model.has_access("create")
                can_write = model.has_access("write")
                node.set("can_create", str(bool(can_create)))
                node.set("can_write", str(bool(can_write)))
            else:
                for action, operation in (
                    ("create", "create"),
                    ("delete", "unlink"),
                    ("edit", "write"),
                ):
                    if not node.get(action) and not model.has_access(operation):
                        node.set(action, "False")
                if node.tag == "kanban":
                    group_by_name = node.get("default_group_by")
                    group_by_field = model._fields.get(group_by_name)
                    if group_by_field and group_by_field.type == "many2one":
                        group_by_model = model.env[group_by_field.comodel_name]
                        for action, operation in (
                            ("group_create", "create"),
                            ("group_delete", "unlink"),
                            ("group_edit", "write"),
                        ):
                            if not node.get(action) and not group_by_model.has_access(
                                operation
                            ):
                                node.set(action, "False")

        return tree

    def _postprocess_debug_to_cache(self, tree: _Element) -> None:
        """Transform ``groups`` containing ``base.group_no_one`` into the
        ``__debug__`` attribute for debug-mode handling.

        ``base.group_no_one`` is a debug-visibility display feature, not a
        security group. Both the positive (show in debug) and negated
        (``!base.group_no_one`` → hide in debug) forms are handled and stripped
        from ``groups`` so :meth:`_postprocess_access_rights` doesn't interfere.
        """
        for node in _xpath_groups(tree):
            groups = node.attrib.get("groups", "").split(",")
            if "base.group_no_one" in groups:
                node.attrib["__debug__"] = "True"
                node.attrib["groups"] = ",".join(
                    group for group in groups if group != "base.group_no_one"
                )
            elif "!base.group_no_one" in groups:
                node.attrib["__debug__"] = "False"
                node.attrib["groups"] = ",".join(
                    group for group in groups if group != "!base.group_no_one"
                )

    def _postprocess_debug(self, tree: _Element) -> _Element:
        """Apply debug mode by making nodes invisible."""
        is_debug = self.env.user.has_group("base.group_no_one")
        for node in _xpath_debug(tree):
            debug = node.attrib.pop("__debug__") == "True"
            if debug != is_debug:
                node.attrib["invisible"] = "1"
                node.attrib["column_invisible"] = "1"
        return tree

    def _init_view_processing(
        self,
        node: _Element,
        model_name: str,
        node_info: dict[str, Any] | None,
        *,
        translate: bool,
    ) -> tuple[NameManager, Any, Any, Any]:
        """Shared setup for :meth:`_postprocess_view` and :meth:`_validate_view`:
        check the model exists, resolve the model/view access-group context, and
        create the view's :class:`NameManager`.

        :param translate: keep the current language on the model (postprocessing)
            or drop it (validation does not require translations)
        :return: ``(name_manager, group_definitions, model_groups, view_groups)``
        """
        if model_name not in self.env:
            self._raise_view_error(
                _("Model not found: %(model)s", model=model_name), node
            )

        group_definitions = self.env["res.groups"]._get_group_definitions()

        # model_groups/view_groups: access groups for the model/view
        model_groups = (
            node_info["model_groups"] if node_info else group_definitions.universe
        )
        view_groups = (
            node_info["view_groups"] if node_info else group_definitions.universe
        )
        parent_name_manager = node_info["name_manager"] if node_info else None

        # combine model access groups with this model's access groups
        model_groups &= self.env["ir.model.access"]._get_access_groups(model_name)

        model = self.env[model_name]
        if not translate:
            # fields_get() optimization: validation does not require translations
            model = model.with_context(lang=None)

        name_manager = NameManager(
            model, parent=parent_name_manager, model_groups=model_groups
        )
        return name_manager, group_definitions, model_groups, view_groups

    def _narrow_model_groups(self, node_info: dict[str, Any], field: Any) -> None:
        """Intersect ``node_info['model_groups']`` with the access groups
        declared on ``field`` (its ``groups`` attribute); no-op if it has none.

        Shared by the ``field``/``label`` handlers of both postprocessing and
        validation so the access-group narrowing lives in a single place.
        """
        if field.groups:
            group_definitions = self.env["res.groups"]._get_group_definitions()
            node_info["model_groups"] &= group_definitions.parse(
                field.groups, raise_if_not_found=False
            )

    def _iter_arch_nodes(
        self,
        root: _Element,
        make_node_info: Callable[[_Element, dict[str, Any] | None], dict[str, Any]],
    ) -> typing.Iterator[tuple[_Element, dict[str, Any]]]:
        """Pre-order depth-first walk over ``root``, shared by
        :meth:`_postprocess_view` and :meth:`_validate_view`.

        For each element it calls ``make_node_info(node, parent_info)`` (where
        ``parent_info`` is the parent's node_info, ``None`` at the root), yields
        ``(node, node_info)`` for the caller's phase-specific work, then descends
        into ``node_info.get("children", node)``. A node whose handler detached
        it from the tree has its subtree skipped. Keeping the traversal here
        stops the two phases from drifting apart.
        """
        # each stack entry pairs a node with its parent's node_info (None = root)
        stack: list[tuple[_Element, dict[str, Any] | None]] = [(root, None)]
        while stack:
            node, parent_info = stack.pop()
            had_parent = node.getparent() is not None
            node_info = make_node_info(node, parent_info)
            yield node, node_info
            if had_parent and node.getparent() is None:
                # a tag handler detached the node from the tree; skip its subtree
                continue
            stack.extend(
                (child, node_info)
                for child in reversed(node_info.get("children", node))
            )

    def _postprocess_view(
        self,
        node: _Element,
        model_name: str,
        editable: bool = True,
        node_info: dict[str, Any] | None = None,
        **options: Any,
    ) -> NameManager:
        """Process the given architecture in-place, adding and removing nodes.

        :param node: the combined architecture as an etree
        :param model_name: the view's reference model name
        :param editable: whether the view is considered editable
        :return: the processed architecture's NameManager
        """
        root = node

        name_manager, group_definitions, model_groups, view_groups = (
            self._init_view_processing(root, model_name, node_info, translate=True)
        )
        model = name_manager.model

        root_info = {
            "view_type": root.tag,
            "mobile": options.get("mobile"),
            "model_groups": model_groups,
            "view_groups": view_groups,
            "name_manager": name_manager,
        }

        # When rendering for warning_info/debug display, keep the human-readable
        # ``groups`` attribute on nodes (it is otherwise popped by
        # _postprocess_attributes) so it shows up in the generated messages.
        preserve_groups = options.get("preserve_groups")

        self._postprocess_debug_to_cache(root)

        # Children inherit their parent's (narrowed) view_groups and editability;
        # model_groups always resets to the root value (field.groups narrowing is
        # per-node, never inherited). See _iter_arch_nodes for the traversal.
        initial_view_groups, initial_editable = view_groups, editable

        def make_node_info(
            node: _Element, parent_info: dict[str, Any] | None
        ) -> dict[str, Any]:
            editable = (
                parent_info["editable"] if parent_info is not None else initial_editable
            )
            node_info = dict(
                root_info,
                view_groups=(
                    parent_info["view_groups"]
                    if parent_info is not None
                    else initial_view_groups
                ),
                editable=editable and self._editable_node(node, name_manager),
            )
            if node_groups := node.get("groups"):
                node_info["view_groups"] &= group_definitions.parse(
                    node_groups, raise_if_not_found=False
                )
            return node_info

        for elem, elem_info in self._iter_arch_nodes(root, make_node_info):
            # tag-specific postprocessing
            postprocessor = getattr(self, f"_postprocess_tag_{elem.tag}", None)
            if postprocessor is not None:
                had_parent = elem.getparent() is not None
                postprocessor(elem, name_manager, elem_info)
                if had_parent and elem.getparent() is None:
                    # the node has been removed: _iter_arch_nodes skips its
                    # subtree, and we skip the rest of its processing here
                    continue

            elem_groups = elem.get("groups")
            if elem_groups or root_info["model_groups"] != elem_info["model_groups"]:
                groups = elem_info["model_groups"] & elem_info["view_groups"]
                elem.set("__groups_key__", groups.key)

            self._postprocess_attributes(elem, name_manager, elem_info)

            if elem_groups and preserve_groups:
                # reset the groups attributes to display in log
                elem.attrib["groups"] = elem_groups

        missing_fields = self._add_missing_fields(root, name_manager)

        if preserve_groups:
            # Build the warning here, while the arch nodes still reflect their
            # postprocessed-but-not-yet-onchanged state: _postprocess_on_change
            # below mutates nodes (e.g. adds on_change="1"), which would leak
            # into the serialized debug text if the warning were built later.
            name_manager.warning = self._group_inconsistency_warning(
                name_manager, missing_fields
            )

        name_manager.update_available_fields()

        root.set("model_access_rights", model._name)

        if self._onchange_able_view(root):
            self._postprocess_on_change(root, model)

        return name_manager

    def _add_missing_fields(
        self, node: _Element, name_manager: NameManager
    ) -> dict[str, Any]:
        """Add the fields required for evaluating expressions in the view given by ``node``."""
        root = node
        missing_fields = name_manager.get_missing_fields()
        for name, (missing_groups, reasons) in missing_fields.items():
            if name not in name_manager.field_info:
                continue

            # If the available fields have different groups then to avoid it being missing for
            # certain users, we virtually add a field with common groups.
            name_manager.available_fields[name].setdefault("info", {})
            name_manager.available_fields[name].setdefault("groups", []).append(
                missing_groups
            )
            name_manager.available_names.add(name)

            readonly = True
            if filename_reasons := [r for r in reasons if r[1][0] == "filename"]:
                filename_node = filename_reasons[-1][2]
                if node_readonly := filename_node.get("readonly"):
                    readonly = node_readonly
                else:
                    field = name_manager.model._fields[filename_node.get("name")]
                    if field.type == "binary":
                        readonly = field.readonly or False
            # If the field is not in the view without any group restriction,
            # add the field node with all mandatory groups (or without group if
            # the mandatory field does not have groups).
            attrs = {
                "name": name,
                ("invisible" if root.tag != "list" else "column_invisible"): "True",
                "readonly": str(readonly),
                "data-used-by": "; ".join(
                    f"{attr}={expr!r} ({node.tag},{node.get('name')})"
                    for _groups, (attr, expr), node in reasons
                ),
            }

            if missing_groups is not False:
                subset_groups = missing_groups.invert_intersect(
                    name_manager.model_groups
                )
                if subset_groups is None:
                    subset_groups = missing_groups
                if not subset_groups.is_universal():
                    attrs["__groups_key__"] = subset_groups.key

            item = etree.Element("field", attrs)
            item.tail = "\n"
            root.append(item)
        return missing_fields

    def _postprocess_on_change(self, arch: _Element, model: models.BaseModel) -> None:
        """Add attribute on_change="1" on fields that are dependencies of
        computed fields on the same view.
        """
        # map each field object to its corresponding nodes in arch
        field_nodes = collections.defaultdict(list)

        def collect(node: _Element, model: models.BaseModel) -> None:
            if node.tag == "field":
                field = model._fields.get(node.get("name"))
                if field:
                    field_nodes[field].append(node)
                    if field.relational:
                        model = self.env[field.comodel_name]
            for child in node:
                collect(child, model)

        collect(arch, model)

        for field, nodes in field_nodes.items():
            # if field should trigger an onchange, add on_change="1" on the
            # nodes referring to field
            model = self.env[field.model_name]
            if model._has_onchange(field, field_nodes):
                for node in nodes:
                    if not node.get("on_change"):
                        node.set("on_change", "1")

    def _get_x2many_missing_view_archs(
        self, field: Any, field_node: _Element, node_info: dict[str, Any]
    ) -> list[_Element]:
        """
        Return the multi-record view archs (kanban or list) needed to display
        the records of an x2many field whose node does not already embed one.
        """
        current_view_types = [el.tag for el in _xpath_descendant_field(field_node)]
        missing_view_types = []
        if not any(
            view_type in current_view_types
            for view_type in field_node.get("mode", "kanban,list").split(",")
        ):
            missing_view_types.append(
                field_node.get(
                    "mode", "kanban" if node_info.get("mobile") else "list"
                ).split(",")[0]
            )

        if not missing_view_types:
            return []

        comodel = self.env[field.comodel_name].sudo(False)
        refs = self._get_view_refs(field_node)
        # Do not propagate <view_type>_view_ref of parent call to `_get_view`
        comodel = comodel.with_context(
            **{
                f"{view_type}_view_ref": refs.get(f"{view_type}_view_ref")
                for view_type in missing_view_types
            }
        )

        # _get_view returns (arch, view); only the arch is embedded in the field.
        return [
            comodel._get_view(view_type=view_type)[0]
            for view_type in missing_view_types
        ]

    def _postprocess_attributes(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        # get mandatory fields
        for attr, expr in node.items():
            if attr in VIEW_MODIFIERS or attr.startswith("decoration-"):
                vnames = get_expression_field_names(expr)
                name_manager.must_have_fields(node, vnames, node_info, (attr, expr))
            elif attr == "groups":
                node.attrib.pop("groups")

    # ------------------------------------------------------
    # Specific node postprocessors
    # ------------------------------------------------------
    def _calendar_field_names(self, node: _Element) -> typing.Iterator[str | None]:
        """Yield the names of the fields referenced by a ``<calendar>`` node:
        its date/color/all_day attributes (:data:`CALENDAR_DATE_ATTRS`), its
        ``aggregate`` attribute, and its ``<filter>`` children.

        Shared by :meth:`_postprocess_tag_calendar` and
        :meth:`_validate_tag_calendar` so the two phases can't drift.
        """
        for attr in CALENDAR_DATE_ATTRS:
            if value := node.get(attr):
                # a date attribute may carry a dotted path (e.g. "line_ids.date");
                # only its first segment names a field on the view's model.
                yield value.split(".", 1)[0]
        if aggregate := node.get("aggregate"):
            yield aggregate.split(":")[0]
        for child in node:
            if child.tag == "filter":
                yield child.get("name")

    def _has_calendar_fields(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        """Register every field referenced by a ``<calendar>`` node on the
        ``name_manager``. Shared by :meth:`_postprocess_tag_calendar` and
        :meth:`_validate_tag_calendar`.
        """
        for name in self._calendar_field_names(node):
            name_manager.has_field(node, name, node_info)

    def _postprocess_tag_calendar(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        self._has_calendar_fields(node, name_manager, node_info)

    def _postprocess_tag_field(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        name = node.get("name")
        if not name:
            return

        attrs = {"id": node.get("id"), "select": node.get("select")}
        field = name_manager.model._fields.get(name)

        if field:
            self._narrow_model_groups(node_info, field)
            if (
                node_info.get("view_type") == "form"
                and field.type in ("one2many", "many2many")
                and not node.get("widget")
                and node.get("invisible") not in ("1", "True")
                and not name_manager.parent
            ):
                # Embed kanban/list/form views for visible x2many fields in form views
                # if no widget or the widget requires it.
                # So the web client doesn't have to call `get_views` for x2many fields not embedding their view
                # in the main form view.
                for arch in self._get_x2many_missing_view_archs(field, node, node_info):
                    node.append(arch)

            if field.relational:
                domain = node.get("domain") or (
                    node_info["editable"] and field._description_domain(self.env)
                )
                if isinstance(domain, str):
                    vnames = get_expression_field_names(domain)
                    name_manager.must_have_fields(
                        node, vnames, node_info, ("domain", domain)
                    )
            if field.type == "properties":
                name_manager.must_have_fields(
                    node,
                    [field.definition_record],
                    node_info,
                    ("fieldname", field.name),
                )
            context = node.get("context")
            if context:
                vnames = get_expression_field_names(context)
                name_manager.must_have_fields(
                    node, vnames, node_info, ("context", context)
                )
            if field.type == "binary" and (field_filename := node.get("filename")):
                name_manager.must_have_fields(
                    node,
                    [field_filename],
                    node_info,
                    ("filename", field_filename),
                )

            for child in node:
                if child.tag in _NESTED_VIEW_TAGS:
                    node_info["children"] = []
                    self._postprocess_view(
                        child,
                        field.comodel_name,
                        editable=node_info["editable"],
                        node_info=node_info,
                    )

            if node_info["editable"] and field.type in (
                "many2one",
                "many2many",
            ):
                node.set("model_access_rights", field.comodel_name)

        name_manager.has_field(node, name, node_info, attrs)

    def _postprocess_tag_form(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        result = name_manager.model.view_header_get(False, node.tag)
        if result:
            node.set("string", result)

    def _postprocess_tag_groupby(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        # groupby nodes should be considered as nested view because they may
        # contain fields on the comodel
        name = node.get("name")
        field = name_manager.model._fields.get(name)
        if not field or not field.comodel_name:
            return
        # post-process the node as a nested view, and associate it to the field
        node_info["children"] = []
        self._postprocess_view(
            node, field.comodel_name, editable=False, node_info=node_info
        )
        name_manager.has_field(node, name, node_info)

    def _postprocess_tag_label(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if not node.get("for"):
            return
        field = name_manager.model._fields.get(node.get("for"))
        if field:
            self._narrow_model_groups(node_info, field)

    def _postprocess_tag_search(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        searchpanel = [child for child in node if child.tag == "searchpanel"]
        if searchpanel:
            self._postprocess_view(
                searchpanel[0],
                name_manager.model._name,
                editable=False,
                node_info=node_info,
            )
            node_info["children"] = [
                child for child in node if child.tag != "searchpanel"
            ]

    def _postprocess_tag_list(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        # reuse form view post-processing
        self._postprocess_tag_form(node, name_manager, node_info)

    # -------------------------------------------------------------------
    # view editability
    # -------------------------------------------------------------------

    @api.model
    @tools.ormcache()
    def _get_view_type_tags(self) -> frozenset[str]:
        """Return the set of tags that are view-type roots (form, list, ...).

        Cached per-registry rather than kept as a module constant because the
        ``type`` selection is extended by installed modules (e.g. gantt, map).
        """
        return frozenset(value for value, _label in self._fields["type"].selection)

    def _editable_node(self, node: _Element, name_manager: NameManager) -> bool:
        """Return whether the given node must be considered editable."""
        func = getattr(self, f"_editable_tag_{node.tag}", None)
        if func is not None:
            return func(node, name_manager)
        # by default views are non-editable
        return node.tag not in self._get_view_type_tags()

    def _editable_tag_form(self, node: _Element, name_manager: NameManager) -> bool:
        return True

    def _editable_tag_list(self, node: _Element, name_manager: NameManager) -> bool:
        return bool(node.get("editable") or node.get("multi_edit"))

    def _editable_tag_field(self, node: _Element, name_manager: NameManager) -> bool:
        field = name_manager.model._fields.get(node.get("name"))
        return field is None or (
            field.is_editable() and node.get("readonly") not in ("1", "True")
        )

    def _onchange_able_view(self, node: _Element) -> bool | None:
        func = getattr(self, f"_onchange_able_view_{node.tag}", None)
        if func is not None:
            return func(node)
        return None

    def _onchange_able_view_form(self, node: _Element) -> bool:
        return True

    def _onchange_able_view_list(self, node: _Element) -> bool:
        return True

    def _onchange_able_view_kanban(self, node: _Element) -> bool:
        return True

    # -------------------------------------------------------------------
    # view validation
    # -------------------------------------------------------------------

    def _validate_view(
        self,
        node: _Element,
        model_name: str,
        view_type: str | None = None,
        editable: bool = True,
        node_info: dict[str, Any] | None = None,
    ) -> NameManager:
        """Validate the given architecture node and return its NameManager.

        :param node: the combined architecture as an etree
        :param model_name: the reference model name for the architecture
        :param editable: whether the view is considered editable
        :return: the architecture's NameManager
        """
        self.ensure_one()

        view_type = view_type or self.type
        if node.tag != view_type:
            self._raise_view_error(
                _(
                    "The root node of a %(view_type)s view should be a <%(view_type)s>, not a <%(tag)s>",
                    view_type=view_type,
                    tag=node.tag,
                ),
                node,
            )

        validate = node_info["validate"] if node_info else False
        name_manager, group_definitions, model_groups, view_groups = (
            self._init_view_processing(node, model_name, node_info, translate=False)
        )

        root_view_type = node.tag
        # Children inherit view_groups, editability and the validate flag from
        # their parent's node_info; model_groups always resets to the root value.
        # See _iter_arch_nodes for the shared traversal.
        initial_view_groups, initial_editable, initial_validate = (
            view_groups,
            editable,
            validate,
        )

        def make_node_info(
            node: _Element, parent_info: dict[str, Any] | None
        ) -> dict[str, Any]:
            if parent_info is not None:
                view_groups = parent_info["view_groups"]
                editable = parent_info["editable"]
                validate = parent_info["validate"]
            else:
                view_groups = initial_view_groups
                editable = initial_editable
                validate = initial_validate
            validate = validate or node.get("__validate__")
            node_info = {
                "editable": editable and self._editable_node(node, name_manager),
                "validate": validate,
                "view_type": root_view_type,
                "model_groups": model_groups,
                "view_groups": view_groups,
                "name_manager": name_manager,
            }
            if groups := node.get("groups"):
                for group_name in groups.replace("!", "").split(","):
                    name_manager.must_exist_group(group_name, node)
                node_info["view_groups"] &= group_definitions.parse(
                    groups, raise_if_not_found=False
                )
            return node_info

        for elem, elem_info in self._iter_arch_nodes(node, make_node_info):
            # tag-specific validation
            validator = getattr(self, f"_validate_tag_{elem.tag}", None)
            if validator is not None:
                validator(elem, name_manager, elem_info)

            if elem_info["validate"]:
                self._validate_attributes(elem, name_manager, elem_info)

        name_manager.check(self)

        return name_manager

    # ------------------------------------------------------
    # Node validator
    # ------------------------------------------------------
    def _validate_tag_form(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        # No form-specific validation by default; kept as an extension point for
        # modules (and reused by _validate_tag_list, which shares form semantics).
        pass

    def _validate_tag_list(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        # reuse form view validation
        self._validate_tag_form(node, name_manager, node_info)
        if not node_info["validate"]:
            return
        # inline list views inside form views aren't rng validated, so we must validate the
        # editable attribute in python
        editable_attr = node.get("editable")
        if editable_attr and editable_attr not in ["top", "bottom"]:
            msg = _(
                'The "editable" attribute of list views must be "top" or "bottom", received %(value)s',
                value=editable_attr,
            )
            self._raise_view_error(msg, node)
        allowed_tags = (
            "field",
            "button",
            "control",
            "groupby",
            "widget",
            "header",
        )
        for child in node.iterchildren(tag=etree.Element):
            if child.tag not in allowed_tags and not isinstance(child, etree._Comment):
                msg = _(
                    "List child can only have one of %(tags)s tag (not %(wrong_tag)s)",
                    tags=", ".join(allowed_tags),
                    wrong_tag=child.tag,
                )
                self._raise_view_error(msg, child)

    def _validate_tag_graph(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if not node_info["validate"]:
            return
        for child in node.iterchildren(tag=etree.Element):
            if child.tag != "field" and not isinstance(child, etree._Comment):
                msg = _(
                    "A <graph> can only contains <field> nodes, found a <%s>",
                    child.tag,
                )
                self._raise_view_error(msg, child)

    def _validate_tag_calendar(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        self._has_calendar_fields(node, name_manager, node_info)

    def _validate_tag_search(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        # (No "requires a field" check: filter-only search views are legal.)
        searchpanels = [child for child in node if child.tag == "searchpanel"]
        if searchpanels:
            if len(searchpanels) > 1:
                self._raise_view_error(
                    _("Search tag can only contain one search panel"), node
                )
            node.remove(searchpanels[0])
            self._validate_view(
                searchpanels[0],
                name_manager.model._name,
                view_type="searchpanel",
                node_info=node_info,
                editable=False,
            )

    def _validate_tag_field(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        validate = node_info["validate"]

        name = node.get("name")
        if not name:
            self._raise_view_error(
                _('Field tag must have a "name" attribute defined'), node
            )

        field = name_manager.model._fields.get(name)
        if field:
            self._narrow_model_groups(node_info, field)

            if validate and field.relational:
                domain = node.get("domain") or (
                    node_info["editable"] and field._description_domain(self.env)
                )
                if isinstance(domain, str):
                    # dynamic domain: in [('foo', '=', bar)], field 'foo' must
                    # exist on the comodel and field 'bar' must be in the view
                    desc = (
                        f'domain of <field name="{name}">'
                        if node.get("domain")
                        else f"domain of python field {name!r}"
                    )
                    self._validate_domain_identifiers(
                        node,
                        name_manager,
                        domain,
                        desc,
                        field.comodel_name,
                        node_info,
                    )

            elif validate and node.get("domain"):
                msg = _(
                    'Domain on non-relational field "%(name)s" makes no sense (domain:%(domain)s)',
                    name=name,
                    domain=node.get("domain"),
                )
                self._raise_view_error(msg, node)

            if field.type == "properties" and node_info["view_type"] != "search":
                name_manager.must_have_fields(
                    node,
                    {field._description_definition_record},
                    node_info,
                    use=("fieldname", field.name),
                )

            for child in node:
                if child.tag not in _NESTED_VIEW_TAGS:
                    continue
                node.remove(child)
                self._validate_view(
                    child,
                    field.comodel_name,
                    view_type=child.tag,
                    editable=node_info["editable"],
                    node_info=node_info,
                )

        elif validate and name not in name_manager.field_info:
            msg = _(
                'Field "%(field_name)s" does not exist in model "%(model_name)s"',
                field_name=name,
                model_name=name_manager.model._name,
            )
            self._raise_view_error(msg, node)

        name_manager.has_field(
            node,
            name,
            node_info,
            {"id": node.get("id"), "select": node.get("select")},
        )

    def _validate_tag_filter(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if not node_info["validate"]:
            return
        domain = node.get("domain")
        if domain:
            name = node.get("name")
            desc = f'domain of <filter name="{name}">' if name else "domain of <filter>"
            self._validate_domain_identifiers(
                node,
                name_manager,
                domain,
                desc,
                name_manager.model._name,
                node_info,
            )
        if node.get("date") and (default_periods := node.get("default_period")):
            custom_options = {f"custom_{child.attrib['name']}" for child in node}
            for default_period in default_periods.split(","):
                if not re.fullmatch(
                    r"(year|month)((-|\+)[1-9]\d*)?", default_period
                ) and default_period not in custom_options | {
                    "first_quarter",
                    "second_quarter",
                    "third_quarter",
                    "fourth_quarter",
                }:
                    msg = _(
                        "Invalid default period %(default_period)s for date filter",
                        default_period=default_period,
                    )
                    self._raise_view_error(msg, node)

    def _validate_tag_button(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if not node_info["validate"]:
            return
        name = node.get("name")
        special = node.get("special")
        type_ = node.get("type")
        if special:
            if special not in ("cancel", "save", "add"):
                self._raise_view_error(
                    _("Invalid special '%(value)s' in button", value=special),
                    node,
                )
        elif type_ == "object":
            if name:
                func = getattr(name_manager.model, name, None)
                if not func:
                    msg = _(
                        "%(action_name)s is not a valid action on %(model_name)s",
                        action_name=name,
                        model_name=name_manager.model._name,
                    )
                    self._raise_view_error(msg, node)
                # get_public_method(name_manager.model, name) is too slow for this validation, a more naive check is acceptable.
                if name.startswith("_") or (
                    hasattr(func, "_api_private") and func._api_private
                ):
                    msg = _(
                        "%(method)s on %(model)s is private and cannot be called from a button",
                        method=name,
                        model=name_manager.model._name,
                    )
                    self._raise_view_error(msg, node)
                try:
                    inspect.signature(func).bind()
                except TypeError:
                    msg = "%s on %s has parameters and cannot be called from a button"
                    self._log_view_warning(msg % (name, name_manager.model._name), node)
                name_manager.has_action(name)
        elif type_ == "action":
            if name:
                name_manager.must_exist_action(name, node)
                name_manager.has_action(name)
        elif type_ and not (
            (
                self._is_qweb_based_view(node_info["view_type"])
                # "button" is the plain HTML type attribute passing through a
                # qweb-based arch untouched
                and type_
                in ("open", "archive", "unarchive", "delete", "set_cover", "button")
            )
            # the list renderer handles type="edit" itself (group/record edit
            # buttons, see web list_renderer.xml); inside <groupby> blocks the
            # nested validation pass runs with view_type="groupby"
            or (node_info["view_type"] in ("list", "groupby") and type_ == "edit")
        ):
            # Unknown button types used to be silently accepted (and skipped the
            # icon accessibility check below). Only a warning — not an error —
            # because custom client renderers may legitimately handle extra
            # types (e.g. kanban handles open/archive/unarchive/delete/
            # set_cover, matched above for qweb-based views).
            self._log_view_warning(f"Unknown button type {type_!r}", node)

        if node.get("icon"):
            description = f"A button with icon attribute ({node.get('icon')})"
            self._validate_fa_class_accessibility(node, description)

    def _validate_tag_groupby(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        # groupby nodes should be considered as nested view because they may
        # contain fields on the comodel
        name = node.get("name")
        if not name:
            return
        field = name_manager.model._fields.get(name)
        if field:
            if node_info["validate"]:
                if field.type != "many2one":
                    msg = _(
                        "Field '%(name)s' found in 'groupby' node can only be of type many2one, found %(type)s",
                        name=field.name,
                        type=field.type,
                    )
                    self._raise_view_error(msg, node)
                domain = node_info["editable"] and field._description_domain(self.env)
                if isinstance(domain, str):
                    desc = f"domain of python field '{name}'"
                    self._validate_domain_identifiers(
                        node,
                        name_manager,
                        domain,
                        desc,
                        field.comodel_name,
                        node_info,
                    )

            # move all children nodes into a new node <groupby>
            groupby_node = E.groupby(*node)
            # validate the node as a nested view
            self._validate_view(
                groupby_node,
                field.comodel_name,
                view_type="groupby",
                editable=False,
                node_info=node_info,
            )
            name_manager.has_field(node, name, node_info)

        elif node_info["validate"]:
            msg = _(
                "Field '%(field)s' found in 'groupby' node does not exist in model %(model)s",
                field=name,
                model=name_manager.model._name,
            )
            self._raise_view_error(msg, node)

    def _validate_tag_searchpanel(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if not node_info["validate"]:
            return
        for child in node.iterchildren(tag=etree.Element):
            if child.get("domain") and child.get("select") != "multi":
                msg = _(
                    "Searchpanel items with a domain attribute must have select='multi'."
                )
                self._raise_view_error(msg, child)

    def _validate_tag_label(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if not node_info["validate"]:
            return
        for_ = node.get("for")
        if not for_:
            msg = _(
                'Label tag must contain a "for". To match label style '
                "without corresponding field or button, use 'class=\"o_form_label\"'."
            )
            self._raise_view_error(msg, node)
        else:
            name_manager.must_have_name(for_, '<label for="...">')

    def _validate_tag_page(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if not node_info["validate"]:
            return
        if node.getparent() is None or node.getparent().tag != "notebook":
            self._raise_view_error(_("Page direct ancestor must be notebook"), node)

    def _validate_tag_img(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if node_info["validate"] and not any(node.get(alt) for alt in att_names("alt")):
            self._log_view_warning("<img> tag must contain an alt attribute", node)

    def _validate_tag_a(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if node_info["validate"] and any(
            "btn" in node.get(cl, "") for cl in att_names("class")
        ):
            if node.get("role") != "button":
                msg = '"<a>" tag with "btn" class must have "button" role'
                self._log_view_warning(msg, node)

    def _validate_tag_ul(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if node_info["validate"]:
            # was applied to all nodes, but in practice only used on div and ul
            self._check_dropdown_menu(node)

    def _validate_tag_div(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        if node_info["validate"]:
            self._check_dropdown_menu(node)
            self._check_progress_bar(node)

    # ------------------------------------------------------
    # Validation tools
    # ------------------------------------------------------

    def _check_dropdown_menu(self, node: _Element) -> None:
        for msg in check_dropdown_menu(node):
            self._log_view_warning(msg, node)

    def _check_progress_bar(self, node: _Element) -> None:
        for msg in check_progress_bar(node):
            self._log_view_warning(msg, node)

    def _is_qweb_based_view(self, view_type: str) -> bool:
        return view_type == "kanban"

    def _validate_attributes(
        self,
        node: _Element,
        name_manager: NameManager,
        node_info: dict[str, Any],
    ) -> None:
        """Generic validation of node attributes."""

        # python expressions for readonly, invisible, ... evaluated client-side
        for attr in VIEW_MODIFIERS:
            py_expression = node.attrib.get(attr)
            if py_expression:
                self._validate_expression(
                    node,
                    name_manager,
                    py_expression,
                    attr,
                    node_info,
                )

        for attr, expr in node.items():
            if attr in ("class", "t-att-class", "t-attf-class"):
                self._validate_classes(node, expr)

            elif attr == "context":
                try:
                    vnames = get_expression_field_names(expr)
                except SyntaxError as e:
                    message = _(
                        "Invalid context: “%(expr)s” is not a valid Python expression \n\n %(error)s",
                        expr=expr,
                        error=e,
                    )
                    self._raise_view_error(message)
                if vnames:
                    name_manager.must_have_fields(
                        node, vnames, node_info, ("context", expr)
                    )
                for key, val_ast in get_dict_asts(expr).items():
                    if key == "group_by":  # only in context
                        if not isinstance(val_ast, ast.Constant) or not isinstance(
                            val_ast.value, str
                        ):
                            msg = _(
                                '"group_by" value must be a string %(attribute)s=“%(value)s”',
                                attribute=attr,
                                value=expr,
                            )
                            self._raise_view_error(msg, node)
                        group_by = val_ast.value
                        fname = group_by.split(":")[0]
                        if fname not in name_manager.model._fields:
                            msg = _(
                                'Unknown field “%(field)s” in "group_by" value in %(attribute)s=“%(value)s”',
                                field=fname,
                                attribute=attr,
                                value=expr,
                            )
                            self._raise_view_error(msg, node)

            elif attr in ("col", "colspan"):
                # col check is mainly there for the tag 'group', but previous
                # check was generic in view form
                if not expr.isdigit():
                    self._raise_view_error(
                        _(
                            "“%(attribute)s” value must be an integer (%(value)s)",
                            attribute=attr,
                            value=expr,
                        ),
                        node,
                    )

            elif attr.startswith("decoration-"):
                vnames = get_expression_field_names(expr)
                if vnames:
                    name_manager.must_have_fields(node, vnames, node_info, (attr, expr))

            elif attr == "data-bs-toggle" and expr == "tab":
                if node.get("role") != "tab":
                    msg = 'tab link (data-bs-toggle="tab") must have "tab" role'
                    self._log_view_warning(msg, node)
                aria_control = node.get("aria-controls") or node.get(
                    "t-att-aria-controls"
                )
                if not aria_control and not node.get("t-attf-aria-controls"):
                    msg = 'tab link (data-bs-toggle="tab") must have "aria_control" defined'
                    self._log_view_warning(msg, node)
                if aria_control and "#" in aria_control:
                    msg = 'aria-controls in tablink cannot contains "#"'
                    self._log_view_warning(msg, node)

            elif attr == "role" and expr in ("presentation", "none"):
                msg = (
                    "A role cannot be `none` or `presentation`. "
                    "All your elements must be accessible with screen readers, describe it."
                )
                self._log_view_warning(msg, node)

            elif attr == "group":
                msg = "attribute 'group' is not valid.  Did you mean 'groups'?"
                self._log_view_warning(msg, node)

            elif _TOOLTIP_ATTR_RE.match(attr):
                self._raise_view_error(
                    _("Forbidden attribute used in arch (%s).", attr), node
                )

            elif attr.startswith("t-"):
                self._validate_qweb_directive(node, attr, node_info["view_type"])
                if COMP_REGEX.search(expr):
                    self._raise_view_error(
                        _("Forbidden use of `__comp__` in arch."), node
                    )

    def _validate_classes(self, node: _Element, expr: str) -> None:
        """Validate the classes present on node."""
        for msg in check_class_accessibility(node, expr):
            self._log_view_warning(msg, node)

    def _validate_fa_class_accessibility(
        self, node: _Element, description: str
    ) -> None:
        for msg in check_fa_class_accessibility(node, description):
            self._log_view_warning(msg, node)

    def _validate_qweb_directive(
        self, node: _Element, directive: str, view_type: str
    ) -> None:
        """Validate that a ``t-*`` directive is allowed in the arch for the
        given ``view_type``.

        Owl directives shouldn't appear directly in archs, but some views (e.g.
        kanban) compile archs to owl templates and accept a wider set.
        """
        allowed = (
            _QWEB_DIRECTIVES_ALLOWED_TEMPLATE
            if self._is_qweb_based_view(view_type)
            else _QWEB_DIRECTIVES_ALLOWED
        )
        if not allowed.match(directive):
            self._raise_view_error(
                _("Forbidden owl directive used in arch (%s).", directive), node
            )

    def _validate_expression(
        self,
        node: _Element,
        name_manager: NameManager,
        py_expression: str,
        attr: str,
        node_info: dict[str, Any],
    ) -> None:
        try:
            if py_expression.lower() in ("0", "false", "1", "true"):
                # most (~95%) elements are 1/True/0/False
                return
            fnames = get_expression_field_names(py_expression)
        except (SyntaxError, ValueError, AttributeError) as e:
            msg = _(
                "Invalid %(use)s: “%(expr)s”\n%(error)s",
                use=f"modifier {attr!r}",
                expr=py_expression,
                error=e,
            )
            self._raise_view_error(msg, node, from_exception=e)
        name_manager.must_have_fields(node, fnames, node_info, (attr, py_expression))

    def _validate_domain_identifiers(
        self,
        node: _Element,
        name_manager: NameManager,
        domain: str,
        use: str,
        target_model: str,
        node_info: dict[str, Any],
    ) -> None:
        try:
            fnames, vnames = get_domain_value_names(domain)
        except (SyntaxError, ValueError, AttributeError) as e:
            msg = _(
                "Invalid %(use)s: “%(expr)s”\n%(error)s",
                use=use,
                expr=domain,
                error=e,
            )
            self._raise_view_error(msg, node, from_exception=e)

        self._check_field_paths(node, fnames, target_model, f"{use} ({domain})")
        name_manager.must_have_fields(node, vnames, node_info, ("domain", domain))

    def _check_field_paths(
        self, node: _Element, field_paths: set[str], model_name: str, use: str
    ) -> None:
        """Check whether the given field paths (dot-separated field names)
        correspond to actual sequences of fields on the given model.
        """
        for field_path in field_paths:
            names = field_path.split(".")
            Model = self.pool[model_name]
            if names[0] == "parent":
                continue
            for index, name in enumerate(names):
                if Model is None:
                    msg = _(
                        "Non-relational field “%(field)s” in path “%(field_path)s” in %(use)s)",
                        field=names[index - 1],
                        field_path=field_path,
                        use=use,
                    )
                    self._raise_view_error(msg, node)
                try:
                    field = Model._fields[name]
                except KeyError:
                    msg = _(
                        'Unknown field "%(model)s.%(field)s" in %(use)s)',
                        model=Model._name,
                        field=name,
                        use=use,
                    )
                    self._raise_view_error(msg, node)
                if not field._description_searchable:
                    msg = _(
                        "Unsearchable field “%(field)s” in path “%(field_path)s” in %(use)s)",
                        field=name,
                        field_path=field_path,
                        use=use,
                    )
                    self._raise_view_error(msg, node)
                Model = self.pool.get(field.comodel_name)

    # ------------------------------------------------------
    # QWeb template views
    # ------------------------------------------------------

    def _read_template_keys(self) -> list[str]:
        """Return the list of context keys to use for caching ``_read_template``."""
        return ["lang", "inherit_branding", "edit_translations"]

    def _get_view_etrees(self) -> list[_Element]:
        if not self:
            return []
        arch_trees = self._get_combined_archs()
        for arch_tree in arch_trees:
            self.distribute_branding(arch_tree)
        return arch_trees

    def _contains_branded(self, node: _Element) -> bool:
        return (
            node.tag == "t"
            or "t-raw" in node.attrib
            or "t-call" in node.attrib
            or any(self.is_node_branded(child) for child in node.iterdescendants())
        )

    def _pop_view_branding(self, element: _Element) -> dict[str, str]:
        return {
            attribute: element.attrib.pop(attribute)
            for attribute in MOVABLE_BRANDING
            if element.get(attribute)
        }

    def distribute_branding(
        self,
        e: _Element,
        branding: dict[str, str] | None = None,
        parent_xpath: str = "",
        index_map: Any = ConstantMapping(1),
    ) -> None:
        if e.get("t-ignore") or e.tag == "head":
            # remove any view branding possibly injected by inheritance
            attrs = set(MOVABLE_BRANDING)
            for descendant in e.iterdescendants(tag=etree.Element):
                if not attrs.intersection(descendant.attrib):
                    continue
                self._pop_view_branding(descendant)

            # Remove the processing instructions indicating where nodes were
            # removed (see apply_inheritance_specs)
            for descendant in e.iterdescendants(tag=etree.ProcessingInstruction):
                if descendant.target == "apply-inheritance-specs-node-removal":
                    descendant.getparent().remove(descendant)
            return

        node_path = e.get("data-oe-xpath")
        if node_path is None:
            # Handle special case for jump points defined by the magic template
            # <t>$0</t>. No branding is allowed in this case since it points to
            # a generic template.
            if e.get("data-oe-no-branding"):
                e.attrib.pop("data-oe-no-branding")
                return
            node_path = f"{parent_xpath}/{e.tag}[{index_map[e.tag]}]"
        if branding:
            if e.get("t-field"):
                e.set("data-oe-xpath", node_path)
            elif not e.get("data-oe-model"):
                e.attrib.update(branding)
                e.set("data-oe-xpath", node_path)
        if not e.get("data-oe-model"):
            return

        if {"t-esc", "t-raw", "t-out"}.intersection(e.attrib):
            # nodes which fully generate their content and have no reason to
            # be branded because they can not sensibly be edited
            self._pop_view_branding(e)
        elif self._contains_branded(e):
            # if a branded element contains branded elements distribute own
            # branding to children unless it's t-raw, then just remove branding
            # on current element
            distributed_branding = self._pop_view_branding(e)

            if "t-raw" not in e.attrib:
                # running index by tag type, for XPath query generation
                indexes = collections.defaultdict(lambda: 0)
                for child in e.iterchildren(etree.Element, etree.ProcessingInstruction):
                    if child.get("data-oe-xpath"):
                        # injected by view inheritance, skip otherwise
                        # generated xpath is incorrect
                        self.distribute_branding(child)
                    elif child.tag is etree.ProcessingInstruction:
                        # If a node is known to have been replaced during
                        # applying an inheritance, increment its index to
                        # compute an accurate xpath for subsequent nodes
                        if child.target == "apply-inheritance-specs-node-removal":
                            indexes[child.text] += 1
                            e.remove(child)
                    else:
                        indexes[child.tag] += 1
                        self.distribute_branding(
                            child,
                            distributed_branding,
                            parent_xpath=node_path,
                            index_map=indexes,
                        )

    def is_node_branded(self, node: _Element) -> bool:
        """Return whether a node is branded or qweb-active: it bears a
        ``data-oe-model``, ``groups`` or ``t-*`` attribute, or is an
        apply-inheritance-specs node-removal processing instruction.
        """
        return any(
            (attr in ("data-oe-model", "groups") or (attr.startswith("t-")))
            for attr in node.attrib
        ) or (
            node.tag is etree.ProcessingInstruction
            and node.target == "apply-inheritance-specs-node-removal"
        )

    @api.readonly
    @api.model
    def render_public_asset(
        self, template: int | str, values: dict[str, Any] | None = None
    ) -> Markup:
        self._get_template_view(template)._check_view_access()
        return self.env["ir.qweb"].sudo()._render(template, values)

    def _render_template(
        self, template: int | str, values: dict[str, Any] | None = None
    ) -> Markup:
        return self.env["ir.qweb"]._render(template, values)

    # ------------------------------------------------------
    # Misc
    # ------------------------------------------------------

    @api.model
    def _validate_custom_views(self, model: str) -> bool:
        """Validate architecture of custom views (= without xml id) for a given model.
        This method is called at the end of registry update.
        """
        rec = self.browse(
            id_
            for (id_,) in self.env.execute_query(
                SQL(
                    """
                   SELECT max(v.id)
                     FROM ir_ui_view v
                LEFT JOIN ir_model_data md ON (md.model = 'ir.ui.view' AND md.res_id = v.id)
                    WHERE md.module IN (SELECT name FROM ir_module_module) IS NOT TRUE
                      AND v.model = %s
                      AND v.active = true
                 GROUP BY coalesce(v.inherit_id, v.id)
                 """,
                    model,
                )
            )
        )
        return rec.with_context({"load_all_views": True})._check_xml()

    @api.model
    def _validate_module_views(self, module: str) -> None:
        """Validate the architecture of all the views of a given module that
        are impacted by view updates, but have not been checked yet.
        """
        if not self.pool._init:
            msg = "_validate_module_views() must only be called during module initialization"
            raise RuntimeError(msg)

        # only validate the views that still exist...
        prefix = module + "."
        prefix_len = len(prefix)
        names = tuple(
            xmlid[prefix_len:]
            for xmlid in self.pool.loaded_xmlids
            if xmlid.startswith(prefix)
        )
        if not names:
            return

        # retrieve the views with an XML id that has not been checked yet, i.e.,
        # the views with noupdate=True on their xml id
        views = self.browse(
            id_
            for (id_,) in self.env.execute_query(
                SQL(
                    """
            SELECT v.id
            FROM ir_ui_view v
            JOIN ir_model_data md ON (md.model = 'ir.ui.view' AND md.res_id = v.id)
            WHERE md.module = %s AND md.name = ANY(%s) AND md.noupdate
        """,
                    module,
                    list(names),
                )
            )
        )

        views._check_xml()

    def _create_all_specific_views(self, processed_modules: list[str]) -> None:
        """To be overridden and have specific view behaviour on create."""
        pass

    def _get_specific_views(self) -> Self:
        """Given a view, return a record set containing all the specific views
        for that view's key.
        """
        self.ensure_one()
        # Only qweb views have a specific counterpart
        if self.type != "qweb":
            return self.env["ir.ui.view"]
        # A specific view can have an xml_id if exported/imported, but it will not be equal to its key (only generic views will).
        return (
            self.with_context(active_test=False)
            .search([("key", "=", self.key)])
            .filtered(lambda r: r.xml_id != r.key)
        )

    def _load_records_write(self, values: dict[str, Any]) -> None:
        """During module update, when updating a generic view, we should also
        update its specific views (COW'd).
        We only update unmodified fields, mimicking the
        noupdate behavior on views having an ir.model.data.
        """
        if self.type == "qweb":
            for cow_view in self._get_specific_views():
                authorized_vals = {
                    key: value
                    for key, value in values.items()
                    if key != "inherit_id" and cow_view[key] == self[key]
                }
                # if inherit_id update, replicate change on cow view but
                # only if that cow view inherit_id wasn't manually changed
                inherit_id = values.get("inherit_id")
                if (
                    inherit_id
                    and self.inherit_id.id != inherit_id
                    and cow_view.inherit_id.key == self.inherit_id.key
                ):
                    self._load_records_write_on_cow(
                        cow_view, inherit_id, authorized_vals
                    )
                else:
                    cow_view.with_context(no_cow=True).write(authorized_vals)
        super()._load_records_write(values)

    def _load_records_write_on_cow(
        self, cow_view: Self, inherit_id: int, values: dict[str, Any]
    ) -> None:
        # for modules updated before `website`, we need to
        # store the change to replay later on cow views
        if not hasattr(self.pool, "website_views_to_adapt"):
            self.pool.website_views_to_adapt = []
        self.pool.website_views_to_adapt.append(
            (
                cow_view.id,
                inherit_id,
                values,
            )
        )
