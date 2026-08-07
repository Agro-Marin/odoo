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
    """Return ``(hexdigest, dynamic)`` for a data file's raw content.

    The digest algorithm is the one :mod:`odoo.libs.hashing` selected; stored
    values are invalidated wholesale by ``_DATA_FILE_CHECKSUM_VERSION``, so
    they never need to be self-describing.
    """
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
    """Load the data (or demo) files declared by ``package``'s manifest.

    noupdate is False, unless it is demo data.

    On upgrade (``mode == "update"``, ``kind == "data"``), files whose content
    is byte-identical to the last successful load are skipped: their records
    are left as-is and the xmlids they asserted back then (recorded via
    ``Registry._xmlid_recorder``) are replayed into ``registry.loaded_xmlids``
    so ``ir.model.data._process_end`` does not clean them up as orphans.
    Checksums live in ``ir_module_module.data_file_checksums``.  Dynamic files
    (see ``_scan_data_file``) always reload; ``--reload-unchanged-data-files``
    disables the skip globally and ``--reinit`` forces a full re-assertion of
    a module (reinit loads with ``mode == "init"``, which never skips).
    """
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
    """Loads demo data for the specified package."""

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
    """Forces the `demo` flag on all modules, and installs demo data for all installed modules."""
    env.cr.execute("UPDATE ir_module_module SET demo=True")
    env.cr.execute(
        "SELECT name FROM ir_module_module WHERE state IN ('installed', 'to upgrade', 'to remove')"
    )
    module_list = [name for (name,) in env.cr.fetchall()]
    graph = ModuleGraph(env.cr, mode="load")
    graph.extend(module_list)

    for package in graph:
        load_demo(env, package, {}, "init")

    env["ir.module.module"].invalidate_model(["demo"])


def _warn_models_without_access_rules(
    env: Environment,
    module_name: str,
    model_names: Collection[str],
    registry: Registry,
) -> None:
    """Log a hint listing concrete models in ``model_names`` that have no ACLs.

    Abstract models are excluded (they have no table and need no access rules).
    """
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


