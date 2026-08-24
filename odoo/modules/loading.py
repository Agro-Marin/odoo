import datetime
import gc
import itertools
import json
import logging
import sys
import time
import traceback
import typing

import odoo.db
from odoo import api, tools
from odoo.api import Environment
from odoo.db import schema
from odoo.libs.hashing import cache_hash
from odoo.tools import OrderedSet
from odoo.tools.convert import ConvertMode as LoadMode
from odoo.tools.convert import IdRef, convert_file

from . import db as modules_db
from .migration import MigrationManager
from .module import (
    adapt_version,
    initialize_sys_path,
    load_odoo_module,
    module_content_checksum,
)
from .module_graph import ModuleGraph
from .registry import Registry

LoadKind = typing.Literal["data", "demo"]

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from odoo.db import BaseCursor
    from odoo.tests.result import OdooTestResult

    from .module_graph import ModuleNode

_logger = logging.getLogger(__name__)

_GC_YOUNG_BACKLOG_LIMIT = 100_000
_GC_FULL_CYCLE_EVERY = 16


_DATA_FILE_CHECKSUM_VERSION = 2

_DYNAMIC_XML_MARKERS = (b"<function", b"<delete")


def _scan_data_file(filename: str, content: bytes) -> tuple[str, bool]:
    digest = cache_hash(content)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    dynamic = ext == "sql" or (
        ext == "xml" and any(marker in content for marker in _DYNAMIC_XML_MARKERS)
    )
    return digest, dynamic


def load_data(
    env: Environment,
    idref: IdRef,
    mode: LoadMode,
    kind: LoadKind,
    package: ModuleNode,
) -> None:
    keys = ("init_xml", "data") if kind == "data" else ("demo", "demo_xml")

    registry = env.registry
    track = (
        kind == "data"
        and mode == "update"
        and tools.config["skip_unchanged_data_files"]
        and schema.column_exists(env.cr, "ir_module_module", "data_file_checksums")
    )
    stored_files: dict = {}
    new_files: dict = {}
    if track:
        env.cr.execute(
            "SELECT data_file_checksums FROM ir_module_module WHERE id = %s",
            [package.id],
        )
        row = env.cr.fetchone()
        stored = row[0] if row else None
        if isinstance(stored, dict) and stored.get("v") == _DATA_FILE_CHECKSUM_VERSION:
            stored_files = stored.get("files") or {}

    files: set[str] = set()
    for k in keys:
        if k == "init_xml" and package.manifest[k]:
            _logger.warning(
                "module %s: key 'init_xml' is deprecated in Odoo 19.",
                package.name,
            )
        if k == "demo_xml" and package.manifest[k]:
            _logger.warning(
                "module %s: key 'demo_xml' is deprecated in Odoo 19, use 'demo'.",
                package.name,
            )
        for filename in package.manifest[k]:
            if filename in files:
                _logger.warning(
                    "File %s is imported twice in module %s %s",
                    filename,
                    package.name,
                    kind,
                )
            files.add(filename)

            if not track:
                _logger.info("loading %s/%s", package.name, filename)
                convert_file(
                    env,
                    package.name,
                    filename,
                    idref,
                    mode,
                    noupdate=kind == "demo",
                )
                continue

            with tools.file_open(f"{package.name}/{filename}", "rb", env=env) as fp:
                content = fp.read()
            digest, dynamic = _scan_data_file(filename, content)
            entry = stored_files.get(filename)
            if (
                not dynamic
                and isinstance(entry, dict)
                and entry.get("sha") == digest
                and not entry.get("dyn")
                and isinstance(entry.get("xmlids"), list)
            ):
                registry.loaded_xmlids.update(entry["xmlids"])
                new_files[filename] = entry
                _logger.info("skipping unchanged %s/%s", package.name, filename)
                continue

            _logger.info("loading %s/%s", package.name, filename)
            recorder: set[str] = set()
            previous_recorder = getattr(registry, "_xmlid_recorder", None)
            registry._xmlid_recorder = recorder
            try:
                convert_file(
                    env,
                    package.name,
                    filename,
                    idref,
                    mode,
                    noupdate=kind == "demo",
                )
            finally:
                registry._xmlid_recorder = previous_recorder
            new_files[filename] = {
                "sha": digest,
                "xmlids": sorted(recorder),
                "dyn": dynamic,
            }

    if track:
        env.cr.execute(
            "UPDATE ir_module_module SET data_file_checksums = %s::jsonb WHERE id = %s",
            [
                json.dumps({"v": _DATA_FILE_CHECKSUM_VERSION, "files": new_files}),
                package.id,
            ],
        )
        env["ir.module.module"].invalidate_model(["data_file_checksums"])


