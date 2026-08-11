"""Stub the package ancestors of the DB-free suites, before pytest imports them.

The Tier-1 suites import leaf modules -- ``odoo.orm.components.cache``,
``odoo.libs.text.*`` -- and must not pay for the package ``__init__`` above
them. ``odoo/orm/__init__.py`` is one line, ``import odoo.init``, and that line
is the whole framework bootstrap: the Rust extension and its freshness CRC, the
gc thresholds, the monkeypatches. Registering a stub package with the right
``__path__`` lets the leaf import resolve while the real ``__init__`` never
runs.

WHY THIS IS A PLUGIN AND NOT JUST A CONFTEST CALL. Under
``--import-mode=importlib`` pytest imports a conftest's parent packages
*before* executing the conftest body -- ``_import_module_using_spec`` recurses
into the parent chain (``_pytest/pathlib.py``, the ``parent_module is None or
need_reimport`` branch) and only then calls ``exec_module``. So a conftest that
stubs its own ancestors is always too late: by the time its first line runs,
the real ``odoo.orm`` has already been imported and ``_stub_package`` finds it
in ``sys.modules`` and returns early. That is not a hypothetical -- it made
every ``stub_odoo_packages`` call in the tree a no-op, and it is why the
``components (pure stdlib)`` CI job, which installs pytest and nothing else,
failed at conftest import on the odoo_rust ImportError.

``pytest_load_initial_conftests`` is the hook that runs before initial conftest
import, so the stubs are in ``sys.modules`` when pytest goes looking for the
parents, and the ``need_reimport`` test above sees a module that already has a
``__path__``.

WHICH SUITES GET STUBBED. ``testpaths`` in pytest.ini is the Tier-1 registry --
the Tier-2 real-import paths (``odoo/orm/tests``, ``odoo/http/tests``,
``tests/service``) are deliberately excluded from it, which is exactly the
distinction needed here. A target is stubbed only if it lies within a testpath
and its directory carries a conftest, so the Tier-2 invocation stubs nothing
and keeps its real ``import odoo.*``. The two invocations stay mutually
exclusive for the reason pytest.ini already gives: these stubs are
process-global.
"""

import sys
import types
from pathlib import Path

__all__ = ["stub_odoo_packages"]


def _stub_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    module.__file__ = str(path / "__init__.py")
    sys.modules[name] = module


def _package_chain(directory: Path) -> list[tuple[str, Path]] | None:
    """Name every package between ``directory`` and the ``odoo`` root above it.

    Returns None when there is no ``odoo`` ancestor -- ``tooling/`` is in
    ``testpaths`` and is not part of the package, so it is skipped rather than
    treated as an error.
    """
    intermediates: list[Path] = []
    current = directory.parent
    while current.name and current.name != "odoo":
        intermediates.append(current)
        current = current.parent

    if current.name != "odoo":
        return None

    chain = [("odoo", current)]
    name = "odoo"
    for package_dir in reversed(intermediates):
        name = f"{name}.{package_dir.name}"
        chain.append((name, package_dir))
    return chain


def stub_odoo_packages(conftest_file: str) -> None:
    """Stub the packages above a suite's ``tests`` directory.

    Kept as the per-suite declaration each conftest makes about itself, and as
    the path that still works when a suite is run by something other than this
    plugin. Idempotent: when the plugin has already registered a stub, or when
    a real module is present, ``_stub_package`` leaves it alone.
    """
    tests_dir = Path(conftest_file).resolve().parent
    chain = _package_chain(tests_dir)
    if chain is None:
        raise RuntimeError(
            f"could not locate the 'odoo' package root above {conftest_file!r}"
        )
    for name, path in chain:
        _stub_package(name, path)


def _stub_for_target(target: Path) -> None:
    directory = target if target.is_dir() else target.parent
    if not (directory / "conftest.py").is_file():
        return
    chain = _package_chain(directory)
    if chain is None:
        return
    for name, path in chain:
        _stub_package(name, path)


def pytest_load_initial_conftests(early_config, parser, args) -> None:
    rootpath = Path(early_config.rootpath)

    testpaths = [
        (rootpath / entry).resolve() for entry in early_config.getini("testpaths")
    ]
    if not testpaths:
        return

    # A bare `pytest` collects testpaths; explicit arguments replace them. Strip
    # options and any `::nodeid` selector to get back to a filesystem path.
    selected = [arg for arg in args if not arg.startswith("-")]
    targets = [(rootpath / arg.split("::")[0]).resolve() for arg in selected]
    if not targets:
        targets = testpaths

    for target in targets:
        within = any(
            target == testpath or testpath in target.parents for testpath in testpaths
        )
        if within:
            _stub_for_target(target)


pytest_load_initial_conftests.tryfirst = True  # before pytest imports conftests
