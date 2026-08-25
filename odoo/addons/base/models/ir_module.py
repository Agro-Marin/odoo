import base64
import contextlib
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
from odoo.db.schema import column_exists
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
from odoo.tools.translate import (
    TranslationImporter,
    code_translations,
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
    updated: int
    added: int


def assert_log_admin_access[T](method: T, /) -> T:

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
        if self._has_cycle():
            raise ValidationError(_("Error ! You cannot create recursive categories."))

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        records = super().create(vals_list)
        self.env.registry.clear_cache("groups")
        return records

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        self.env.registry.clear_cache("groups")
        return res

    def unlink(self) -> bool:
        res = super().unlink()
        self.env.registry.clear_cache("groups")
        return res


class MyFilterMessages(Transform):
    default_priority = 870

    def apply(self) -> None:
        for node in self.document.findall(nodes.system_message):
            _logger.debug("docutils' system message present: %s", node)
            node.parent.remove(node)


class MyWriter(Writer):
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
    _is_registry_metadata = True
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
        string="Menus", compute="_compute_records_by_module", store=True
    )
    reports_by_module = fields.Text(
        string="Reports", compute="_compute_records_by_module", store=True
    )
    views_by_module = fields.Text(
        string="Views", compute="_compute_records_by_module", store=True
    )
    application = fields.Boolean("Application", readonly=True)
    icon = fields.Char("Icon URL")
    icon_image = fields.Binary(string="Icon", compute="_compute_icon_display")
    icon_flag = fields.Char(string="Flag", compute="_compute_icon_display")
    to_buy = fields.Boolean("Odoo Enterprise Module", default=False)
    has_iap = fields.Boolean(compute="_compute_has_iap")
    data_file_checksums = fields.Json(readonly=True, prefetch=False)
    content_checksum = fields.Char(readonly=True, prefetch=False)

    _name_uniq = models.Constraint(
        "UNIQUE (name)",
        "The name of the module must be unique!",
    )

    @classmethod
    def get_module_info(cls, name: str) -> dict[str, Any] | Manifest:
        if not name:
            return {}
        return modules.Manifest.for_addon(name, display_warning=False) or {}

    @api.depends("name", "description")
    def _compute_description_html(self) -> None:

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
        default_version = modules.adapt_version("1.0")
        for module in self:
            module.manifest_version = self.get_module_info(module.name).get(
                "version", default_version
            )

    @api.depends("name", "state")
    def _compute_records_by_module(self) -> None:
        IrModelData = self.env["ir.model.data"].with_context(active_test=True)
        dmodels = ["ir.ui.view", "ir.actions.report", "ir.ui.menu"]

        active_mods = self.filtered(
            lambda m: m.state in ("installed", "to upgrade", "to remove")
        )
        for module in self - active_mods:
            module.views_by_module = ""
            module.reports_by_module = ""
            module.menus_by_module = ""
        if not active_mods:
            return

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
    def _compute_icon_display(self) -> None:
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
                with contextlib.suppress(ValueError):
                    module.icon_flag = get_flag(countries[0].upper())

    def _compute_has_iap(self) -> None:
        iap = self.browse(self._get_id("iap") or [])
        iap_dependent_ids = set(iap.downstream_dependencies(exclude_states=())._ids)
        for module in self:
            module.has_iap = bool(module.id) and module.id in iap_dependent_ids

    @api.ondelete(at_uninstall=False)
    def _unlink_except_installed(self) -> None:
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
        self.env.registry.clear_cache("stable")
        return super().unlink()

    def _get_domain_modules_to_load(self) -> list[tuple[str, str, str]]:
        return [("state", "=", "installed")]

    @api.model
    def check_external_dependencies(
        self, module_name: str, newstate: str = "to install"
    ) -> None:
        manifest = modules.Manifest.for_addon(module_name)
        if not manifest:
            return
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

            update_mods._state_update(newstate, states_to_update, level=level - 1)

            if module.state in states_to_update:
                self.check_external_dependencies(module.name, newstate)
                module.write({"state": newstate})

    @assert_log_admin_access
    def button_install(self) -> dict[str, Any]:
        env_no_prefetch = self.env(
            context=dict(self.env.context, prefetch_fields=False)
        )
        company_countries = env_no_prefetch["res.company"].search([]).country_id
        auto_domain = [
            ("state", "=", "uninstalled"),
            ("auto_install", "=", True),
        ]

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
            to_install._state_update("to install", ["uninstalled"])

            if config.get("skip_auto_install"):
                to_install = self.browse()
            else:
                to_install = self.search(auto_domain).filtered(must_install)

        install_mods = self.search([("state", "in", list(install_states))])

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

        exclusives = self.env["ir.module.category"].search([("exclusive", "=", True)])
        for category in exclusives:
            categories = category.search([("id", "child_of", category.ids)])
            category_mods = install_mods.filtered(
                lambda mod, categories=categories: mod.category_id in categories
            )
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
        _logger.info("User #%d triggered module installation", self.env.uid)
        if request:
            request.allowed_company_ids = self.env.companies.ids
        return self._button_immediate_function(
            self.env.registry[self._name].button_install
        )

    @assert_log_admin_access
    @api.model
    def button_reset_state(self) -> bool:
        self.search([("state", "=", "to install")]).state = "uninstalled"
        self.search([("state", "in", ("to upgrade", "to remove"))]).state = "installed"
        return True

    @api.model
    def check_module_update(self) -> bool:
        return bool(
            self.sudo().search_count(
                [("state", "in", ("to install", "to upgrade", "to remove"))],
                limit=1,
            )
        )

    @assert_log_admin_access
    def module_uninstall(self) -> bool:
        modules_to_remove = self.mapped("name")
        self.env["ir.model.data"]._module_data_uninstall(modules_to_remove)
        self.with_context(prefetch_fields=False).write(
            {"state": "uninstalled", "db_version": False}
        )
        return True

    def _remove_copied_views(self) -> None:
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
        return self._dependency_closure(
            _UPSTREAM_CLOSURE_QUERY, known_deps, exclude_states
        )

    def _next_todo_action(self) -> dict[str, Any]:
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

        self.env.cr.execute("SET LOCAL lock_timeout = '3s'")

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
            self.env.cr.execute("LOCK ir_module_module IN EXCLUSIVE MODE")
        except psycopg.OperationalError:
            self.env.cr.rollback()
            raise UserError(
                _(
                    "Odoo is currently processing another module operation.\n"
                    "Please try again later or contact your system administrator."
                )
            ) from None

        try:
            self.env.cr.execute("SELECT FROM ir_cron FOR UPDATE")
        except psycopg.OperationalError:
            self.env.cr.rollback()
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

        menu = self.env["ir.ui.menu"].search([("parent_id", "=", False)])[:1]
        return {
            "type": "ir.actions.client",
            "tag": "reload",
            "params": {"menu_id": menu.id},
        }

    @assert_log_admin_access
    def button_immediate_uninstall(self) -> dict[str, Any]:
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
        return self._button_immediate_function(
            self.env.registry[self._name].button_upgrade
        )

    @assert_log_admin_access
    def button_upgrade(self) -> dict[str, Any] | None:
        if not self:
            return None
        Dependency = self.env["ir.module.module.dependency"]
        self.update_list()

        todo = list(self)
        seen_ids = set(self.ids)
        if "base" in self.mapped("name"):
            others = self.search(
                [
                    ("state", "=", "installed"),
                    ("name", "!=", "studio_customization"),
                    ("id", "not in", self.ids),
                ]
            )
            todo.extend(others)
            seen_ids.update(others._ids)
        deps_by_name = defaultdict(list)
        for dep in Dependency.search([]):
            deps_by_name[dep.name].append(dep)

        i = 0
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
        self.env.registry.clear_cache("stable")
        return modules

    @assert_log_admin_access
    @api.model
    def update_list(self) -> UpdateListResult:
        from odoo.addons.base.models.assetsbundle import AssetsBundle

        AssetsBundle.invalidate_addon_scan_cache()

        updated = added = 0

        default_version = modules.adapt_version("1.0")
        known_mods = self.with_context(lang=None).search([])
        known_mods_names = {mod.name: mod for mod in known_mods}
        auto_install_requirements: dict[int, Collection[str]] = {}
        category_cache: dict[str, int] = {}

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

            mod._update_from_terp(manifest, category_cache)
            auto_install_requirements[mod.id] = manifest.get("auto_install") or ()

        self._sync_auto_install_required(auto_install_requirements)

        return UpdateListResult(updated=updated, added=added)

    def _update_from_terp(
        self,
        terp: dict[str, Any] | Manifest,
        category_cache: dict[str, int] | None = None,
    ) -> None:
        self._update_dependencies(terp.get("depends", []))
        self._update_countries(terp.get("countries", []))
        self._update_exclusions(terp.get("excludes", []))
        self._update_category(terp.get("category", "Uncategorized"), category_cache)

    def _sync_link_rows(
        self,
        table: str,
        column: str,
        existing: set,
        needed: set,
        cast: SQL,
    ) -> bool:
        """Bring `table`'s rows for this module in line with `needed`.

        The three manifest-fed link tables differ only in what they key on, so
        they share this. One statement per direction rather than one per row:
        a first `update_list` over this workspace inserts ~3.5k dependency
        rows, which was ~3.5k round trips.

        Returns whether any row moved, so a caller can skip an invalidation
        that has nothing to invalidate.
        """
        # These statements name `self.id`; an empty recordset would spell it
        # `False` and insert rows under a NULL `module_id`, which the column
        # accepts and nothing ever collects.
        self.ensure_one()
        cr = self.env.cr
        # Sorted, so the rows land in a reproducible order. Inserting one row
        # per set element left it at the mercy of per-process string hashing:
        # the same manifest produced a different `dependencies_id` order in
        # every process, and the model declares no `_order`, so `id` decides.
        if to_add := sorted(needed - existing):
            cr.execute(
                SQL(
                    "INSERT INTO %s (module_id, %s) SELECT %s, unnest(%s::%s)",
                    SQL.identifier(table),
                    SQL.identifier(column),
                    self.id,
                    to_add,
                    cast,
                )
            )
        if to_remove := sorted(existing - needed):
            cr.execute(
                SQL(
                    "DELETE FROM %s WHERE module_id = %s AND %s = ANY(%s)",
                    SQL.identifier(table),
                    self.id,
                    SQL.identifier(column),
                    to_remove,
                )
            )
        return bool(to_add or to_remove)

    def _update_dependencies(self, depends: list[str] | None = None) -> None:
        self.env["ir.module.module.dependency"].flush_model()
        if self._sync_link_rows(
            "ir_module_module_dependency",
            "name",
            {dep.name for dep in self.dependencies_id},
            set(depends or []),
            SQL("varchar[]"),
        ):
            self.invalidate_recordset(["dependencies_id"])

    @api.model
    def _sync_auto_install_required(
        self, requirements: dict[int, Collection[str]]
    ) -> None:
        if not requirements:
            return
        Dependency = self.env["ir.module.module.dependency"]
        Dependency.flush_model(["auto_install_required"])
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
        existing = set(self.country_ids.ids)
        id_by_code = self.env["res.country"]._id_by_code()
        needed = {
            country_id
            for code in countries
            if (country_id := id_by_code.get(code.upper()))
        }
        if self._sync_link_rows(
            "module_country", "country_id", existing, needed, SQL("integer[]")
        ):
            self.invalidate_recordset(["country_ids"])
            # Model-wide, so it was flushing every company's cache once per
            # module scanned -- 1556 times for the 239 that carry a country.
            self.env["res.company"].invalidate_model(["uninstalled_l10n_module_ids"])

    def _update_exclusions(self, excludes: list[str] | None = None) -> None:
        self.env["ir.module.module.exclusion"].flush_model()
        if self._sync_link_rows(
            "ir_module_module_exclusion",
            "name",
            {excl.name for excl in self.exclusion_ids},
            set(excludes or []),
            SQL("varchar[]"),
        ):
            self.invalidate_recordset(["exclusion_ids"])

    def _update_category(
        self,
        category: str = "Uncategorized",
        category_cache: dict[str, int] | None = None,
    ) -> None:
        current_category = self.category_id
        seen = set()
        while current_category:
            seen.add(current_category.id)
            if current_category.parent_id.id in seen:
                current_category.parent_id = False
                _logger.warning(
                    "category %r ancestry loop has been detected and fixed",
                    current_category,
                )
            current_category = current_category.parent_id

        # Compare the resolved category, not the manifest path against the
        # stored display names: `create_categories` keys a category by an xml_id
        # derived from the path, and base data is free to give that record any
        # name it likes -- `Accounting/Accounting` is stored as `Invoicing`. A
        # name comparison therefore never matches for such a category, and
        # rewrote `category_id` to the value it already held on every call. It
        # was language-dependent too, `name` being translated.
        cat_id = modules.db.create_categories(
            self.env.cr, category.split("/"), category_cache
        )
        if cat_id != self.category_id.id:
            self.write({"category_id": cat_id})

    def _update_translations(
        self,
        filter_lang: list[str] | str | None = None,
        overwrite: bool = False,
    ) -> None:
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
        for module in self:
            if not module.description_html:
                _logger.warning("module %s: description is empty!", module.name)

    def _get(self, name: str) -> Self:
        module_id = self._get_id(name) if name else False
        return self.browse(module_id).sudo()

    @tools.ormcache("name", cache="stable")
    def _get_id(self, name: str) -> int | None:
        self.flush_model(["name"])
        self.env.cr.execute("SELECT id FROM ir_module_module WHERE name=%s", (name,))
        result = self.env.cr.fetchone()
        return result[0] if result else None

    @api.model
    @tools.ormcache(cache="stable")
    def _installed(self) -> dict[str, int]:
        return {
            module.name: module.id
            for module in self.sudo().search([("state", "=", "installed")])
        }

    @api.model
    def search_panel_select_range(
        self, field_name: str, **kwargs: Any
    ) -> dict[str, Any]:
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
                    record["__count"] = self.env["ir.module.module"].search_count(
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
        translation_importer = TranslationImporter(self.env.cr, verbose=False)

        for module_name in module_names:
            if not Manifest.for_addon(module_name, display_warning=False):
                continue
            code_translations.clear(module_name)
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
        yield from ()


DEP_STATES = STATES + [("unknown", "Unknown")]


class IrModuleModuleDependency(models.Model):
    _name = "ir.module.module.dependency"
    _description = "Module dependency"
    _log_access = False
    _allow_sudo_commands = False

    name = fields.Char(index=True)

    module_id = fields.Many2one("ir.module.module", "Module", ondelete="cascade")

    depend_id = fields.Many2one(
        "ir.module.module",
        "Dependency",
        compute="_compute_depend_id",
        search="_search_depend_id",
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
    def _compute_depend_id(self) -> None:
        names = {dep.name for dep in self}
        mods = self.env["ir.module.module"].search([("name", "in", names)])

        name_mod = {mod.name: mod for mod in mods}
        for dep in self:
            dep.depend_id = name_mod.get(dep.name)

    def _search_depend_id(
        self, operator: str, value: Any
    ) -> list[tuple[str, str, Any]] | NotImplementedType:
        if operator == "any" and isinstance(value, Domain | list | tuple):
            value = self.env["ir.module.module"].search(Domain(value)).ids
            operator = "in"
        if operator != "in":
            return NotImplemented
        mods = self.env["ir.module.module"].browse(value)
        return [("name", "in", mods.mapped("name"))]

    @api.depends("depend_id.state")
    def _compute_state(self) -> None:
        for dependency in self:
            dependency.state = dependency.depend_id.state or "unknown"

    @api.model
    def all_dependencies(self, module_names: list[str]) -> dict[str, list[str]]:
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

    module_id = fields.Many2one("ir.module.module", "Module", ondelete="cascade")

    exclusion_id = fields.Many2one(
        "ir.module.module",
        "Exclusion Module",
        compute="_compute_exclusion_id",
        search="_search_exclusion_id",
    )
    state = fields.Selection(DEP_STATES, string="Status", compute="_compute_state")

    _module_exclusion_uniq = models.Constraint(
        "UNIQUE (module_id, name)",
        "A module cannot declare the same exclusion twice!",
    )

    @api.depends("name")
    def _compute_exclusion_id(self) -> None:
        names = {excl.name for excl in self}
        mods = self.env["ir.module.module"].search([("name", "in", names)])

        name_mod = {mod.name: mod for mod in mods}
        for excl in self:
            excl.exclusion_id = name_mod.get(excl.name)

    def _search_exclusion_id(
        self, operator: str, value: Any
    ) -> list[tuple[str, str, Any]] | NotImplementedType:
        if operator == "any" and isinstance(value, Domain | list | tuple):
            value = self.env["ir.module.module"].search(Domain(value)).ids
            operator = "in"
        if operator != "in":
            return NotImplemented
        mods = self.env["ir.module.module"].browse(value)
        return [("name", "in", mods.mapped("name"))]

    @api.depends("exclusion_id.state")
    def _compute_state(self) -> None:
        for exclusion in self:
            exclusion.state = exclusion.exclusion_id.state or "unknown"
