import base64
import functools
import logging
import platform
from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from types import NotImplementedType
from typing import TYPE_CHECKING, Any, NamedTuple, Self

import lxml.html
import psycopg
from docutils import nodes
from docutils.core import publish_string
from docutils.transforms import Transform, writer_aux
from docutils.writers.html4css1 import Writer
from markupsafe import Markup

from odoo import _, api, fields, models, modules, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessDenied, UserError, ValidationError
from odoo.fields import Domain
from odoo.http import request
from odoo.libs.parse_version import parse_version
from odoo.modules.module import (
    Manifest,
    MissingDependencyError,
    module_content_checksum,
)
from odoo.tools import SQL, config
from odoo.tools.misc import get_flag, topological_sort
from odoo.tools.sql import column_exists
from odoo.tools.translate import (
    TranslationImporter,
    get_datafile_translation_path,
    get_po_paths,
)

from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

_logger = logging.getLogger(__name__)

ACTION_DICT = {
    "view_mode": "form",
    "res_model": "base.module.upgrade",
    "target": "new",
    "type": "ir.actions.act_window",
}


class UpdateListResult(NamedTuple):
    """Outcome of ir.module.module.update_list(): module records changed."""

    updated: int
    added: int


def assert_log_admin_access[T](method: T, /) -> T:
    """Require the caller to be an administrator, logging allow/deny; raise AccessDenied otherwise."""

    @functools.wraps(method)
    def check_and_log(self, *args: Any, **kwargs: Any) -> Any:
        user = self.env.user
        origin = request.httprequest.remote_addr if request else "n/a"
        log_data = (
            method.__name__,
            self.sudo().mapped("display_name"),
            user.login,
            user.id,
            origin,
        )
        if not self.env.is_admin():
            _logger.warning(
                "DENY access to module.%s on %s to user %s ID #%s via %s",
                *log_data,
            )
            raise AccessDenied
        _logger.info("ALLOW access to module.%s on %s to user %s #%s via %s", *log_data)
        return method(self, *args, **kwargs)

    return check_and_log


class IrModuleCategory(models.Model):
    _name = "ir.module.category"
    _description = "Application"
    _order = "sequence, name, id"
    _allow_sudo_commands = False

    name = fields.Char(string="Name", required=True, translate=True)
    parent_id = fields.Many2one(
        "ir.module.category", string="Parent Application", index=True
    )
    child_ids = fields.One2many(
        "ir.module.category", "parent_id", string="Child Applications"
    )
    module_ids = fields.One2many("ir.module.module", "category_id", string="Modules")
    privilege_ids = fields.One2many(
        "res.groups.privilege", "category_id", string="Privileges"
    )
    description = fields.Text(string="Description", translate=True)
    sequence = fields.Integer(string="Sequence")
    visible = fields.Boolean(string="Visible", default=True)
    exclusive = fields.Boolean(string="Exclusive")
    xml_id = fields.Char(string="External ID", compute="_compute_xml_id")

    def _compute_xml_id(self) -> None:
        """Compute the first external id of each category, if any."""
        xml_ids = defaultdict(list)
        domain = [("model", "=", self._name), ("res_id", "in", self.ids)]
        for data in (
            self.env["ir.model.data"]
            .sudo()
            .search_read(domain, ["module", "name", "res_id"])
        ):
            xml_ids[data["res_id"]].append(f"{data['module']}.{data['name']}")
        for cat in self:
            cat.xml_id = xml_ids.get(cat.id, [""])[0]

    @api.constrains("parent_id")
    def _check_parent_not_circular(self) -> None:
        """Forbid cycles in the category hierarchy."""
        if self._has_cycle():
            raise ValidationError(_("Error ! You cannot create recursive categories."))


class MyFilterMessages(Transform):
    """Remove ``system_message`` nodes, logging each at DEBUG.

    The standard ``report_level`` filter would drop them without logging.
    """

    default_priority = 870

    def apply(self) -> None:
        # `findall` exists since docutils 0.18 and requirements.txt pins 0.22.x
        for node in self.document.findall(nodes.system_message):
            _logger.debug("docutils' system message present: %s", node)
            node.parent.remove(node)


class MyWriter(Writer):
    """Custom docutils html4css1 writer that keeps warnings out of the output document."""

    def get_transforms(self) -> list[type[Transform]]:
        return [MyFilterMessages, writer_aux.Admonitions]


STATES = [
    ("uninstallable", "Uninstallable"),
    ("uninstalled", "Not Installed"),
    ("installed", "Installed"),
    ("to upgrade", "To be upgraded"),
    ("to remove", "To be removed"),
    ("to install", "To be installed"),
]

# Recursive closures over the module dependency graph, resolved in one round-trip.
# The two variants differ only in join direction: downstream walks to dependents,
# upstream to dependencies. Excluded-state or blocked modules are pruned and thus
# block paths through them; seeds are traversed but excluded from the result.
_DOWNSTREAM_CLOSURE_QUERY = """
    WITH RECURSIVE closure(id, name) AS (
        SELECT m.id, m.name
        FROM ir_module_module m
        WHERE m.id = ANY(%(seed_ids)s)
    UNION
        SELECT m.id, m.name
        FROM closure c
        JOIN ir_module_module_dependency d ON d.name = c.name
        JOIN ir_module_module m ON m.id = d.module_id
        WHERE m.state != ALL(%(exclude_states)s)
          AND m.id != ALL(%(blocked_ids)s)
    )
    SELECT id FROM closure WHERE id != ALL(%(seed_ids)s)
"""

_UPSTREAM_CLOSURE_QUERY = """
    WITH RECURSIVE closure(id, name) AS (
        SELECT m.id, m.name
        FROM ir_module_module m
        WHERE m.id = ANY(%(seed_ids)s)
    UNION
        SELECT m.id, m.name
        FROM closure c
        JOIN ir_module_module_dependency d ON d.module_id = c.id
        JOIN ir_module_module m ON m.name = d.name
        WHERE m.state != ALL(%(exclude_states)s)
          AND m.id != ALL(%(blocked_ids)s)
    )
    SELECT id FROM closure WHERE id != ALL(%(seed_ids)s)
"""