def load_demo(
    env: Environment, package: ModuleNode, idref: IdRef, mode: LoadMode
) -> bool:

    try:
        if package.manifest.get("demo") or package.manifest.get("demo_xml"):
            _logger.info("Module %s: loading demo", package.name)
            with env.cr.savepoint(flush=False):
                load_data(env(su=True), idref, mode, kind="demo", package=package)
        return True
    except Exception:
        _logger.warning(
            "Module %s demo data failed to install, installed without demo data",
            package.name,
            exc_info=True,
        )

        todo = env.ref("base.demo_failure_todo", raise_if_not_found=False)
        Failure = env.get("ir.demo_failure")
        if todo and Failure is not None:
            todo.state = "open"
            Failure.create({"module_id": package.id, "error": traceback.format_exc()})
        return False


def force_demo(env: Environment) -> None:
    """Load demo data into every loaded module, and record which ones took it.

    `demo` says the module *has* demo data loaded, so it is written from what
    `load_demo` reports, exactly as `load_module_graph` does. Setting the whole
    column true up front and discarding the return value recorded a module whose
    demo XML had just raised as carrying demo data -- and set the flag on every
    uninstalled and uninstallable module in the table as well, 654 of 671 rows on
    a fresh database, none of which is ever a candidate for it.
    """
    env.cr.execute(
        "SELECT name FROM ir_module_module WHERE state IN ('installed', 'to upgrade', 'to remove')"
    )
    module_list = [name for (name,) in env.cr.fetchall()]
    graph = ModuleGraph(env.cr, mode="load")
    graph.extend(module_list)

    loaded = [package.name for package in graph if load_demo(env, package, {}, "init")]

    env.cr.execute(
        "UPDATE ir_module_module SET demo = (name = ANY(%s)) WHERE name = ANY(%s)",
        [loaded, module_list],
    )
    env["ir.module.module"].invalidate_model(["demo"])


def _warn_models_without_access_rules(
    env: Environment,
    module_name: str,
    model_names: Collection[str],
    registry: Registry,
) -> None:
    concrete_models = [model for model in model_names if not registry[model]._abstract]
    if not concrete_models:
        return
    env.cr.execute(
        """
        SELECT m.model FROM ir_model m
        WHERE NOT EXISTS (
            SELECT 1 FROM ir_model_access a WHERE a.model_id = m.id
        ) AND m.model = ANY(%s)
    """,
        [list(concrete_models)],
    )
    models = [model for [model] in env.cr.fetchall()]
    if not models:
        return
    lines = [
        f"The models {models} have no access rules in module {module_name}, consider adding some, like:",
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink",
    ]
    for model in models:
        xmlid = model.replace(".", "_")
        lines.append(
            f"{module_name}.access_{xmlid},access_{xmlid},{module_name}.model_{xmlid},base.group_user,1,0,0,0"
        )
    _logger.warning("\n".join(lines))


UpdateOperation = typing.Literal["install", "upgrade", "reinit"]