def load_module_graph(
    env: Environment,
    graph: ModuleGraph,
    update_module: bool = False,
    report: OdooTestResult | None = None,
    models_to_check: OrderedSet[str] | None = None,
    install_demo: bool = True,
) -> None:
    """Load, upgrade and install not-yet-loaded module nodes in ``graph`` for ``env.registry``.

    :param env: environment whose registry is populated
    :param graph: graph of module nodes to load
    :param update_module: whether to update modules or not
    :param report: test result collecting the tests run while loading
    :param models_to_check: accumulator of model names to re-check afterwards;
        updated in place
    :param install_demo: whether to attempt installing demo data for newly installed modules
    """
    if models_to_check is None:
        models_to_check = OrderedSet()

    registry = env.registry
    assert isinstance(env.cr, odoo.db.Cursor), "Need for a real Cursor to load modules"
    migrations = MigrationManager(env.cr, graph)
    module_count = len(graph)
    _logger.info("loading %d modules...", module_count)

    t0 = time.time()
    loading_extra_query_count = odoo.db.sql_counter
    loading_cursor_query_count = env.cr.sql_log_count

    models_updated = set()
    gc_sweeps = 0

    try:
        for index, package in enumerate(graph, 1):
            module_name = package.name
            module_id = package.id

            if module_name in registry._init_modules:
                continue

            module_t0 = time.time()
            module_cursor_query_count = env.cr.sql_log_count
            module_extra_query_count = odoo.db.sql_counter

            if not update_module:
                update_operation = None
            elif package.state == "to install":
                update_operation = "install"
            elif package.state == "to upgrade":
                update_operation = "upgrade"
            elif module_name in registry._reinit_modules:
                update_operation = "reinit"
            else:
                update_operation = None
            module_log_level = logging.DEBUG
            if update_operation:
                module_log_level = logging.INFO
            _logger.log(
                module_log_level,
                "Loading module %s (%d/%d)",
                module_name,
                index,
                module_count,
            )

            if update_operation:
                if update_operation == "upgrade":
                    if package.name != "base":
                        registry._setup_models__(env.cr, [], skip_if_clean=True)
                    migrations.migrate_module(package, "pre")
                if package.name != "base":
                    env.flush_all()

            load_odoo_module(package.name)

            if update_operation == "install":
                py_module = sys.modules[f"odoo.addons.{module_name}"]
                pre_init = package.manifest.get("pre_init_hook")
                if pre_init:
                    registry._setup_models__(env.cr, [], skip_if_clean=True)
                    getattr(py_module, pre_init)(env)

            model_names = registry.load(package)

            if update_operation:
                model_names = registry.descendants(model_names, "_inherit", "_inherits")
                models_updated |= model_names
                models_to_check -= model_names
                registry._setup_models__(env.cr, [], skip_if_clean=True)
                registry.init_models(
                    env.cr,
                    model_names,
                    {"module": package.name},
                    update_operation == "install",
                )
            elif update_module and package.state != "to remove":
                model_names = registry.descendants(model_names, "_inherit", "_inherits")
                models_to_check |= model_names & models_updated
            elif update_module and package.state == "to remove":
                models_to_check |= model_names

            if update_operation:
                module = env["ir.module.module"].browse(module_id)
                module._check()

                idref: dict = {}

                if update_operation == "install":
                    load_data(env, idref, "init", kind="data", package=package)
                    if install_demo and package.demo_installable:
                        package.demo = load_demo(env, package, idref, "init")
                else:
                    module.write(module.get_values_from_terp(package.manifest))
                    mode = "update" if update_operation == "upgrade" else "init"
                    load_data(env, idref, mode, kind="data", package=package)
                    if package.demo:
                        package.demo = load_demo(env, package, idref, mode)
                env.cr.execute(
                    "UPDATE ir_module_module SET demo = %s WHERE id = %s",
                    (package.demo, module_id),
                )
                module.invalidate_model(["demo"])

                migrations.migrate_module(package, "post")

                overwrite = tools.config["overwrite_existing_translations"]
                module._update_translations(overwrite=overwrite)

            registry._init_modules.add(package.name)

            if update_operation:
                if update_operation == "install":
                    post_init = package.manifest.get("post_init_hook")
                    if post_init:
                        getattr(py_module, post_init)(env)
                elif update_operation == "upgrade":
                    env["ir.ui.view"]._validate_module_views(module_name)

                _warn_models_without_access_rules(
                    env, module_name, model_names, registry
                )

                registry.updated_modules.append(package.name)

                ver = adapt_version(package.manifest["version"])
                values = {"state": "installed", "db_version": ver}
                if schema.column_exists(env.cr, "ir_module_module", "content_checksum"):
                    values["content_checksum"] = module_content_checksum(module_name)
                module.write(values)

                package.state = "installed"
                module.env.flush_all()
                module.env.cr.commit()

            test_time = 0.0
            test_queries = 0
            test_results = None

            update_from_config = (
                tools.config["update"] or tools.config["init"] or tools.config["reinit"]
            )
            if tools.config["test_enable"] and (
                update_operation or not update_from_config
            ):
                from odoo.tests import loader

                suite = loader.make_suite([module_name], "at_install")
                if suite.countTestCases():
                    if not update_operation:
                        registry._setup_models__(env.cr, [], skip_if_clean=True)
                    registry.check_null_constraints(env.cr)
                    tests_t0, tests_q0 = time.time(), odoo.db.sql_counter
                    test_results = loader.run_suite(suite, global_report=report)
                    assert report is not None, "Missing report during tests"
                    report.update(test_results)
                    test_time = time.time() - tests_t0
                    test_queries = odoo.db.sql_counter - tests_q0

                    module = env["ir.module.module"].browse(module_id)

            extra_queries = (
                odoo.db.sql_counter - module_extra_query_count - test_queries
            )
            extras = []
            if test_queries:
                extras.append(f"+{test_queries} test")
            if extra_queries:
                extras.append(f"+{extra_queries} other")
            _logger.log(
                module_log_level,
                "Module %s loaded in %.2fs%s, %s queries%s",
                module_name,
                time.time() - module_t0,
                f" (incl. {test_time:.2f}s test)" if test_time else "",
                env.cr.sql_log_count - module_cursor_query_count,
                f" ({', '.join(extras)})" if extras else "",
            )
            if test_results and not test_results.wasSuccessful():
                _logger.error(
                    "Module %s: %d failures, %d errors of %d tests",
                    module_name,
                    test_results.failures_count,
                    test_results.errors_count,
                    test_results.testsRun,
                )

            env.invalidate_all()

            if gc.get_count()[0] > _GC_YOUNG_BACKLOG_LIMIT:
                registry._caches.clear_all()
                gc_sweeps += 1
                if gc_sweeps % _GC_FULL_CYCLE_EVERY == 0:
                    gc.unfreeze()
                    gc.collect()
                else:
                    gc.collect(generation=1)
                gc.freeze()

    finally:
        gc.unfreeze()

    _logger.runbot(
        "%s modules loaded in %.2fs, %s queries (+%s extra)",
        len(graph),
        time.time() - t0,
        env.cr.sql_log_count - loading_cursor_query_count,
        odoo.db.sql_counter - loading_extra_query_count,
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
    """The uninstall phase removed modules; the registry must be rebuilt.

    Replaces a bare ``return`` that used to sit in the middle of
    ``load_modules``, after that branch had already called ``Registry.new()``
    itself. Two things were wrong with that shape: the recursion was invisible
    from the top of the function, and the ~45 lines of tail phases after it were
    skipped by an accident of statement order rather than by a decision.

    Raising instead puts both facts where a reader meets them --
    ``load_modules`` catches this, rebuilds, and returns -- and makes "the tail
    does not run in the *outer* call" an explicit branch. It stays true that the
    tail runs exactly once overall, because the *inner* build runs it; that is
    pinned by ``tests/loading/test_load_modules_uninstall.py``.
    """


class _ModuleLoader:
    """The state ``load_modules`` threads through its phases.

    ``load_modules`` was a single 332-line procedure with 70 branches -- the
    densest function in the core -- operating on five names held in one long
    scope. The phases were real but anonymous: nine separate ``if
    update_module:`` blocks interleaved the "install/upgrade" program into the
    "load an existing database" one, and the reader had to hold the whole body
    to know whether a given line ran.

    Each phase is now a method named for what it does, and ``load_modules`` is
    the composition root that lists them in order. Behaviour is unchanged --
    ``tests/loading/`` characterizes the phase sequence for both programs and
    the uninstall branch, and was written before this refactor for that purpose.

    Note the two programs are *not* split into separate methods. They interleave
    at nine points, so a clean split would have to duplicate the shared spine at
    each one; keeping one sequence with its guards visible in the composition
    root says the same thing without the duplication.
    """

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
    ) -> None:
        self.registry = registry
        self.cr = cr
        self.update_module = update_module
        self.upgrade_modules = upgrade_modules
        self.install_modules = install_modules
        self.reinit_modules = reinit_modules
        self.new_db_demo = new_db_demo
        #: Accumulator, mutated in place -- the caller reads it back.
        self.models_to_check = models_to_check
        self.graph: ModuleGraph = None  # type: ignore[assignment]
        self.env = None  # type: ignore[assignment]
        self.report = None

    # -- phase 1 ----------------------------------------------------------
    def bootstrap(self) -> bool:
        """Initialise the database if needed and seed the graph with ``base``.

        :return: whether loading should continue. ``False`` means an
            uninitialised database and no ``update_module`` to initialise it --
            the one early exit that is not an error.
        """
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

    # -- phase 2 [update] -------------------------------------------------
    def run_pre_upgrade_scripts(self) -> None:
        for pyfile in tools.config["pre_upgrade_scripts"]:
            odoo.modules.migration.exec_script(
                self.cr, self.graph["base"].db_version, pyfile, "base", "pre"
            )

    # -- phase 3 [update] -------------------------------------------------
    def capture_database_field_metadata(self) -> None:
        """Record which fields the *database* thinks are translated / company-dependent.

        Read before the modules are loaded, because loading is what may change
        them; ``untranslate_dropped_fields`` below compares against this.
        """
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

    # -- phase 4 ----------------------------------------------------------
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
        )

    # -- phase 5 ----------------------------------------------------------
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

    # -- phase 6 [update] -------------------------------------------------
    def process_module_requests(self) -> None:
        """Turn the requested install / upgrade / reinit sets into module states."""
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

    # -- phase 7 ----------------------------------------------------------
    def converge_module_graph(self) -> None:
        """Extend the graph and reload until no further module is loaded.

        Each round can make more modules reachable (a newly installed module's
        dependents), so this runs to a fixpoint rather than a fixed number of
        passes. It terminates on either no new module names or no new
        ``updated_modules``.
        """
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
            )
            if len(self.registry.updated_modules) == updated_modules_count:
                break

    # -- phase 8 [update] -------------------------------------------------
    def untranslate_dropped_fields(self) -> None:
        """Re-initialise models whose fields stopped being ``translate=True``."""
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

    # -- phase 9 ----------------------------------------------------------
    def finish_registry_setup(self) -> None:
        self.registry.loaded = True
        self.registry._setup_models__(self.cr)

    # -- phase 10 ---------------------------------------------------------
    def report_modules_that_never_loaded(self) -> None:
        Module = self.env["ir.module.module"]
        modules = Module.search_fetch(
            Module._get_modules_to_load_domain(), ["name"], order="name"
        )
        missing = [name for name in modules.mapped("name") if name not in self.graph]
        if missing:
            _logger.error(
                "Some modules are not loaded, some dependencies or manifest may be missing: %s",
                missing,
            )

    # -- phase 11 [update] ------------------------------------------------
    def run_end_migrations(self) -> None:
        migrations = MigrationManager(self.cr, self.graph)
        for package in self.graph:
            migrations.migrate_module(package, "end")

    # -- phase 12 ---------------------------------------------------------
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

    # -- phase 13 ---------------------------------------------------------
    def finalize_constraints(self) -> None:
        self.registry.finalize_constraints(self.cr)

    # -- phase 14 ---------------------------------------------------------
    def run_post_update_model_checks(self) -> None:
        """Only meaningful when something was actually updated."""
        if not self.registry.updated_modules:
            return
        env = self.env
        cr = self.cr
        cr.execute("SELECT model from ir_model")
        for (model,) in cr.fetchall():
            if model in self.registry:
                env[model]._check_removed_columns(log=True)
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

    # -- phase 15 [update] ------------------------------------------------
    def uninstall_removed_modules(self) -> None:
        """Uninstall modules in state ``to remove``.

        :raises _UninstallRequiresReload: when anything was uninstalled. The
            registry now describes models that no longer exist, so the caller
            must rebuild it rather than continue with the remaining phases.
        """
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

    # -- phase 16 [update] ------------------------------------------------
    def collect_models_with_manual_fields(self) -> None:
        self.cr.execute(
            """SELECT DISTINCT model FROM ir_model_fields WHERE state = 'manual'"""
        )
        self.models_to_check.update(
            model_name
            for (model_name,) in self.cr.fetchall()
            if model_name in self.registry
        )

    # -- phase 17 ---------------------------------------------------------
    def reinit_models_to_check(self) -> None:
        if not self.models_to_check:
            return
        models = [model for model in self.models_to_check if model in self.registry]
        self.registry.init_models(
            self.cr,
            models,
            {"models_to_check": True, "update_custom_fields": True},
        )

    # -- phase 18 [update] ------------------------------------------------
    def validate_custom_views(self) -> None:
        View = self.env["ir.ui.view"]
        for model in self.registry:
            try:
                View._validate_custom_views(model)
            except Exception as e:
                _logger.warning("invalid custom view(s) for model %s: %s", model, e)

    # -- phase 19 ---------------------------------------------------------
    def log_assertion_report(self) -> None:
        report = self.registry._assertion_report
        if not report or report.wasSuccessful():
            _logger.info("Modules loaded.")
        else:
            _logger.error("At least one test failed when loading the modules.")

    # -- phase 20 ---------------------------------------------------------
    def register_model_hooks(self) -> None:
        for model in self.env.values():
            model._register_hook()
        self.env.flush_all()

    # -- phase 21 ---------------------------------------------------------
    def check_null_constraints(self) -> None:
        self.registry.check_null_constraints(self.cr)

    # -- phase 22 [update] ------------------------------------------------
    def flag_partially_updated_database(self) -> None:
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
) -> None:
    """Load the modules for a registry object that has just been created.  This
    function is part of Registry.new() and should not be used anywhere else.

    The body is a composition root over :class:`_ModuleLoader`'s phases, listed
    in execution order. Phases guarded by ``if update_module:`` are the
    install/upgrade program; the rest run on every load. The phase sequence for
    both programs is characterized by ``tests/loading/``.

    :param registry: The new inited registry object used to load modules.
    :param update_module: Whether to update (install, upgrade, or uninstall) modules. Defaults to ``False``
    :param upgrade_modules: A collection of module names to upgrade.
    :param install_modules: A collection of module names to install.
    :param reinit_modules: A collection of module names to reinitialize.
    :param new_db_demo: Whether to install demo data for new database. Defaults to ``False``
    :param models_to_check: accumulator of model names to re-check afterwards;
        updated in place
    """
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
        )

        if not loader.bootstrap():
            return

        if update_module and upgrade_modules:
            loader.run_pre_upgrade_scripts()
        if update_module and schema.table_exists(cr, "ir_model_fields"):
            loader.capture_database_field_metadata()

        loader.open_environment_and_load_base()
        loader.load_languages()

        if update_module:
            loader.process_module_requests()

        loader.converge_module_graph()

        if update_module:
            loader.untranslate_dropped_fields()

        loader.finish_registry_setup()
        loader.report_modules_that_never_loaded()

        if update_module:
            loader.run_end_migrations()

        loader.report_pending_module_states()
        loader.finalize_constraints()
        loader.run_post_update_model_checks()

        try:
            if update_module:
                loader.uninstall_removed_modules()
        except _UninstallRequiresReload:
            # The uninstalled models are still in this registry, so it cannot be
            # trusted for the remaining phases: rebuild instead. The rebuild
            # runs those phases itself, which is why the tail below is skipped
            # here and still happens exactly once overall
            # (tests/loading/test_load_modules_uninstall.py).
            _logger.info("Reloading registry once more after uninstalling modules")
            Registry.new(
                cr.dbname,
                update_module=update_module,
                models_to_check=models_to_check,
            )
            return

        if update_module:
            loader.collect_models_with_manual_fields()
        loader.reinit_models_to_check()

        if update_module:
            loader.validate_custom_views()

        loader.log_assertion_report()
        loader.register_model_hooks()
        loader.check_null_constraints()

        if update_module:
            loader.flag_partially_updated_database()


def reset_modules_state(db_name: str) -> None:
    """Resets modules flagged as "to x" to their original state"""
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