class IrModuleModule(models.Model):
    _name = "ir.module.module"
    _rec_name = "shortdesc"
    _rec_names_search = ["name", "shortdesc", "summary"]
    _description = "Module"
    _order = "application desc,sequence,name"
    _allow_sudo_commands = False

    name = fields.Char("Technical Name", readonly=True, required=True)
    category_id = fields.Many2one(
        "ir.module.category", string="Category", readonly=True, index=True
    )
    shortdesc = fields.Char("Module Name", readonly=True, translate=True)
    summary = fields.Char("Summary", readonly=True, translate=True)
    description = fields.Text("Description", readonly=True, translate=True)
    description_html = fields.Html(
        "Description HTML", compute="_compute_description_html"
    )
    author = fields.Char("Author", readonly=True)
    maintainer = fields.Char("Maintainer", readonly=True)
    contributors = fields.Text("Contributors", readonly=True)
    website = fields.Char("Website", readonly=True)

    # `manifest_version` is the version declared in the module's __manifest__.py
    # on disk; `db_version` is the version persisted on the last successful
    # install/upgrade; `published_version` is the version available on the
    # remote module repository.
    manifest_version = fields.Char(
        "Manifest Version", compute="_compute_manifest_version"
    )
    db_version = fields.Char("Installed Version", readonly=True)
    published_version = fields.Char("Published Version", readonly=True)

    url = fields.Char("URL", readonly=True)
    sequence = fields.Integer("Sequence", default=100)
    dependencies_id = fields.One2many(
        "ir.module.module.dependency",
        "module_id",
        string="Dependencies",
        readonly=True,
    )
    country_ids = fields.Many2many(
        "res.country", "module_country", "module_id", "country_id"
    )
    exclusion_ids = fields.One2many(
        "ir.module.module.exclusion",
        "module_id",
        string="Exclusions",
        readonly=True,
    )
    auto_install = fields.Boolean(
        "Automatic Installation",
        help="An auto-installable module is automatically installed by the "
        "system when all its dependencies are satisfied. "
        "If the module has no dependency, it is always installed.",
    )
    state = fields.Selection(
        STATES,
        string="Status",
        default="uninstallable",
        readonly=True,
        index=True,
    )
    demo = fields.Boolean("Demo Data", default=False, readonly=True)
    license = fields.Selection(
        [
            ("GPL-2", "GPL Version 2"),
            ("GPL-2 or any later version", "GPL-2 or later version"),
            ("GPL-3", "GPL Version 3"),
            ("GPL-3 or any later version", "GPL-3 or later version"),
            ("AGPL-3", "Affero GPL-3"),
            ("LGPL-3", "LGPL Version 3"),
            ("Other OSI approved licence", "Other OSI Approved License"),
            ("OEEL-1", "Odoo Enterprise Edition License v1.0"),
            ("OPL-1", "Odoo Proprietary License v1.0"),
            ("Other proprietary", "Other Proprietary"),
        ],
        string="License",
        default="LGPL-3",
        readonly=True,
    )
    menus_by_module = fields.Text(
        string="Menus", compute="_compute_views_by_module", store=True
    )
    reports_by_module = fields.Text(
        string="Reports", compute="_compute_views_by_module", store=True
    )
    views_by_module = fields.Text(
        string="Views", compute="_compute_views_by_module", store=True
    )
    application = fields.Boolean("Application", readonly=True)
    icon = fields.Char("Icon URL")
    icon_image = fields.Binary(string="Icon", compute="_compute_icon_image")
    icon_flag = fields.Char(string="Flag", compute="_compute_icon_image")
    to_buy = fields.Boolean("Odoo Enterprise Module", default=False)
    has_iap = fields.Boolean(compute="_compute_has_iap")
    # Written by odoo.modules.loading.load_data (raw SQL) after each successful
    # upgrade: {"v": 1, "files": {<filename>: {"sha": ..., "xmlids": [...],
    # "dyn": bool}}}.  Lets the next upgrade skip converting data files whose
    # content did not change.  Not meant to be edited through the ORM.
    data_file_checksums = fields.Json(readonly=True, prefetch=False)
    # sha256 of the module directory at its last successful install/upgrade
    # (see odoo.modules.module.module_content_checksum), stamped by
    # load_module_graph.  button_upgrade uses it to leave unchanged modules
    # out of upgrade cascades.
    content_checksum = fields.Char(readonly=True, prefetch=False)

    _name_uniq = models.Constraint(
        "UNIQUE (name)",
        "The name of the module must be unique!",
    )

    @classmethod
    def get_module_info(cls, name: str) -> dict[str, Any] | Manifest:
        """Return the manifest of the named addon, or ``{}`` if unavailable.

        There is no manifest for studio_customization and imported modules.
        """
        return modules.Manifest.for_addon(name, display_warning=False) or {}

    @api.depends("name", "description")
    def _compute_description_html(self) -> None:
        """Render the module description (index.html or rst) as sanitized HTML."""

        def _apply_description_images(doc: str) -> str:
            html = lxml.html.document_fromstring(doc)
            for element, _attribute, _link, _pos in html.iterlinks():
                if (
                    element.get("src")
                    and "//" not in element.get("src")
                    and "static/" not in element.get("src")
                ):
                    element.set(
                        "src",
                        f"/{module.name}/static/description/{element.get('src')}",
                    )
            return tools.html_sanitize(lxml.html.tostring(html, encoding="unicode"))

        for module in self:
            if not module.name:
                module.description_html = False
                continue
            path = str(Path(module.name, "static/description/index.html"))
            doc = None
            try:
                with tools.file_open(path, "rb") as desc_file:
                    # Backs the form and module loading (_check reads it), so a
                    # bad/empty index.html must never raise; fall back to manifest.
                    doc = desc_file.read().decode(errors="replace").strip()
            except FileNotFoundError:
                doc = None

            if doc:
                module.description_html = _apply_description_images(doc)
                continue

            overrides = {
                "embed_stylesheet": False,
                "doctitle_xform": False,
                "output_encoding": "unicode",
                "xml_declaration": False,
                "file_insertion_enabled": False,
            }
            raw_description = module.description or ""

            try:
                output = publish_string(
                    source=raw_description,
                    settings_overrides=overrides,
                    writer=MyWriter(),
                )
            except Exception as e:
                _logger.warning(
                    "Failed to render module description for %s: %s. Falling back to raw description.",
                    module.name,
                    e,
                )
                output = Markup("<pre><code>%s</code></pre>") % raw_description

            module.description_html = _apply_description_images(output)

    @api.depends("name")
    def _compute_manifest_version(self) -> None:
        """Compute the version declared in the on-disk manifest."""
        default_version = modules.adapt_version("1.0")
        for module in self:
            module.manifest_version = self.get_module_info(module.name).get(
                "version", default_version
            )

    @api.depends("name", "state")
    def _compute_views_by_module(self) -> None:
        """Compute the lists of views, reports and menus owned by the modules."""
        IrModelData = self.env["ir.model.data"].with_context(active_test=True)
        dmodels = ["ir.ui.view", "ir.actions.report", "ir.ui.menu"]

        # Skip uninstalled modules, no data to find anyway.
        active_mods = self.filtered(
            lambda m: m.state in ("installed", "to upgrade", "to remove")
        )
        for module in self - active_mods:
            module.views_by_module = ""
            module.reports_by_module = ""
            module.menus_by_module = ""
        if not active_mods:
            return

        # One batched ir.model.data search for the whole recordset; this stored
        # compute fires for many modules at once, so per-module search is O(n) queries.
        imd_per_module: defaultdict[str, defaultdict[str, list[int]]] = defaultdict(
            lambda: defaultdict(list)
        )
        imd_domain = [
            ("module", "in", [m.name for m in active_mods]),
            ("model", "in", dmodels),
        ]
        for data in IrModelData.sudo().search(imd_domain):
            imd_per_module[data.module][data.model].append(data.res_id)

        def existing(model):
            # Runs before the module update, so some xmlids may be dangling;
            # filter records to the existing ones before reading them.
            ids = [
                res_id
                for per_model in imd_per_module.values()
                for res_id in per_model[model]
            ]
            return self.env[model].browse(ids).exists()

        def format_view(v):
            prefix = "* INHERIT " if v.inherit_id else ""
            return f"{prefix}{v.name} ({v.type})"

        views = {v.id: format_view(v) for v in existing("ir.ui.view")}
        reports = {r.id: r.name for r in existing("ir.actions.report")}
        menus = {m.id: m.complete_name for m in existing("ir.ui.menu")}

        for module in active_mods:
            imd_models = imd_per_module[module.name]
            module.views_by_module = "\n".join(
                sorted(views[i] for i in imd_models["ir.ui.view"] if i in views)
            )
            module.reports_by_module = "\n".join(
                sorted(
                    reports[i] for i in imd_models["ir.actions.report"] if i in reports
                )
            )
            module.menus_by_module = "\n".join(
                sorted(menus[i] for i in imd_models["ir.ui.menu"] if i in menus)
            )

    @api.depends("icon")
    def _compute_icon_image(self) -> None:
        """Compute the module icon (base64) and its country flag glyph."""
        # Pre-assign both fields: records skipped below (NewIds) must still get
        # every field of this compute assigned.
        self.icon_image = ""
        self.icon_flag = ""
        for module in self:
            if not module.id:
                continue
            manifest = self.get_module_info(module.name)
            if module.icon:
                path = module.icon
            elif manifest:
                path = manifest.get("icon", "")
            else:
                path = Manifest.for_addon("base").icon
            path = path.removeprefix("/")
            if path:
                # module.icon is user-writable: the filter_ext whitelist and
                # file_open's addons-path sandbox prevent arbitrary file reads.
                # Load-bearing security controls; do not drop them.
                try:
                    with tools.file_open(
                        path,
                        "rb",
                        filter_ext=(".png", ".svg", ".gif", ".jpeg", ".jpg"),
                    ) as image_file:
                        module.icon_image = base64.b64encode(image_file.read())
                except OSError:
                    module.icon_image = ""
            countries = manifest.get("countries", [])
            if len(countries) == 1:
                module.icon_flag = get_flag(countries[0].upper())

    def _compute_has_iap(self) -> None:
        """Compute whether the module transitively depends on the iap module."""
        # One downstream closure of 'iap' for the whole batch (module depends on
        # iap <=> it is a transitive dependent of iap), rather than one upstream
        # closure per record; test ids against a set, not recordset membership.
        iap = self.browse(self._get_id("iap") or [])
        iap_dependent_ids = set(iap.downstream_dependencies(exclude_states=())._ids)
        for module in self:
            module.has_iap = bool(module.id) and module.id in iap_dependent_ids

    @api.ondelete(at_uninstall=False)
    def _unlink_except_installed(self) -> None:
        """Forbid deleting modules that are installed or scheduled for an operation."""
        for module in self:
            if module.state in (
                "installed",
                "to upgrade",
                "to remove",
                "to install",
            ):
                raise UserError(
                    _(
                        "You are trying to remove a module that is installed or will be installed."
                    )
                )

    def unlink(self) -> bool:
        """Delete the modules and drop the "stable" cache (_get_id/_installed)."""
        self.env.registry.clear_cache("stable")
        return super().unlink()

    def _get_modules_to_load_domain(self) -> list[tuple[str, str, str]]:
        """Domain to retrieve the modules that should be loaded by the registry."""
        return [("state", "=", "installed")]

    @api.model
    def check_external_dependencies(
        self, module_name: str, newstate: str = "to install"
    ) -> None:
        """Raise a UserError if an external dependency of the module is missing.

        :param str module_name: technical name of the module to check
        :param str newstate: target state, only used to word the error message
        """
        manifest = modules.Manifest.for_addon(module_name)
        if not manifest:
            return  # unavailable module, there is no point in checking dependencies
        try:
            manifest.check_manifest_dependencies()
        except MissingDependencyError as e:
            if newstate == "to install":
                msg = _(
                    'Unable to install module "%(module)s" because an external dependency is not met: %(dependency)s',
                    module=module_name,
                    dependency=e.dependency,
                )
            elif newstate == "to upgrade":
                msg = _(
                    'Unable to upgrade module "%(module)s" because an external dependency is not met: %(dependency)s',
                    module=module_name,
                    dependency=e.dependency,
                )
            else:
                msg = _(
                    'Unable to process module "%(module)s" because an external dependency is not met: %(dependency)s',
                    module=module_name,
                    dependency=e.dependency,
                )

            install_package = None
            if platform.system() == "Linux":
                try:
                    distro = platform.freedesktop_os_release()
                except OSError:
                    # no os-release file (minimal containers): the apt hint
                    # is best-effort and must not mask the UserError below
                    distro = {}
                id_likes = {distro.get("ID", ""), *distro.get("ID_LIKE", "").split()}
                if "debian" in id_likes or "ubuntu" in id_likes:
                    if (
                        package := manifest["external_dependencies"]
                        .get("apt", {})
                        .get(e.dependency)
                    ):
                        install_package = f"apt install {package}"

            if install_package:
                msg += _("\nIt can be installed running: %s", install_package)

            raise UserError(msg) from e

    def _state_update(
        self, newstate: str, states_to_update: list[str], level: int = 100
    ) -> None:
        """Set ``newstate`` on the modules and, recursively, their dependencies.

        :param str newstate: target state
        :param list states_to_update: only modules in these states are updated
        :param int level: recursion budget, guards against dependency cycles
        """
        if level < 1:
            raise UserError(
                _(
                    "Recursion error in modules dependencies (while processing: %s)!",
                    ", ".join(self.mapped("name")) or "?",
                )
            )

        for module in self:
            if module.state not in states_to_update:
                continue

            # partition dependencies into those to update and those already ready
            update_ids, ready_ids = [], []
            for dep in module.dependencies_id:
                if dep.state == "unknown":
                    raise UserError(
                        _(
                            'You try to install module "%(module)s" that depends on module "%(dependency)s".\nBut the latter module is not available in your system.',
                            module=module.name,
                            dependency=dep.name,
                        )
                    )
                if dep.depend_id.state == newstate:
                    ready_ids.append(dep.depend_id.id)
                else:
                    update_ids.append(dep.depend_id.id)
            update_mods = self.browse(update_ids)

            # update dependency modules that require it
            update_mods._state_update(newstate, states_to_update, level=level - 1)

            if module.state in states_to_update:
                # check dependencies and update module itself
                self.check_external_dependencies(module.name, newstate)
                module.write({"state": newstate})

    @assert_log_admin_access
    def button_install(self) -> dict[str, Any]:
        """Mark the modules and their dependencies "to install", pull in eligible
        auto-install modules, and validate module and category exclusion rules.

        :return: the upgrade-wizard action that applies the scheduled states
        :rtype: dict[str, Any]
        """
        # During install, models may have new Python fields without DB columns yet;
        # prefetch_fields=False avoids fetching them (as in _auto_init).
        env_no_prefetch = self.env(
            context=dict(self.env.context, prefetch_fields=False)
        )
        company_countries = env_no_prefetch["res.company"].search([]).country_id
        # domain to select auto-installable (but not yet installed) modules
        auto_domain = [
            ("state", "=", "uninstalled"),
            ("auto_install", "=", True),
        ]

        # An auto-install module must be installed when: all its deps are installed
        # or to be installed, at least one dep is 'to install', and (if country
        # specific) at least one company is in one of its countries.
        install_states = frozenset(("installed", "to install", "to upgrade"))

        def must_install(module):
            states = {
                dep.state for dep in module.dependencies_id if dep.auto_install_required
            }
            return (
                states <= install_states
                and "to install" in states
                and (not module.country_ids or module.country_ids & company_countries)
            )

        to_install = self
        while to_install:
            # Mark the given modules and their dependencies to be installed.
            to_install._state_update("to install", ["uninstalled"])

            # Determine which auto-installable modules must be installed.
            if config.get("skip_auto_install"):
                to_install = self.browse()
            else:
                to_install = self.search(auto_domain).filtered(must_install)

        # the modules that are installed/to install/to upgrade
        install_mods = self.search([("state", "in", list(install_states))])

        # check individual exclusions
        install_names = {module.name for module in install_mods}
        for module in install_mods:
            for exclusion in module.exclusion_ids:
                if exclusion.name in install_names:
                    raise UserError(
                        _(
                            'Modules "%(module)s" and "%(incompatible_module)s" are incompatible.',
                            module=module.shortdesc,
                            incompatible_module=exclusion.exclusion_id.shortdesc,
                        )
                    )

        # check category exclusions
        exclusives = self.env["ir.module.category"].search([("exclusive", "=", True)])
        for category in exclusives:
            # retrieve installed modules in category and sub-categories
            categories = category.search([("id", "child_of", category.ids)])
            category_mods = install_mods.filtered(
                lambda mod, categories=categories: mod.category_id in categories
            )
            # Valid if all category modules are transitive dependencies of one of
            # them. upstream_dependencies excludes the seed, so union it back in.
            if category_mods and not any(
                category_mods
                <= (module | module.upstream_dependencies(exclude_states=()))
                for module in category_mods
            ):
                labels = dict(self.fields_get(["state"])["state"]["selection"])
                raise UserError(
                    _(
                        'You are trying to install incompatible modules in category "%(category)s":%(module_list)s',
                        category=category.name,
                        module_list="".join(
                            f"\n- {module.shortdesc} ({labels[module.state]})"
                            for module in category_mods
                        ),
                    )
                )

        return dict(ACTION_DICT, name=_("Install"))

    @assert_log_admin_access
    def button_immediate_install(self) -> dict[str, Any]:
        """Install the selected modules immediately and fully.

        :return: the next res.config action to execute
        :rtype: dict[str, Any]
        """
        _logger.info("User #%d triggered module installation", self.env.uid)
        # Stash allowed companies on the thread-local request as a pseudo-global
        # env: e.g. installing a Chart of Accounts must configure it on the
        # selected company, not SUPERUSER's own.
        if request:
            request.allowed_company_ids = self.env.companies.ids
        return self._button_immediate_function(
            self.env.registry[self._name].button_install
        )

    @assert_log_admin_access
    @api.model
    def button_reset_state(self) -> bool:
        """Reset the transient module states after an interrupted operation."""
        self.search([("state", "=", "to install")]).state = "uninstalled"
        self.search([("state", "in", ("to upgrade", "to remove"))]).state = "installed"
        return True

    @api.model
    def check_module_update(self) -> bool:
        """Return whether a module operation is currently scheduled."""
        return bool(
            self.sudo().search_count(
                [("state", "in", ("to install", "to upgrade", "to remove"))],
                limit=1,
            )
        )

    @assert_log_admin_access
    def module_uninstall(self) -> bool:
        """Uninstall the modules completely, dropping the DB structures they
        created (tables, columns, constraints, ...)."""
        modules_to_remove = self.mapped("name")
        self.env["ir.model.data"]._module_data_uninstall(modules_to_remove)
        # we deactivate prefetching to not try to read a column that has been deleted
        self.with_context(prefetch_fields=False).write(
            {"state": "uninstalled", "db_version": False}
        )
        return True

    def _remove_copied_views(self) -> None:
        """Remove the view copies created by the modules in `self`.

        Copies have no external id, so ``_module_data_uninstall`` misses them;
        match on ``key`` instead. Left behind, they crash on data removed with
        the module.
        """
        domain = Domain.OR(Domain("key", "=like", m.name + ".%") for m in self)
        orphans = (
            self.env["ir.ui.view"]
            .with_context(**{"active_test": False, MODULE_UNINSTALL_FLAG: True})
            .search(domain)
        )
        orphans.unlink()

    def _dependency_closure(
        self,
        query: str,
        known_deps: Self | None,
        exclude_states: tuple[str, ...],
    ) -> Self:
        """Resolve one recursive closure over the module dependency graph.

        :param str query: one of the module-level ``*_CLOSURE_QUERY`` constants
        :param known_deps: records excluded from traversal and unioned into
            the result
        :param tuple exclude_states: module states pruned during traversal
        :return: ``known_deps`` plus the closure of ``self`` (``self`` excluded)
        :rtype: recordset
        """
        if not self:
            return self
        self.flush_model(["name", "state"])
        self.env["ir.module.module.dependency"].flush_model(["module_id", "name"])
        known_deps = known_deps or self.browse()
        self.env.cr.execute(
            query,
            {
                "seed_ids": list(self.ids),
                "exclude_states": list(exclude_states),
                "blocked_ids": list(known_deps.ids),
            },
        )
        return known_deps | self.browse([row[0] for row in self.env.cr.fetchall()])

    def downstream_dependencies(
        self,
        known_deps: Self | None = None,
        exclude_states: tuple[str, ...] = (
            "uninstalled",
            "uninstallable",
            "to remove",
        ),
    ) -> Self:
        """Return the modules that directly or indirectly depend on ``self`` and
        satisfy the ``exclude_states`` filter.

        :param known_deps: records excluded from traversal and unioned into
            the result
        :param tuple exclude_states: module states pruned during traversal;
            pass ``()`` to disable the state filter
        """
        return self._dependency_closure(
            _DOWNSTREAM_CLOSURE_QUERY, known_deps, exclude_states
        )

    def upstream_dependencies(
        self,
        known_deps: Self | None = None,
        exclude_states: tuple[str, ...] = (
            "installed",
            "uninstallable",
            "to remove",
        ),
    ) -> Self:
        """Return the modules that ``self`` directly or indirectly depends on and
        that satisfy the ``exclude_states`` filter.

        :param known_deps: records excluded from traversal and unioned into
            the result
        :param tuple exclude_states: module states pruned during traversal;
            pass ``()`` to disable the state filter
        """
        return self._dependency_closure(
            _UPSTREAM_CLOSURE_QUERY, known_deps, exclude_states
        )

    def _next_todo_action(self) -> dict[str, Any]:
        """Return the pending ir.actions.todo action if any, else redirect to /odoo."""
        Todos = self.env["ir.actions.todo"]
        _logger.info("getting next %s", Todos)
        active_todo = Todos.search([("state", "=", "open")], limit=1)
        if active_todo:
            _logger.info('next action is "%s"', active_todo.name)
            return active_todo.action_launch()
        return {
            "type": "ir.actions.act_url",
            "target": "self",
            "url": "/odoo",
        }

    def _button_immediate_function(
        self, function: Callable[..., Any]
    ) -> dict[str, Any]:
        if not self.env.registry.ready or self.env.registry._init:
            raise UserError(
                _(
                    "Immediate module operations cannot be performed on an init or non-loaded registry. Please use button_install instead."
                )
            )

        if modules.module.current_test:
            msg = (
                "Module operations inside tests are not transactional and thus forbidden.\n"
                "If you really need to perform module operations to test a specific behavior, it "
                "is best to write it as a standalone script, and ask the runbot/metastorm team "
                "for help."
            )
            raise RuntimeError(msg)

        # raise error if database is updating for module operations
        if self.search_count(
            [("state", "in", ("to install", "to upgrade", "to remove"))],
            limit=1,
        ):
            raise UserError(
                _(
                    "Odoo is currently processing another module operation.\n"
                    "Please try again later or contact your system administrator."
                )
            )
        try:
            # raise error if another transaction is trying to schedule module operations concurrently
            self.env.cr.execute("LOCK ir_module_module IN EXCLUSIVE MODE NOWAIT")
        except psycopg.OperationalError:
            raise UserError(
                _(
                    "Odoo is currently processing another module operation.\n"
                    "Please try again later or contact your system administrator."
                )
            ) from None

        try:
            # This is done because the installation/uninstallation/upgrade can modify a currently
            # running cron job and prevent it from finishing, and since the ir_cron table is locked
            # during execution, the lock won't be released until timeout.
            self.env.cr.execute("SELECT FROM ir_cron FOR UPDATE NOWAIT")
        except psycopg.OperationalError:
            raise UserError(
                _(
                    "Odoo is currently processing a scheduled action.\n"
                    "Module operations are not possible at this time, "
                    "please try again later or contact your system administrator."
                )
            ) from None
        function(self)

        self.env.cr.commit()
        registry = modules.registry.Registry.new(self.env.cr.dbname, update_module=True)
        self.env.cr.commit()
        if request and request.registry is self.env.registry:
            request.env.cr.reset()
            request.registry = request.env.registry
            if request.env.registry is not registry:
                raise RuntimeError(
                    "Registry mismatch after module installation: request registry was not refreshed"
                )
        self.env.cr.reset()
        if self.env.registry is not registry:
            raise RuntimeError(
                "Registry mismatch after module installation: env registry was not refreshed"
            )

        next_action = self.env["ir.module.module"]._next_todo_action() or {}
        if next_action.get("type") != "ir.actions.act_window_close":
            return next_action

        # reload the client; open the first available root menu
        menu = self.env["ir.ui.menu"].search([("parent_id", "=", False)])[:1]
        return {
            "type": "ir.actions.client",
            "tag": "reload",
            "params": {"menu_id": menu.id},
        }

    @assert_log_admin_access
    def button_immediate_uninstall(self) -> dict[str, Any]:
        """Uninstall the selected modules immediately; return the next res.config action."""
        _logger.info("User #%d triggered module uninstallation", self.env.uid)
        return self._button_immediate_function(
            self.env.registry[self._name].button_uninstall
        )

    @assert_log_admin_access
    def button_uninstall(self) -> dict[str, Any]:
        un_installable_modules = set(config["server_wide_modules"]) & set(
            self.mapped("name")
        )
        if un_installable_modules:
            raise UserError(
                _(
                    "Those modules cannot be uninstalled: %s",
                    ", ".join(un_installable_modules),
                )
            )
        if any(
            state not in ("installed", "to upgrade") for state in self.mapped("state")
        ):
            raise UserError(
                _(
                    "One or more of the selected modules have already been uninstalled, if you "
                    "believe this to be an error, you may try again later or contact support."
                )
            )
        deps = self.downstream_dependencies()
        (self + deps).write({"state": "to remove"})
        return dict(ACTION_DICT, name=_("Uninstall"))

    @assert_log_admin_access
    def button_uninstall_wizard(self) -> dict[str, Any]:
        """Launch the wizard to uninstall the given module."""
        return {
            "type": "ir.actions.act_window",
            "target": "new",
            "name": _("Uninstall module"),
            "view_mode": "form",
            "res_model": "base.module.uninstall",
            "context": {"default_module_ids": self.ids},
        }

    @assert_log_admin_access
    def button_immediate_upgrade(self) -> dict[str, Any]:
        """Upgrade the selected modules immediately; return the next res.config action."""
        return self._button_immediate_function(
            self.env.registry[self._name].button_upgrade
        )

    @assert_log_admin_access
    def button_upgrade(self) -> dict[str, Any] | None:
        """Mark the modules and their reverse dependencies "to upgrade" and
        schedule the installation of new, not-yet-installed dependencies.

        :return: the upgrade-wizard action, or None when ``self`` is empty
        :rtype: dict[str, Any] | None
        """
        if not self:
            return None
        Dependency = self.env["ir.module.module.dependency"]
        self.update_list()

        todo = list(self)
        # Membership on the growing `todo` recordset is O(V*E) (measured 89ms at
        # 1536 addons); a set of ids keeps each test O(1).
        seen_ids = set(self.ids)
        if "base" in self.mapped("name"):
            # An installed module reachable only through a new, uninstalled
            # dependency isn't selected yet; upgrading 'base' must also upgrade
            # these modules and thereby install the new dependency.
            others = self.search(
                [
                    ("state", "=", "installed"),
                    ("name", "!=", "studio_customization"),
                    ("id", "not in", self.ids),
                ]
            )
            todo.extend(others)
            seen_ids.update(others._ids)
        # Prefetch all dependency rows once; the sweep below would otherwise
        # issue one search per visited module (hundreds on a 'base' upgrade).
        deps_by_name = defaultdict(list)
        for dep in Dependency.search([]):
            deps_by_name[dep.name].append(dep)

        i = 0
        # `todo` grows while iterating: index loop instead of for-each
        while i < len(todo):
            module = todo[i]
            i += 1
            if module.state not in ("installed", "to upgrade"):
                raise UserError(
                    _(
                        "Cannot upgrade module “%s”. It is not installed.",
                        module.name,
                    )
                )
            if self.get_module_info(module.name).get("installable", True):
                self.check_external_dependencies(module.name, "to upgrade")
            for dep in deps_by_name.get(module.name, ()):
                dependent = dep.module_id
                if (
                    dependent.id not in seen_ids
                    and dependent.state == "installed"
                    and dependent.name != "studio_customization"
                ):
                    seen_ids.add(dependent.id)
                    todo.append(dependent)

        # Cascaded modules whose directory content is identical to their last
        # successful upgrade have nothing to re-run: same data files, same
        # schema, same version (so no migrations), same translations.  Leave
        # them installed.  Explicitly requested modules (``self``) always
        # upgrade; modules never stamped (fresh column, NULL) always upgrade.
        # The traversal above is deliberately unfiltered — a changed module
        # reachable only through unchanged intermediates must still be found.
        marked_ids = [m.id for m in todo]
        if config["skip_unchanged_modules"] and column_exists(
            self.env.cr, "ir_module_module", "content_checksum"
        ):
            self.env.cr.execute(
                "SELECT id, content_checksum FROM ir_module_module"
                " WHERE content_checksum IS NOT NULL"
            )
            stamped = dict(self.env.cr.fetchall())
            requested_ids = set(self.ids)
            marked_ids, skipped = [], 0
            for module in todo:
                stored = stamped.get(module.id)
                if (
                    module.id not in requested_ids
                    and stored is not None
                    and module_content_checksum(module.name) == stored
                ):
                    skipped += 1
                else:
                    marked_ids.append(module.id)
            if skipped:
                _logger.info(
                    "upgrade cascade: %d modules to upgrade, %d unchanged "
                    "modules left as installed "
                    "(--upgrade-unchanged-modules to force)",
                    len(marked_ids),
                    skipped,
                )

        self.browse(marked_ids).write({"state": "to upgrade"})

        uninstalled_dep_names = []
        for module in todo:
            if not self.get_module_info(module.name).get("installable", True):
                continue
            for dep in module.dependencies_id:
                if dep.state == "unknown":
                    raise UserError(
                        _(
                            "You try to upgrade the module %(module)s that depends on the module: %(dependency)s.\nBut this module is not available in your system.",
                            module=module.name,
                            dependency=dep.name,
                        )
                    )
                if dep.state == "uninstalled":
                    uninstalled_dep_names.append(dep.name)

        if uninstalled_dep_names:
            self.search([("name", "in", uninstalled_dep_names)]).button_install()
        return dict(ACTION_DICT, name=_("Apply Schedule Upgrade"))

    @staticmethod
    def get_values_from_terp(terp: dict[str, Any] | Manifest) -> dict[str, Any]:
        """Map manifest values to ``ir.module.module`` field values."""
        return {
            "description": dedent(terp.get("description", "")),
            "shortdesc": terp.get("name", ""),
            "author": terp.get("author", "Unknown"),
            "maintainer": terp.get("maintainer", False),
            "contributors": ", ".join(terp.get("contributors", [])) or False,
            "website": terp.get("website", ""),
            "license": terp.get("license", "LGPL-3"),
            "sequence": terp.get("sequence", 100),
            "application": terp.get("application", False),
            "auto_install": terp.get("auto_install", False) is not False,
            "icon": terp.get("icon", False),
            "summary": terp.get("summary", ""),
            "url": terp.get("url") or terp.get("live_test_url", ""),
            "to_buy": False,
        }

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Create the modules with their ``base.module_*`` external ids."""
        modules = super().create(vals_list)
        module_metadata_list = [
            {
                "name": f"module_{module.name}",
                "model": "ir.module.module",
                "module": "base",
                "res_id": module.id,
                "noupdate": True,
            }
            for module in modules
        ]
        self.env["ir.model.data"].create(module_metadata_list)
        # New name->id entries change what _get_id/_installed resolve; like
        # unlink, drop the "stable" cache so a cached negative _get_id result
        # cannot go stale within the current registry.
        self.env.registry.clear_cache("stable")
        return modules

    @assert_log_admin_access
    @api.model
    def update_list(self) -> UpdateListResult:
        """Synchronize the module records with the manifests found on disk.

        :return: counts of modules with a new version and of new modules
        :rtype: UpdateListResult
        """
        # Filesystem may have new addon directories since the last scan; drop the
        # per-process esbuild addon-flag cache so newly discovered addons
        # contribute their --alias on the next bundle.
        from odoo.addons.base.models.assetsbundle import AssetsBundle

        AssetsBundle.invalidate_addon_scan_cache()

        updated = added = 0

        default_version = modules.adapt_version("1.0")
        known_mods = self.with_context(lang=None).search([])
        known_mods_names = {mod.name: mod for mod in known_mods}
        # auto_install requirements per module id, applied in one batched
        # statement after the loop (see _sync_auto_install_required)
        auto_install_requirements: dict[int, Collection[str]] = {}

        # iterate through detected modules and update/create them in db
        for manifest in modules.Manifest.all_addon_manifests():
            mod = known_mods_names.get(manifest.name)
            values = self.get_values_from_terp(manifest)

            if mod:
                updated_values = {}
                for key in values:
                    old = getattr(mod, key)
                    if (old or values[key]) and values[key] != old:
                        updated_values[key] = values[key]
                if manifest.get("installable", True) and mod.state == "uninstallable":
                    updated_values["state"] = "uninstalled"
                if parse_version(
                    manifest.get("version", default_version)
                ) > parse_version(mod.db_version or default_version):
                    updated += 1
                if updated_values:
                    mod.write(updated_values)
            else:
                state = (
                    "uninstalled"
                    if manifest.get("installable", True)
                    else "uninstallable"
                )
                mod = self.create(dict(name=manifest.name, state=state, **values))
                added += 1

            mod._update_from_terp(manifest)
            auto_install_requirements[mod.id] = manifest.get("auto_install") or ()

        self._sync_auto_install_required(auto_install_requirements)

        return UpdateListResult(updated=updated, added=added)

    def _update_from_terp(self, terp: dict[str, Any] | Manifest) -> None:
        """Synchronize the relational data of the module with its manifest.

        ``auto_install_required`` is deliberately not synced here; update_list()
        batches it for the whole scan via :meth:`_sync_auto_install_required`.
        """
        self._update_dependencies(terp.get("depends", []))
        self._update_countries(terp.get("countries", []))
        self._update_exclusions(terp.get("excludes", []))
        self._update_category(terp.get("category", "Uncategorized"))

    def _update_dependencies(self, depends: list[str] | None = None) -> None:
        """Synchronize the dependency rows of the (single) module in ``self``
        with its manifest ``depends`` value."""
        self.env["ir.module.module.dependency"].flush_model()
        existing = {dep.name for dep in self.dependencies_id}
        needed = set(depends or [])
        for dep in needed - existing:
            self.env.cr.execute(
                "INSERT INTO ir_module_module_dependency (module_id, name) values (%s, %s)",
                (self.id, dep),
            )
        for dep in existing - needed:
            self.env.cr.execute(
                "DELETE FROM ir_module_module_dependency WHERE module_id = %s and name = %s",
                (self.id, dep),
            )
        self.invalidate_recordset(["dependencies_id"])

    @api.model
    def _sync_auto_install_required(
        self, requirements: dict[int, Collection[str]]
    ) -> None:
        """Batch-set ``auto_install_required`` on the given modules' dependency
        rows from their manifest ``auto_install`` values.

        One statement for the whole scan; update_list() previously issued one
        UPDATE per module (~1536 per scan here, and button_upgrade calls it on
        every click).

        :param dict requirements: ``{module_id: required dependency names}``
            (an empty collection when the module is not auto-installable)
        """
        if not requirements:
            return
        Dependency = self.env["ir.module.module.dependency"]
        Dependency.flush_model(["auto_install_required"])
        # IS DISTINCT FROM guard: without it every update_list() rewrites every
        # dependency row (pure MVCC/WAL churn, ~3.4k row versions per idle run).
        values = SQL(", ").join(
            SQL("(%s, %s::varchar[])", module_id, list(names or ()))
            for module_id, names in requirements.items()
        )
        self.env.cr.execute(
            SQL(
                """ UPDATE ir_module_module_dependency d
                    SET auto_install_required = (d.name = ANY(v.required))
                    FROM (VALUES %s) AS v(module_id, required)
                    WHERE d.module_id = v.module_id
                      AND d.auto_install_required
                          IS DISTINCT FROM (d.name = ANY(v.required)) """,
                values,
            )
        )
        Dependency.invalidate_model(["auto_install_required"])

    def _update_countries(self, countries: tuple[str, ...] | list[str] = ()) -> None:
        """Synchronize the country rows of the (single) module in ``self``
        with the country codes of its manifest."""
        existing = set(self.country_ids.ids)
        needed = set(
            self.env["res.country"]
            .search([("code", "in", [c.upper() for c in countries])])
            .ids
        )
        for dep in needed - existing:
            self.env.cr.execute(
                "INSERT INTO module_country (module_id, country_id) values (%s, %s)",
                (self.id, dep),
            )
        for dep in existing - needed:
            self.env.cr.execute(
                "DELETE FROM module_country WHERE module_id = %s and country_id = %s",
                (self.id, dep),
            )
        self.invalidate_recordset(["country_ids"])
        self.env["res.company"].invalidate_model(["uninstalled_l10n_module_ids"])

    def _update_exclusions(self, excludes: list[str] | None = None) -> None:
        """Synchronize the exclusion rows of the (single) module in ``self``
        with its manifest ``excludes`` value."""
        self.env["ir.module.module.exclusion"].flush_model()
        existing = {excl.name for excl in self.exclusion_ids}
        needed = set(excludes or [])
        for name in needed - existing:
            self.env.cr.execute(
                "INSERT INTO ir_module_module_exclusion (module_id, name) VALUES (%s, %s)",
                (self.id, name),
            )
        for name in existing - needed:
            self.env.cr.execute(
                "DELETE FROM ir_module_module_exclusion WHERE module_id=%s AND name=%s",
                (self.id, name),
            )
        self.invalidate_recordset(["exclusion_ids"])

    def _update_category(self, category: str = "Uncategorized") -> None:
        """Assign the category from its manifest path, creating it as needed
        and repairing any ancestry loop found on the way."""
        current_category = self.category_id
        seen = set()
        current_category_path = []
        while current_category:
            current_category_path.insert(0, current_category.name)
            seen.add(current_category.id)
            if current_category.parent_id.id in seen:
                current_category.parent_id = False
                _logger.warning(
                    "category %r ancestry loop has been detected and fixed",
                    current_category,
                )
            current_category = current_category.parent_id

        categs = category.split("/")
        if categs != current_category_path:
            cat_id = modules.db.create_categories(self.env.cr, categs)
            self.write({"category_id": cat_id})

    def _update_translations(
        self,
        filter_lang: list[str] | str | None = None,
        overwrite: bool = False,
    ) -> None:
        """Load the PO files of the modules for the given (or installed)
        languages, dependencies first."""
        if not filter_lang:
            langs = self.env["res.lang"].get_installed()
            filter_lang = [code for code, _ in langs]
        elif not isinstance(filter_lang, (list, tuple)):
            filter_lang = [filter_lang]

        update_mods = self.filtered(
            lambda r: r.state in ("installed", "to install", "to upgrade")
        )
        mod_dict = {mod.name: mod.dependencies_id.mapped("name") for mod in update_mods}
        mod_names = topological_sort(mod_dict)
        self.env["ir.module.module"]._load_module_terms(
            mod_names, filter_lang, overwrite
        )

    def _check(self) -> None:
        """Warn about modules shipping an empty description (loading hook)."""
        for module in self:
            if not module.description_html:
                _logger.warning("module %s: description is empty!", module.name)

    def _get(self, name: str) -> Self:
        """Return the sudoed ``ir.module.module`` record with the given name
        (empty recordset if not found).

        Sudo is required because the model is restricted to ``base.group_system``,
        so non-admin callers can read module state. The record carries elevated
        privileges: do not use it to write unless the context is already admin.
        """
        module_id = self._get_id(name) if name else False
        return self.browse(module_id).sudo()

    @tools.ormcache("name", cache="stable")
    def _get_id(self, name: str) -> int | None:
        """Return the id of the named module, or None if not found."""
        self.flush_model(["name"])
        self.env.cr.execute("SELECT id FROM ir_module_module WHERE name=%s", (name,))
        result = self.env.cr.fetchone()
        return result[0] if result else None

    @api.model
    @tools.ormcache(cache="stable")
    def _installed(self) -> dict[str, int]:
        """Return the installed modules as a dict ``{name: id}``."""
        return {
            module.name: module.id
            for module in self.sudo().search([("state", "=", "installed")])
        }

    @api.model
    def search_panel_select_range(
        self, field_name: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Return the Apps search-panel categories, hiding theme/hidden ones."""
        if field_name == "category_id":
            enable_counters = kwargs.get("enable_counters", False)
            domain = Domain(
                [
                    ("parent_id", "=", False),
                    "|",
                    ("module_ids.application", "!=", False),
                    ("child_ids.module_ids", "!=", False),
                ]
            )

            excluded_xmlids = [
                "base.module_category_website_theme",
                "base.module_category_theme",
            ]
            if not self.env.user.has_group("base.group_no_one"):
                excluded_xmlids.append("base.module_category_hidden")

            excluded_category_ids = []
            for excluded_xmlid in excluded_xmlids:
                categ = self.env.ref(excluded_xmlid, False)
                if not categ:
                    continue
                excluded_category_ids.append(categ.id)

            if excluded_category_ids:
                domain &= Domain("id", "not in", excluded_category_ids)

            records = self.env["ir.module.category"].search_read(
                domain, ["display_name"], order="sequence"
            )

            if enable_counters:
                for record in records:
                    model_domain = Domain.AND(
                        [
                            kwargs.get("search_domain", []),
                            kwargs.get("category_domain", []),
                            kwargs.get("filter_domain", []),
                            [
                                ("category_id", "child_of", record["id"]),
                                (
                                    "category_id",
                                    "not in",
                                    excluded_category_ids,
                                ),
                            ],
                        ]
                    )
                    record["__count"] = self.env["ir.module.module"].search_count(  # noqa: E8507 — inherent: child_of per category requires tree traversal
                        model_domain
                    )

            return {
                "parent_field": "parent_id",
                "values": records,
            }

        return super().search_panel_select_range(field_name, **kwargs)

    @api.model
    def _load_module_terms(
        self, module_names: list[str], langs: list[str], overwrite: bool = False
    ) -> None:
        """Load PO files of the given modules for the given languages."""
        # load i18n files
        translation_importer = TranslationImporter(self.env.cr, verbose=False)

        for module_name in module_names:
            if not Manifest.for_addon(module_name, display_warning=False):
                continue
            for lang in langs:
                for po_path in get_po_paths(module_name, lang):
                    _logger.info(
                        "module %s: loading translation file %s for language %s",
                        module_name,
                        po_path,
                        lang,
                    )
                    translation_importer.load_file(po_path, lang)
                for data_path in get_datafile_translation_path(module_name):
                    translation_importer.load_file(data_path, lang, module=module_name)
                if lang != "en_US" and lang not in translation_importer.imported_langs:
                    _logger.info(
                        "module %s: no translation for language %s",
                        module_name,
                        lang,
                    )

        translation_importer.save(overwrite=overwrite)

    @api.model
    def _extract_resource_attachment_translations(self, module: str, lang: str) -> Any:
        """Hook yielding translatable terms of resource attachments (none here)."""
        yield from ()


