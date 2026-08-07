import ast
import copy
import functools
import importlib
import importlib.machinery
import importlib.metadata
import logging
import os
import re
import sys
import traceback
import types
import typing
from collections.abc import Collection, Mapping
from pathlib import Path

import odoo.upgrade
from odoo import release, tools
from odoo.libs.hashing import ALGO_TAG, cache_hasher, update_from_file

import odoo.addons

try:
    from packaging.requirements import InvalidRequirement, Requirement
except ImportError:

    class InvalidRequirement(Exception): ...

    class Requirement:
        def __init__(self, pydep):
            if not re.fullmatch(r"[\w\-]+", pydep):
                msg = f"Package `packaging` is required to parse `{pydep}` external dependency and is not installed"
                raise ImportError(msg)
            self.marker = None
            self.specifier = None
            self.name = pydep


__all__ = [
    "Manifest",
    "adapt_version",
    "get_manifest",
    "get_module_path",
    "get_modules",
    "get_resource_from_path",
    "initialize_sys_path",
    "load_odoo_module",
    "load_script",
    "module_content_checksum",
]

MODULE_NAME_RE = re.compile(r"^\w{1,256}$", re.ASCII)
MANIFEST_NAMES = ["__manifest__.py"]
README = ["README.rst", "README.md", "README.txt", "README"]

_DEFAULT_MANIFEST = {
    "application": False,
    "bootstrap": False,
    "assets": {},
    "auto_install": False,
    "category": "Uncategorized",
    "cloc_exclude": [],
    "configurator_snippets": {},
    "configurator_snippets_addons": {},
    "countries": [],
    "data": [],
    "demo": [],
    "demo_xml": [],
    "depends": [],
    "description": "",
    "external_dependencies": {},
    "init_xml": [],
    "installable": True,
    "images": [],
    "images_preview_theme": {},
    "live_test_url": "",
    "new_page_templates": {},
    "post_init_hook": "",
    "post_load": "",
    "pre_init_hook": "",
    "sequence": 100,
    "summary": "",
    "test": [],
    "theme_customizations": {},
    "update_xml": [],
    "uninstall_hook": "",
    "version": "1.0",
    "web": False,
    "website": "",
}

TYPED_FIELD_DEFINITION_RE = re.compile(
    r"""
    \b (?P<field_name>\w+) \s*
    (:\s*(?P<field_type>[^ ]*))? \s*
    = \s*
    fields\.(?P<field_class>Many2one|One2many|Many2many)
    (\[(?P<type_param>[^\]]+)\])?
""",
    re.VERBOSE,
)

_logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from odoo.tests.common import TestCase

current_test: TestCase | bool = False
"""Test-mode marker observed by loggers, mail, reports and the ORM.

The value follows a small state machine driven by ``odoo.tests``:

* ``False`` — no test is running (default and steady state).
* ``True`` — ``loader.run_suite`` has begun; the suite has not yet selected
  a specific :class:`TestCase`.  Brief, observable only between
  :class:`OdooSuite.run` iterations.
* ``TestCase`` instance — set by ``OdooSuite.run`` for the currently
  executing test, and read by consumers as ``current_test.canonical_tag`` or
  ``current_test.get_log_metadata()``.  Consumers that dereference attributes
  must guard against the bool form (e.g. with ``contextlib.suppress``).

A plain global is correct: Odoo uses fork-based concurrency, so each worker
gets its own copy, and tests require ``--workers=0``.
"""