class _PackageLoader:
    """One module's pass through the graph, one method per step.

    The steps are the same ones the loop body always had; naming them is what
    lets `load_module_graph` read as a schedule instead of as thirty-eight
    branches over `update_operation`. Each method decides for itself whether it
    applies, the way `_ModuleLoader`'s phases do -- which is why the caller
    below is a flat list of calls with no flag threaded through it.

    Order is the contract here, not decomposition: `tests/loading/
    test_load_modules_phases.py` traces it, and several steps depend on an
    earlier one having run. The pre-migration must see the old schema; the
    python module must be imported before `pre_init_hook` can be reached on it;
    `_init_modules` must be marked before the post-init hook, because a hook
    that touches the registry would otherwise re-enter this module.
    """

    __slots__ = (
        "cursor_queries_at_start",
        "env",
        "extra_queries_at_start",
        "index",
        "install_demo",
        "log_level",
        "migrations",
        "model_names",
        "models_to_check",
        "models_updated",
        "module",
        "module_count",
        "operation",
        "package",
        "py_module",
        "registry",
        "report",
        "run_tests",
        "started_at",
        "test_queries",
        "test_results",
        "test_time",
        "update_module",
    )

    def __init__(
        self,
        env: Environment,
        package: ModuleNode,
        *,
        index: int,
        module_count: int,
        migrations: MigrationManager,
        update_module: bool,
        install_demo: bool,
        run_tests: bool,
        report: OdooTestResult | None,
        models_to_check: OrderedSet[str],
        models_updated: set[str],
    ) -> None:
        self.env = env
        self.registry = env.registry
        self.package = package
        self.index = index
        self.module_count = module_count
        self.migrations = migrations
        self.update_module = update_module
        self.install_demo = install_demo
        self.run_tests = run_tests
        self.report = report
        self.models_to_check = models_to_check
        self.models_updated = models_updated

        self.started_at = time.time()
        self.cursor_queries_at_start = env.cr.sql_log_count
        self.extra_queries_at_start = odoo.db.sql_counter

        self.operation: UpdateOperation | None = None
        self.log_level = logging.DEBUG
        self.model_names: OrderedSet[str] = OrderedSet()
        self.module = None
        self.py_module = None
        self.test_time = 0.0
        self.test_queries = 0
        self.test_results = None

    @property
    def name(self) -> str:
        return self.package.name

    def resolve_operation(self) -> None:
        package = self.package
        if not self.update_module:
            self.operation = None
        elif package.state == "to install":
            self.operation = "install"
        elif package.state == "to upgrade":
            self.operation = "upgrade"
        elif package.name in self.registry._reinit_modules:
            self.operation = "reinit"
        else:
            self.operation = None
        if self.operation:
            self.log_level = logging.INFO

    def announce(self) -> None:
        _logger.log(
            self.log_level,
            "Loading module %s (%d/%d)",
            self.name,
            self.index,
            self.module_count,
        )

    def run_pre_migration(self) -> None:
        if not self.operation:
            return
        if self.operation == "upgrade":
            if self.name != "base":
                self.registry._setup_models__(self.env.cr, [], skip_if_clean=True)
            self.migrations.migrate_module(self.package, "pre")
        if self.name != "base":
            self.env.flush_all()

    def import_python_module(self) -> None:
        load_odoo_module(self.name)
        self.py_module = sys.modules[f"odoo.addons.{self.name}"]

    def run_pre_init_hook(self) -> None:
        if self.operation != "install":
            return
        if pre_init := self.package.manifest.get("pre_init_hook"):
            self.registry._setup_models__(self.env.cr, [], skip_if_clean=True)
            getattr(self.py_module, pre_init)(self.env)

    def load_models(self) -> None:
        registry, package = self.registry, self.package
        model_names = registry.load(package)

        if self.operation:
            model_names = registry.descendants(model_names, "_inherit", "_inherits")
            self.models_updated |= model_names
            self.models_to_check -= model_names
            registry._setup_models__(self.env.cr, [], skip_if_clean=True)
            registry.init_models(
                self.env.cr,
                model_names,
                {"module": package.name},
                self.operation == "install",
            )
        elif self.update_module and package.state != "to remove":
            model_names = registry.descendants(model_names, "_inherit", "_inherits")
            self.models_to_check |= model_names & self.models_updated
        elif self.update_module and package.state == "to remove":
            self.models_to_check |= model_names

        self.model_names = model_names

    def load_data_and_demo(self) -> None:
        if not self.operation:
            return
        env, package = self.env, self.package
        self.module = env["ir.module.module"].browse(package.id)
        self.module._check()

        idref: dict = {}
        if self.operation == "install":
            load_data(env, idref, "init", kind="data", package=package)
            if self.install_demo and package.demo_installable:
                package.demo = load_demo(env, package, idref, "init")
        else:
            self.module.write(self.module.get_values_from_terp(package.manifest))
            mode = "update" if self.operation == "upgrade" else "init"
            load_data(env, idref, mode, kind="data", package=package)
            if package.demo:
                package.demo = load_demo(env, package, idref, mode)
        env.cr.execute(
            "UPDATE ir_module_module SET demo = %s WHERE id = %s",
            (package.demo, package.id),
        )
        self.module.invalidate_model(["demo"])

    def run_post_migration(self) -> None:
        if not self.operation:
            return
        self.migrations.migrate_module(self.package, "post")
        overwrite = tools.config["overwrite_existing_translations"]
        self.module._update_translations(overwrite=overwrite)

    def mark_loaded(self) -> None:
        self.registry._init_modules.add(self.name)

    def run_post_init_hook(self) -> None:
        if self.operation == "install":
            if post_init := self.package.manifest.get("post_init_hook"):
                getattr(self.py_module, post_init)(self.env)
        elif self.operation == "upgrade":
            self.env["ir.ui.view"]._check_module_views(self.name)

    def stamp_installed(self) -> None:
        if not self.operation:
            return
        env, registry = self.env, self.registry
        _warn_models_without_access_rules(env, self.name, self.model_names, registry)
        registry.updated_modules.append(self.name)

        values = {
            "state": "installed",
            "db_version": adapt_version(self.package.manifest["version"]),
        }
        if schema.column_exists(env.cr, "ir_module_module", "content_checksum"):
            values["content_checksum"] = module_content_checksum(self.name)
        self.module.write(values)

        self.package.state = "installed"
        env.flush_all()
        env.cr.commit()

    def run_at_install_tests(self) -> None:
        update_from_config = (
            tools.config["update"] or tools.config["init"] or tools.config["reinit"]
        )
        if not (
            self.run_tests
            and tools.config["test_enable"]
            and (self.operation or not update_from_config)
        ):
            return

        from odoo.tests import loader

        suite = loader.make_suite([self.name], "at_install")
        if not suite.countTestCases():
            return
        if not self.operation:
            self.registry._setup_models__(self.env.cr, [], skip_if_clean=True)
        self.registry.check_null_constraints(self.env.cr)
        tests_t0, tests_q0 = time.time(), odoo.db.sql_counter
        self.test_results = loader.run_suite(suite, global_report=self.report)
        assert self.report is not None, "Missing report during tests"
        self.report.update(self.test_results)
        self.test_time = time.time() - tests_t0
        self.test_queries = odoo.db.sql_counter - tests_q0

    def report_cost(self) -> None:
        extra_queries = (
            odoo.db.sql_counter - self.extra_queries_at_start - self.test_queries
        )
        extras = []
        if self.test_queries:
            extras.append(f"+{self.test_queries} test")
        if extra_queries:
            extras.append(f"+{extra_queries} other")
        _logger.log(
            self.log_level,
            "Module %s loaded in %.2fs%s, %s queries%s",
            self.name,
            time.time() - self.started_at,
            f" (incl. {self.test_time:.2f}s test)" if self.test_time else "",
            self.env.cr.sql_log_count - self.cursor_queries_at_start,
            f" ({', '.join(extras)})" if extras else "",
        )
        results = self.test_results
        if results and not results.wasSuccessful():
            _logger.error(
                "Module %s: %d failures, %d errors of %d tests",
                self.name,
                results.failures_count,
                results.errors_count,
                results.testsRun,
            )

    def run(self) -> None:
        self.resolve_operation()
        self.announce()
        self.run_pre_migration()
        self.import_python_module()
        self.run_pre_init_hook()
        self.load_models()
        self.load_data_and_demo()
        self.run_post_migration()
        self.mark_loaded()
        self.run_post_init_hook()
        self.stamp_installed()
        self.run_at_install_tests()
        self.report_cost()