DEP_STATES = STATES + [("unknown", "Unknown")]


class IrModuleModuleDependency(models.Model):
    _name = "ir.module.module.dependency"
    _description = "Module dependency"
    _log_access = (
        False  # inserts are done manually, create and write uid, dates are always null
    )
    _allow_sudo_commands = False

    name = fields.Char(index=True)

    # the module that depends on it
    module_id = fields.Many2one("ir.module.module", "Module", ondelete="cascade")

    # the module corresponding to the dependency, and its status
    depend_id = fields.Many2one(
        "ir.module.module",
        "Dependency",
        compute="_compute_depend",
        search="_search_depend",
    )
    state = fields.Selection(DEP_STATES, string="Status", compute="_compute_state")

    auto_install_required = fields.Boolean(
        default=True,
        help="Whether this dependency blocks automatic installation of the dependent",
    )

    _module_dependency_uniq = models.Constraint(
        "UNIQUE (module_id, name)",
        "A module cannot declare the same dependency twice!",
    )

    @api.depends("name")
    def _compute_depend(self) -> None:
        """Resolve the dependency name to its module record, if any."""
        names = {dep.name for dep in self}
        mods = self.env["ir.module.module"].search([("name", "in", names)])

        name_mod = {mod.name: mod for mod in mods}
        for dep in self:
            dep.depend_id = name_mod.get(dep.name)

    def _search_depend(
        self, operator: str, value: Any
    ) -> list[tuple[str, str, Any]] | NotImplementedType:
        """Translate a condition on ``depend_id`` into one on the dependency name."""
        if operator == "any" and isinstance(value, Domain | list | tuple):
            # 'any' carries a sub-domain (also from path decomposition, e.g.
            # ('depend_id.name', '=', x)); resolve it to module ids first.
            value = self.env["ir.module.module"].search(Domain(value)).ids
            operator = "in"
        if operator != "in":
            return NotImplemented
        mods = self.env["ir.module.module"].browse(value)
        return [("name", "in", mods.mapped("name"))]

    @api.depends("depend_id.state")
    def _compute_state(self) -> None:
        """Mirror the state of the resolved module, or 'unknown'."""
        for dependency in self:
            dependency.state = dependency.depend_id.state or "unknown"

    @api.model
    def all_dependencies(self, module_names: list[str]) -> dict[str, list[str]]:
        """Map every module reachable from ``module_names`` through the
        dependency graph to the list of its direct dependency names.

        Modules without dependency rows (leaves) do not appear as keys.

        :param list module_names: technical names to start the traversal from
        :rtype: dict[str, list[str]]
        """
        searched: set[str] = set()
        to_search = set(module_names)
        res: dict[str, list[str]] = {}
        while to_search:
            searched |= to_search
            groups = self._read_group(
                [("module_id.name", "in", list(to_search))],
                groupby=["module_id"],
                aggregates=["name:array_agg"],
            )
            to_search.clear()
            for module, dep_names in groups:
                res[module.name] = dep_names
                to_search.update(set(dep_names) - searched)
        return res