class UpgradeHook:
    """Make the legacy `migrations` package resolve to `odoo.upgrade`.

    Uses the PEP 451 loader protocol (create_module/exec_module). Triggered
    only by multi-version upgrade scripts importing from the legacy name.
    """

    def find_spec(
        self,
        fullname: str,
        path: typing.Any = None,
        target: types.ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if re.match(r"^odoo\.addons\.base\.maintenance\.migrations\b", fullname):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
        """Use default module creation semantics."""
        return

    def exec_module(self, module: types.ModuleType) -> None:
        """Redirect import to the canonical odoo.upgrade module."""
        canonical_name = module.__name__.replace(
            "odoo.addons.base.maintenance.migrations", "odoo.upgrade"
        )
        if canonical_name in sys.modules:
            canonical = sys.modules[canonical_name]
        else:
            canonical = importlib.import_module(canonical_name)

        sys.modules[module.__name__] = canonical


def initialize_sys_path() -> None:
    """
    Setup the addons path ``odoo.addons.__path__`` with various defaults
    and explicit directories.
    """
    for path in (
        tools.config.addons_data_dir,
        *tools.config["addons_path"],
        tools.config.addons_community_dir,
    ):
        if os.access(path, os.R_OK) and path not in odoo.addons.__path__:
            odoo.addons.__path__.append(path)

    legacy_upgrade_path = str(
        Path(tools.config.addons_base_dir, "base/maintenance/migrations")
    )
    for up in tools.config["upgrade_path"] or [legacy_upgrade_path]:
        if up not in odoo.upgrade.__path__:
            odoo.upgrade.__path__.append(up)

    spec = importlib.machinery.ModuleSpec(
        "odoo.addons.base.maintenance", None, is_package=True
    )
    maintenance_pkg = importlib.util.module_from_spec(spec)
    maintenance_pkg.migrations = odoo.upgrade
    sys.modules["odoo.addons.base.maintenance"] = maintenance_pkg
    sys.modules["odoo.addons.base.maintenance.migrations"] = odoo.upgrade

    current_addons_path = tuple(odoo.addons.__path__)
    if getattr(initialize_sys_path, "_last_addons_path", None) != current_addons_path:
        Manifest.clear_caches()
        initialize_sys_path._last_addons_path = current_addons_path

    if not getattr(initialize_sys_path, "called", False):
        odoo.addons.__path__._path_finder = lambda *a: None
        odoo.upgrade.__path__._path_finder = lambda *a: None
        sys.meta_path.insert(0, UpgradeHook())
        initialize_sys_path.called = True


@typing.final
class Manifest(Mapping[str, typing.Any]):
    """The manifest data of a module."""

    _COMPUTED_KEYS = (
        "description",
        "icon",
        "addons_path",
        "version",
        "static_path",
    )

    def __init__(self, *, path: str, manifest_content: dict):
        assert Path(path).is_absolute(), "path of module must be absolute"
        self.path = path
        self.name = Path(path).name
        if not MODULE_NAME_RE.match(self.name):
            raise ValueError(f"Invalid module name: {self.name}")
        self.__manifest_content = manifest_content

    @property
    def addons_path(self) -> str:
        p = Path(self.path)
        assert p.name == self.name
        return str(p.parent)

    @functools.cached_property
    def __manifest_cached(self) -> dict[str, typing.Any]:
        """Parsed and validated manifest data from the file."""
        return _load_manifest(self.name, self.__manifest_content)

    @functools.cached_property
    def description(self) -> str:
        """The description of the module defaulting to the README file."""
        if desc := self.__manifest_cached.get("description"):
            return desc
        for file_name in README:
            try:
                with tools.file_open(str(Path(self.path, file_name))) as f:
                    return f.read()
            except OSError:
                pass
        return ""

    @functools.cached_property
    def version(self) -> str:
        try:
            return self.__manifest_cached["version"]
        except KeyError:
            return adapt_version("1.0")

    @functools.cached_property
    def icon(self) -> str:
        return get_module_icon(self.name)

    @functools.cached_property
    def static_path(self) -> str | None:
        static = Path(self.path, "static")
        manifest = self.__manifest_cached
        if (manifest["installable"] or manifest["assets"]) and static.is_dir():
            return str(static)
        return None

    def __getitem__(self, key: str) -> typing.Any:
        if key in self._COMPUTED_KEYS:
            return getattr(self, key)
        val = self.__manifest_cached[key]
        if isinstance(val, (str, int, bool, float)):
            return val
        return copy.deepcopy(val)

    def raw_value(self, key: str) -> typing.Any:
        return copy.deepcopy(self.__manifest_cached.get(key))

    def _force_parse(self) -> None:
        """Parse the manifest now instead of on first access.

        Parsing is normally deferred (``__manifest_cached`` is a
        ``cached_property``). Force it during graph construction so manifest
        validation errors surface up-front rather than mid-loop.
        """
        self.__manifest_cached

    def __iter__(self) -> typing.Iterator[str]:
        manifest = self.__manifest_cached
        yield from manifest
        for key in self._COMPUTED_KEYS:
            if key not in manifest:
                yield key

    def check_manifest_dependencies(self) -> None:
        """Check that the dependencies of the manifest are available.

        - Checking for external python dependencies
        - Checking binaries are available in PATH

        On missing dependencies, raise an error.
        """
        depends = self.get("external_dependencies")
        if not depends:
            return
        for pydep in depends.get("python", []):
            check_python_external_dependency(pydep)

        for binary in depends.get("bin", []):
            try:
                tools.find_in_path(binary)
            except OSError as e:
                msg = f"Unable to find {binary!r} in path"
                raise MissingDependencyError(msg, binary) from e

    def __bool__(self) -> bool:
        return True

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __repr__(self) -> str:
        return f"Manifest({self.name})"

    _manifest_cache: dict[str, Manifest] = {}

    @staticmethod
    def _get_manifest_from_addons(module: str) -> Manifest | None:
        """Get the module's manifest from a name. Searching only in addons paths."""
        if (cached := Manifest._manifest_cache.get(module)) is not None:
            return cached
        for adp in odoo.addons.__path__:
            if manifest := Manifest._from_path(str(Path(adp, module))):
                Manifest._manifest_cache[module] = manifest
                return manifest
        return None

    @staticmethod
    def clear_caches() -> None:
        """Drop memoized manifests.

        Call this when the addons path changes or modules are added/updated on
        disk so that :meth:`for_addon` reflects the new state.
        """
        Manifest._manifest_cache.clear()

    @staticmethod
    def for_addon(module_name: str, *, display_warning: bool = True) -> Manifest | None:
        """Get the module's manifest from a name.

        :param module_name: module's name
        :param display_warning: log a warning if the module is not found
        """
        if not MODULE_NAME_RE.match(module_name):
            return None
        if mod := Manifest._get_manifest_from_addons(module_name):
            return mod
        if display_warning:
            _logger.warning("module %s: manifest not found", module_name)
        return None

    @staticmethod
    def _from_path(path: str, env: typing.Any = None) -> Manifest | None:
        """Given a path, read the manifest file.

        ``env`` is required to read a manifest located inside a temporary
        directory created via ``file_open_temporary_directory()`` (e.g. when
        importing a module from a zip file); ``file_open`` needs it to allow
        that transient path.
        """
        for manifest_name in MANIFEST_NAMES:
            try:
                with tools.file_open(str(Path(path, manifest_name)), env=env) as f:
                    manifest_content = ast.literal_eval(f.read())
            except OSError:
                pass
            except (SyntaxError, ValueError) as e:
                _logger.warning(
                    "Failed to parse the manifest file at %r: %s",
                    path,
                    e,
                )
            else:
                try:
                    return Manifest(path=path, manifest_content=manifest_content)
                except ValueError:
                    _logger.debug(
                        "Manifest at %r has invalid module name, skipped",
                        path,
                    )
        return None

    @staticmethod
    def all_addon_manifests() -> list[Manifest]:
        """Read all manifests in the addons paths."""
        modules: dict[str, Manifest] = {}
        for adp in odoo.addons.__path__:
            if not Path(adp).is_dir():
                _logger.warning("addons path is not a directory: %s", adp)
                continue
            for entry in Path(adp).iterdir():
                if entry.name in modules:
                    continue
                if mod := Manifest._from_path(str(entry)):
                    assert entry.name == mod.name
                    modules[entry.name] = mod
        return sorted(modules.values(), key=lambda m: m.name)


def get_module_path(module: str, display_warning: bool = True) -> str | None:
    """Return the path of the given module.

    Search the addons paths and return the first path where the given
    module is found.
    """
    mod = Manifest.for_addon(module, display_warning=display_warning)
    return mod.path if mod else None


_CHECKSUM_IGNORE_DIRS = frozenset({"__pycache__", ".git"})
_CHECKSUM_IGNORE_SUFFIXES = (".pyc", ".pyo", ".swp", "~")


def module_content_checksum(module: str) -> str | None:
    """Return an algorithm-tagged hexdigest over the module directory's content.

    Covers every regular file (relative path and bytes) except caches and
    editor droppings, in sorted order, so the digest is stable across
    checkouts and hosts.  Returns None when the module has no directory on
    the current addons path.  Used by ``ir.module.module`` to detect modules
    whose code and data did not change since their last successful upgrade
    (see ``button_upgrade``); deliberately *not* cached — a running server
    may see the directory change under it on deploy.

    The ``<algo>:`` prefix makes the digest self-describing: a value stamped
    by a different algorithm compares unequal, so the module is re-upgraded
    rather than skipped on stale evidence.  Switching algorithms therefore
    costs one upgrade pass per module, never a wrong skip.
    """
    path = get_module_path(module, display_warning=False)
    if not path:
        return None
    digest = cache_hasher()
    root = Path(path)
    files = sorted(
        p
        for p in root.rglob("*")
        if not _CHECKSUM_IGNORE_DIRS.intersection(p.parts)
        and not p.name.endswith(_CHECKSUM_IGNORE_SUFFIXES)
        and p.is_file()
    )
    for p in files:
        digest.update(str(p.relative_to(root)).encode())
        digest.update(b"\0")
        update_from_file(digest, p)
        digest.update(b"\0")
    return f"{ALGO_TAG}:{digest.hexdigest()}"


def get_resource_from_path(path: str) -> tuple[str, str, str] | None:
    """Tries to extract the module name and the resource's relative path
    out of an absolute resource path.

    If operation is successful, returns a tuple containing the module name, the relative path
    to the resource using '/' as filesystem separator[1] and the same relative path using
    OS-native separators.

    [1] same convention as the resource path declaration in manifests

    :param path: absolute resource path

    :rtype: tuple
    :return: tuple(module_name, relative_path, os_relative_path) if possible, else None
    """
    p = Path(path)
    sorted_paths = sorted(odoo.addons.__path__, key=len, reverse=True)
    for adpath in sorted_paths:
        try:
            rel = p.relative_to(adpath)
        except ValueError:
            continue
        parts = rel.parts
        if not parts:
            continue
        module = parts[0]
        relative = parts[1:]
        return (
            module,
            "/".join(relative),
            str(Path(*relative)) if relative else "",
        )
    return None


def get_module_icon(module: str) -> str:
    """Get the path to the module's icon. Invalid module names are accepted."""
    manifest = Manifest.for_addon(module, display_warning=False)
    fpath = ""
    if manifest:
        fpath = (manifest.raw_value("icon") or "").lstrip("/")
    if not fpath:
        fpath = f"{module}/static/description/icon.png"
    try:
        tools.file_path(fpath)
        return "/" + fpath
    except FileNotFoundError:
        return "/base/static/description/icon.png"


def _load_manifest(module: str, manifest_content: dict) -> dict:
    """Load and validate the module manifest.

    Return a new dictionary with cleaned and validated keys.
    """

    manifest = {
        k: (v.copy() if isinstance(v, (list, dict)) else v)
        for k, v in _DEFAULT_MANIFEST.items()
    }
    manifest.update(manifest_content)

    if not manifest.get("author"):
        author = manifest.get("contributors") or manifest.get("maintainer") or ""
        if isinstance(author, (list, tuple)):
            author = ", ".join(str(a) for a in author)
        else:
            author = str(author)
        manifest["author"] = author
        _logger.warning(
            "Missing `author` key in manifest for %r, defaulting to %r",
            module,
            author,
        )

    if not manifest.get("license"):
        manifest["license"] = "LGPL-3"
        _logger.warning(
            "Missing `license` key in manifest for %r, defaulting to LGPL-3",
            module,
        )

    if module == "base":
        manifest["depends"] = []
    elif not manifest["depends"]:
        manifest["depends"] = ["base"]

    depends = manifest["depends"]
    if isinstance(depends, str):
        raise TypeError(
            f"module {module}: 'depends' must be a list of module names; got"
            f" string {depends!r} (did you forget the brackets, e.g."
            f" ['{depends}']?)"
        )
    assert isinstance(depends, Collection)

    auto_install = manifest["auto_install"]
    if isinstance(auto_install, str):
        raise TypeError(
            f"module {module}: 'auto_install' must be a bool or a list/tuple/set"
            f" of dependency names; got string {auto_install!r} (did you forget"
            f" the brackets, e.g. ['{auto_install}']?)"
        )
    if isinstance(auto_install, (list, tuple, set, frozenset)):
        manifest["auto_install"] = auto_install_set = set(auto_install)
        non_dependencies = auto_install_set.difference(depends)
        assert not non_dependencies, (
            f"module {module}: auto_install triggers must be dependencies,"
            f" found non-dependencies [{', '.join(non_dependencies)}]"
        )
    elif auto_install is True:
        manifest["auto_install"] = set(depends)
    elif auto_install is not False:
        raise TypeError(
            f"module {module}: 'auto_install' must be a bool or a"
            f" list/tuple/set of dependency names; got"
            f" {type(auto_install).__name__}: {auto_install!r}"
        )

    try:
        manifest["version"] = adapt_version(str(manifest["version"]))
    except ValueError:
        if manifest["installable"]:
            _logger.warning(
                "The module %s has an invalid version %r, setting installable=False",
                module,
                manifest["version"],
            )
            manifest["installable"] = False
    if manifest["installable"] and not check_version(
        str(manifest["version"]), should_raise=False
    ):
        _logger.warning(
            "The module %s has an incompatible version, setting installable=False",
            module,
        )
        manifest["installable"] = False

    return manifest


def get_manifest(module: str, mod_path: str | None = None) -> Mapping[str, typing.Any]:
    """
    Get the module manifest.

    :param str module: The name of the module (sale, purchase, ...).
    :param str | None mod_path: The optional path to the module on
        the file-system. If not set, it is determined by scanning the
        addons-paths.
    :returns: The module manifest as a dict or an empty dict
        when the manifest was not found.
    """
    if mod_path:
        mod = Manifest._from_path(mod_path)
        if mod and mod.name != module:
            raise ValueError(f"Invalid path for module {module}: {mod_path}")
    else:
        mod = Manifest.for_addon(module, display_warning=False)
    return mod if mod is not None else {}


def load_odoo_module(module_name: str) -> None:
    """Load an Odoo module, if not already loaded.

    Import the module and register its models, via either the MetaModel
    metaclass or explicit model instantiation. Also used for server-wide
    modules, which may register no models.
    """

    qualname = f"odoo.addons.{module_name}"
    if qualname in sys.modules:
        return

    try:
        __import__(qualname)

        manifest = Manifest.for_addon(module_name)
        if manifest and (post_load := manifest.get("post_load")):
            getattr(sys.modules[qualname], post_load)()

    except AttributeError as err:
        _logger.critical("Couldn't load module %s", module_name)
        trace = traceback.format_exc()
        match = TYPED_FIELD_DEFINITION_RE.search(trace)
        if match and "most likely due to a circular import" in trace:
            field_name = match["field_name"]
            field_class = match["field_class"]
            field_type = match["field_type"] or match["type_param"]
            if "." not in field_type:
                field_type = f"{module_name}.{field_type}"
            raise AttributeError(
                f"{err}\n"
                "To avoid circular import for the comodel, use the annotation syntax:\n"
                f"    {field_name}: {field_type} = fields.{field_class}(...)\n"
                "Annotations are lazily evaluated (PEP 649), so the comodel\n"
                "class does not need to be importable at field definition time."
            ).with_traceback(err.__traceback__) from None
        raise
    except Exception:
        _logger.critical("Couldn't load module %s", module_name)
        raise


def get_modules() -> list[str]:
    """Get the list of module names that can be loaded."""
    return [m.name for m in Manifest.all_addon_manifests()]


def adapt_version(version: str) -> str:
    """Reformat the version of the module into a canonical format."""
    parts = version.split(".")
    if not (2 <= len(parts) <= 5):
        raise ValueError(
            f"Invalid version {version!r}, must have between 2 and 5 parts"
        )
    try:
        for part in parts:
            int(part)
    except ValueError as e:
        raise ValueError(f"Invalid version {version!r}") from e
    serie = release.major_version
    if len(parts) <= 3 and version != serie and not version.startswith(serie + "."):
        return f"{serie}.{version}"
    return version


def check_version(version: str, should_raise: bool = True) -> bool:
    """Check that the version is in a valid format for the current release."""
    try:
        version = adapt_version(version)
    except ValueError:
        if should_raise:
            raise
        return False
    serie = release.major_version
    if version == serie or version.startswith(serie + "."):
        return True
    if should_raise:
        raise ValueError(
            f"Invalid version {version!r}. Modules should have a version in format"
            f" `x.y`, `x.y.z`, `{serie}.x.y` or `{serie}.x.y.z`."
        )
    return False


class MissingDependencyError(Exception):
    def __init__(self, message: str, dependency: str) -> None:
        self.dependency = dependency
        super().__init__(message)


def check_python_external_dependency(pydep: str) -> None:
    try:
        requirement = Requirement(pydep)
    except InvalidRequirement as e:
        msg = f"{pydep} is an invalid external dependency specification: {e}"
        raise ValueError(msg) from e
    if requirement.marker and not requirement.marker.evaluate():
        _logger.debug(
            "Ignored external dependency %s because environment markers do not match",
            pydep,
        )
        return
    try:
        version = importlib.metadata.version(requirement.name)
    except importlib.metadata.PackageNotFoundError as e:
        try:
            importlib.import_module(requirement.name)
            _logger.warning(
                "python external dependency on '%s' does not appear to be a valid PyPI package. Using a PyPI package name is recommended.",
                requirement.name,
            )
            return
        except ImportError:
            pass
        msg = f"External dependency {pydep!r} not installed: {e}"
        raise MissingDependencyError(msg, pydep) from e
    if requirement.specifier and not requirement.specifier.contains(version):
        msg = f"External dependency version mismatch: {pydep} (installed: {version})"
        raise MissingDependencyError(msg, pydep)


def load_script(path: str, module_name: str) -> types.ModuleType:
    full_path = tools.file_path(path) if not Path(path).is_absolute() else path
    spec = importlib.util.spec_from_file_location(module_name, full_path)
    assert spec and spec.loader, f"spec not found for {module_name}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