def _sweep_gc(registry: Registry, sweeps: int) -> int:
    """Drop caches and collect when the young generation has run away.

    Loading a full addons tree allocates far more than it retains, and the
    default generational thresholds do not keep up. `gc.freeze()` moves what
    survived out of the way so later sweeps do not rescan it; a full collection
    every sixteenth sweep is what stops the frozen set growing without bound.
    """
    if gc.get_count()[0] <= _GC_YOUNG_BACKLOG_LIMIT:
        return sweeps
    registry._caches.clear_all()
    sweeps += 1
    if sweeps % _GC_FULL_CYCLE_EVERY == 0:
        gc.unfreeze()
        gc.collect()
    else:
        gc.collect(generation=1)
    gc.freeze()
    return sweeps


def load_module_graph(
    env: Environment,
    graph: ModuleGraph,
    update_module: bool = False,
    report: OdooTestResult | None = None,
    models_to_check: OrderedSet[str] | None = None,
    install_demo: bool = True,
    run_tests: bool = True,
) -> None:
    if models_to_check is None:
        models_to_check = OrderedSet()

    registry = env.registry
    assert isinstance(env.cr, odoo.db.Cursor), "Need for a real Cursor to load modules"
    migrations = MigrationManager(env.cr, graph)
    module_count = len(graph)
    _logger.info("loading %d modules...", module_count)

    t0 = time.time()
    extra_queries_at_start = odoo.db.sql_counter
    cursor_queries_at_start = env.cr.sql_log_count

    models_updated: set[str] = set()
    gc_sweeps = 0

    try:
        for index, package in enumerate(graph, 1):
            if package.name in registry._init_modules:
                continue
            _PackageLoader(
                env,
                package,
                index=index,
                module_count=module_count,
                migrations=migrations,
                update_module=update_module,
                install_demo=install_demo,
                run_tests=run_tests,
                report=report,
                models_to_check=models_to_check,
                models_updated=models_updated,
            ).run()
            env.invalidate_all()
            gc_sweeps = _sweep_gc(registry, gc_sweeps)
    finally:
        gc.unfreeze()

    _logger.runbot(
        "%s modules loaded in %.2fs, %s queries (+%s extra)",
        len(graph),
        time.time() - t0,
        env.cr.sql_log_count - cursor_queries_at_start,
        odoo.db.sql_counter - extra_queries_at_start,
    )