class IrModuleModuleExclusion(models.Model):
    _name = "ir.module.module.exclusion"
    _description = "Module exclusion"
    _allow_sudo_commands = False

    name = fields.Char(index=True)

    # the module that excludes it
    module_id = fields.Many2one("ir.module.module", "Module", ondelete="cascade")

    # the module corresponding to the exclusion, and its status
    exclusion_id = fields.Many2one(
        "ir.module.module",
        "Exclusion Module",
        compute="_compute_exclusion",
        search="_search_exclusion",
    )
    state = fields.Selection(DEP_STATES, string="Status", compute="_compute_state")

    _module_exclusion_uniq = models.Constraint(
        "UNIQUE (module_id, name)",
        "A module cannot declare the same exclusion twice!",
    )

    @api.depends("name")
    def _compute_exclusion(self) -> None:
        """Resolve the exclusion name to its module record, if any."""
        names = {excl.name for excl in self}
        mods = self.env["ir.module.module"].search([("name", "in", names)])

        name_mod = {mod.name: mod for mod in mods}
        for excl in self:
            excl.exclusion_id = name_mod.get(excl.name)

    def _search_exclusion(
        self, operator: str, value: Any
    ) -> list[tuple[str, str, Any]] | NotImplementedType:
        """Translate a condition on ``exclusion_id`` into one on the exclusion name."""
        if operator == "any" and isinstance(value, Domain | list | tuple):
            # 'any' carries a sub-domain (also from path decomposition, e.g.
            # ('exclusion_id.name', '=', x)); resolve it to module ids first.
            value = self.env["ir.module.module"].search(Domain(value)).ids
            operator = "in"
        if operator != "in":
            return NotImplemented
        mods = self.env["ir.module.module"].browse(value)
        return [("name", "in", mods.mapped("name"))]

    @api.depends("exclusion_id.state")
    def _compute_state(self) -> None:
        """Mirror the state of the resolved module, or 'unknown'."""
        for exclusion in self:
            exclusion.state = exclusion.exclusion_id.state or "unknown"