def _check_module_names(cr: BaseCursor, module_names: Iterable[str]) -> None:
    mod_names = set(module_names)
    mod_names.discard("all")
    if mod_names:
        cr.execute(
            "SELECT count(id) AS count FROM ir_module_module WHERE name = ANY(%s)",
            (list(mod_names),),
        )
        row = cr.fetchone()
        assert row is not None
        if row[0] != len(mod_names):
            cr.execute("SELECT name FROM ir_module_module")
            incorrect_names = mod_names.difference(name for [name] in cr.fetchall())
            _logger.warning(
                "invalid module names, ignored: %s", ", ".join(incorrect_names)
            )


class _UninstallRequiresReload(Exception):
    pass


class _ModuleLoader:
    __slots__ = (
        "cr",
        "env",
        "graph",
        "install_modules",
        "models_to_check",
        "new_db_demo",
        "registry",
        "reinit_modules",
        "report",
        "run_tests",
        "update_module",
        "upgrade_modules",
    )

    def __init__(
        self,
        registry: Registry,
        cr: BaseCursor,
        *,
        update_module: bool,
        upgrade_modules: Collection[str],
        install_modules: Collection[str],
        reinit_modules: Collection[str],
        new_db_demo: bool,
        models_to_check: OrderedSet[str],
        run_tests: bool = True,
    ) -> None:
        self.registry = registry
        self.cr = cr
        self.run_tests = run_tests
        self.update_module = update_module
        self.upgrade_modules = upgrade_modules
        self.install_modules = install_modules
        self.reinit_modules = reinit_modules
        self.new_db_demo = new_db_demo
        self.models_to_check = models_to_check
        self.graph: ModuleGraph = None  # type: ignore[assignment]
        self.env = None  # type: ignore[assignment]
        self.report = None

    def bootstrap(self) -> bool:
        cr = self.cr
        cr.execute("SET SESSION lock_timeout = '15s'")
        if not modules_db.is_initialized(cr):
            if not self.update_module:
                _logger.info(
                    "Database %s not initialized, skipping (use `-i base` to bootstrap).",
                    cr.dbname,
                )
                return False
            _logger.info("Initializing database %s", cr.dbname)
            modules_db.initialize(cr)
        elif "base" in self.reinit_modules:
            self.registry._reinit_modules.add("base")

        if "base" in self.upgrade_modules:
            cr.execute(
                "update ir_module_module set state=%s where name=%s and state=%s",
                ("to upgrade", "base", "installed"),
            )

        self.graph = ModuleGraph(cr, mode="update" if self.update_module else "load")
        self.graph.extend(["base"])
        if not self.graph:
            _logger.critical("module base cannot be loaded! (hint: verify addons-path)")
            msg = "Module `base` cannot be loaded! (hint: verify addons-path)"
            raise ImportError(msg)
        return True

    def run_pre_upgrade_scripts(self) -> None:
        if not (self.update_module and self.upgrade_modules):
            return
        for pyfile in tools.config["pre_upgrade_scripts"]:
            odoo.modules.migration.exec_script(
                self.cr, self.graph["base"].db_version, pyfile, "base", "pre"
            )

    def capture_database_field_metadata(self) -> None:
        if not (self.update_module and schema.table_exists(self.cr, "ir_model_fields")):
            return
        cr = self.cr
        cr.execute(
            "SELECT model || '.' || name, translate FROM ir_model_fields WHERE translate IS NOT NULL"
        )
        self.registry._database_translated_fields = dict(cr.fetchall())

        if schema.column_exists(cr, "ir_model_fields", "company_dependent"):
            cr.execute(
                "SELECT model || '.' || name FROM ir_model_fields WHERE company_dependent IS TRUE"
            )
            self.registry._database_company_dependent_fields = {
                row[0] for row in cr.fetchall()
            }

    def open_environment_and_load_base(self) -> None:
        self.report = self.registry._assertion_report
        self.env = api.Environment(self.cr, api.SUPERUSER_ID, {})
        load_module_graph(
            self.env,
            self.graph,
            update_module=self.update_module,
            report=self.report,
            models_to_check=self.models_to_check,
            install_demo=self.new_db_demo,
            run_tests=self.run_tests,
        )

    def load_languages(self) -> None:
        load_lang = tools.config.get("load_language")
        lang_pending = bool(load_lang) and not getattr(
            self.registry, "_load_language_done", False
        )
        if lang_pending or self.update_module:
            self.registry._setup_models__(self.cr, [], skip_if_clean=True)

        if lang_pending:
            for lang in load_lang.split(","):
                tools.translate.load_language(self.cr, lang)
            self.registry._load_language_done = True

    def process_module_requests(self) -> None:
        if not self.update_module:
            return
        env = self.env
        cr = self.cr
        Module = env["ir.module.module"]
        _logger.info("updating modules list")
        Module.update_list()

        _check_module_names(
            cr, itertools.chain(self.install_modules, self.upgrade_modules)
        )

        if self.install_modules:
            modules = Module.search(
                [
                    ("state", "=", "uninstalled"),
                    ("name", "in", tuple(self.install_modules)),
                ]
            )
            if modules:
                modules.button_install()

        if self.upgrade_modules:
            modules = Module.search(
                [
                    ("state", "in", ("installed", "to upgrade")),
                    ("name", "in", tuple(self.upgrade_modules)),
                ]
            )
            if modules:
                modules.button_upgrade()

        if self.reinit_modules:
            modules = Module.search(
                [
                    ("state", "in", ("installed", "to upgrade")),
                    ("name", "in", tuple(self.reinit_modules)),
                ]
            )
            reinit_records = (
                modules.downstream_dependencies(
                    exclude_states=(
                        "uninstalled",
                        "uninstallable",
                        "to remove",
                        "to install",
                    )
                )
                + modules
            )
            self.registry._reinit_modules.update(
                m
                for m in reinit_records.mapped("name")
                if m not in self.graph._imported_modules
            )

        env.flush_all()
        cr.execute(
            "update ir_module_module set state=%s where name=%s",
            ("installed", "base"),
        )
        Module.invalidate_model(["state"])

    def converge_module_graph(self) -> None:
        env = self.env
        while True:
            if self.update_module:
                states = ("installed", "to upgrade", "to remove", "to install")
            else:
                states = ("installed", "to upgrade", "to remove")
            env.cr.execute(
                "SELECT name from ir_module_module WHERE state = ANY(%s)",
                [list(states)],
            )
            module_list = [
                name for (name,) in env.cr.fetchall() if name not in self.graph
            ]
            if not module_list:
                break
            self.graph.extend(module_list)
            _logger.debug("Updating graph with %d more modules", len(module_list))
            updated_modules_count = len(self.registry.updated_modules)
            load_module_graph(
                env,
                self.graph,
                update_module=self.update_module,
                report=self.report,
                models_to_check=self.models_to_check,
                run_tests=self.run_tests,
            )
            if len(self.registry.updated_modules) == updated_modules_count:
                break

    def untranslate_dropped_fields(self) -> None:
        if not self.update_module:
            return
        registry = self.registry
        database_translated_fields = registry._database_translated_fields
        registry._database_translated_fields = {}
        registry._setup_models__(self.cr, [], skip_if_clean=True)
        models_to_untranslate = set()
        for full_name in database_translated_fields:
            model_name, field_name = full_name.rsplit(".", 1)
            if model_name in registry:
                field = registry[model_name]._fields.get(field_name)
                if field and not field.translate:
                    _logger.debug("Making field %s non-translated", field)
                    models_to_untranslate.add(model_name)
        registry.init_models(
            self.cr, list(models_to_untranslate), {"models_to_check": True}
        )

    def finish_registry_setup(self) -> None:
        self.registry.loaded = True
        self.registry._setup_models__(self.cr)

    def report_modules_that_never_loaded(self) -> None:
        Module = self.env["ir.module.module"]
        modules = Module.search_fetch(
            Module._get_domain_modules_to_load(), ["name"], order="name"
        )
        missing = [name for name in modules.mapped("name") if name not in self.graph]
        if missing:
            _logger.error(
                "Some modules are not loaded, some dependencies or manifest may be missing: %s",
                missing,
            )

    def run_end_migrations(self) -> None:
        if not self.update_module:
            return
        migrations = MigrationManager(self.cr, self.graph)
        for package in self.graph:
            migrations.migrate_module(package, "end")

    def report_pending_module_states(self) -> None:
        cr = self.cr
        cr.execute(
            "SELECT name, state FROM ir_module_module WHERE state IN ('to install', 'to upgrade')"
        )
        pending = cr.fetchall()
        if pending and self.update_module:
            _logger.error(
                "Some modules have inconsistent states after upgrade, "
                "some dependencies may be missing: %s",
                sorted(name for name, _state in pending),
            )
        elif pending:
            to_install = sorted(
                name for name, state in pending if state == "to install"
            )
            to_upgrade = sorted(
                name for name, state in pending if state == "to upgrade"
            )
            if to_upgrade:
                _logger.warning(
                    "Modules pending upgrade (restart with -u to process): %s",
                    to_upgrade,
                )
            if to_install:
                _logger.info(
                    "Modules pending installation (restart with -i or -u to process): %s",
                    to_install,
                )

    def finalize_constraints(self) -> None:
        self.registry.finalize_constraints(self.cr)

    def run_post_update_model_checks(self) -> None:
        if not self.registry.updated_modules:
            return
        env = self.env
        cr = self.cr
        cr.execute("SELECT model from ir_model")
        for (model,) in cr.fetchall():
            if model in self.registry:
                env[model]._check_removed_columns()
            elif _logger.isEnabledFor(logging.INFO):
                _logger.runbot(
                    "Model %s is declared but cannot be loaded! (Perhaps a module was partially removed or renamed)",
                    model,
                )

        env["ir.model.data"]._process_end(self.registry.updated_modules)
        vacuum_cron = env.ref("base.autovacuum_job", raise_if_not_found=False)
        if vacuum_cron:
            trigger_at = datetime.datetime.now(datetime.UTC).replace(
                tzinfo=None
            ) + datetime.timedelta(minutes=1)
            vacuum_cron._trigger(at=trigger_at)

        env.flush_all()

    def uninstall_removed_modules(self) -> None:
        if not self.update_module:
            return
        env = self.env
        cr = self.cr
        cr.execute(
            "SELECT name, id FROM ir_module_module WHERE state=%s",
            ("to remove",),
        )
        modules_to_remove = dict(cr.fetchall())
        if not modules_to_remove:
            return

        pkgs = reversed([p for p in self.graph if p.name in modules_to_remove])
        for pkg in pkgs:
            uninstall_hook = pkg.manifest.get("uninstall_hook")
            if uninstall_hook:
                py_module = sys.modules[f"odoo.addons.{pkg.name}"]
                getattr(py_module, uninstall_hook)(env)
                env.flush_all()

        Module = env["ir.module.module"]
        Module.browse(modules_to_remove.values()).module_uninstall()
        cr.commit()
        raise _UninstallRequiresReload

    def collect_models_with_manual_fields(self) -> None:
        if not self.update_module:
            return
        self.cr.execute(
            """SELECT DISTINCT model FROM ir_model_fields WHERE state = 'manual'"""
        )
        self.models_to_check.update(
            model_name
            for (model_name,) in self.cr.fetchall()
            if model_name in self.registry
        )

    def reinit_models_to_check(self) -> None:
        if not self.models_to_check:
            return
        models = [model for model in self.models_to_check if model in self.registry]
        self.registry.init_models(
            self.cr,
            models,
            {"models_to_check": True, "update_custom_fields": True},
        )

    def validate_custom_views(self) -> None:
        if not self.update_module:
            return
        View = self.env["ir.ui.view"]
        for model in self.registry:
            try:
                View._check_custom_views(model)
            except Exception as e:
                _logger.warning("invalid custom view(s) for model %s: %s", model, e)

    def log_assertion_report(self) -> None:
        report = self.registry._assertion_report
        if not report or report.wasSuccessful():
            _logger.info("Modules loaded.")
        else:
            _logger.error("At least one test failed when loading the modules.")

    def register_model_hooks(self) -> None:
        for model in self.env.values():
            model._register_hook()
        self.env.flush_all()

    def check_null_constraints(self) -> None:
        self.registry.check_null_constraints(self.cr)

    def flag_partially_updated_database(self) -> None:
        if not self.update_module:
            return
        self.cr.execute("""
            INSERT INTO ir_config_parameter(key, value)
            SELECT 'base.partially_updated_database', '1'
            WHERE EXISTS(SELECT FROM ir_module_module WHERE state IN ('to upgrade', 'to install', 'to remove'))
            ON CONFLICT DO NOTHING
            """)


def load_modules(
    registry: Registry,
    *,
    update_module: bool = False,
    upgrade_modules: Collection[str] = (),
    install_modules: Collection[str] = (),
    reinit_modules: Collection[str] = (),
    new_db_demo: bool = False,
    models_to_check: OrderedSet[str] | None = None,
    run_tests: bool = True,
) -> None:
    if models_to_check is None:
        models_to_check = OrderedSet()

    initialize_sys_path()

    with registry.cursor() as cr:
        loader = _ModuleLoader(
            registry,
            cr,
            update_module=update_module,
            upgrade_modules=upgrade_modules,
            install_modules=install_modules,
            reinit_modules=reinit_modules,
            new_db_demo=new_db_demo,
            models_to_check=models_to_check,
            run_tests=run_tests,
        )

        if not loader.bootstrap():
            return

        loader.run_pre_upgrade_scripts()
        loader.capture_database_field_metadata()
        loader.open_environment_and_load_base()
        loader.load_languages()
        loader.process_module_requests()
        loader.converge_module_graph()
        loader.untranslate_dropped_fields()
        loader.finish_registry_setup()
        loader.report_modules_that_never_loaded()
        loader.run_end_migrations()
        loader.report_pending_module_states()
        loader.finalize_constraints()
        loader.run_post_update_model_checks()

        try:
            loader.uninstall_removed_modules()
        except _UninstallRequiresReload:
            _logger.info("Reloading registry once more after uninstalling modules")
            Registry.new(
                cr.dbname,
                update_module=update_module,
                models_to_check=models_to_check,
            )
            return

        loader.collect_models_with_manual_fields()
        loader.reinit_models_to_check()
        loader.validate_custom_views()
        loader.log_assertion_report()
        loader.register_model_hooks()
        loader.check_null_constraints()
        loader.flag_partially_updated_database()


def reset_modules_state(db_name: str) -> None:
    db = odoo.db.db_connect(db_name)
    with db.cursor() as cr:
        if not schema.table_exists(cr, "ir_module_module"):
            _logger.info(
                "skipping reset_modules_state, ir_module_module table does not exist"
            )
            return
        cr.execute(
            "UPDATE ir_module_module SET state='installed' WHERE state IN ('to remove', 'to upgrade')"
        )
        reset_count = cr.rowcount
        cr.execute(
            "UPDATE ir_module_module SET state='uninstalled' WHERE state='to install'"
        )
        reset_count += cr.rowcount
        if reset_count:
            _logger.warning(
                "Transient module states were reset (%d modules)", reset_count
            )
