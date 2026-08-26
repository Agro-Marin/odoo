import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import TestCase as _StdTestCase

from .. import tools
from .result import OdooTestResult
from .suite import OdooSuite
from .tag_selector import TagsSelector

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator


def get_module_test_cases(module: Any) -> Iterator[_StdTestCase]:
    # The *stdlib* base on purpose, not odoo.tests.case.TestCase: a third-party
    # test that subclasses unittest.TestCase directly must still be discovered,
    # and the vendored class is a subclass of this one so it matches either way.
    # Spelled _StdTestCase because every sibling in this package says
    # `from . import case`, meaning the vendored module -- the bare name `case`
    # here used to be the stdlib one, so the same identifier meant two
    # different modules depending on the file.
    for obj in module.__dict__.values():
        if not isinstance(obj, type):
            continue
        if not issubclass(obj, _StdTestCase):
            continue
        if obj.__module__ != module.__name__:
            continue

        test_case_class = obj
        if getattr(test_case_class, "allow_inherited_tests_method", False):
            test_cases = inspect.getmembers(test_case_class, callable)
        else:
            test_cases = sorted(test_case_class.__dict__.items())

        for method_name, method in test_cases:
            if not callable(method):
                continue
            if not method_name.startswith("test"):
                continue
            yield test_case_class(method_name)


def get_test_modules(module: str) -> list[Any]:
    results = _get_tests_modules(f"odoo.addons.{module}")
    results += list(_get_upgrade_test_modules(module))

    return results


def _get_tests_modules(package_name: str) -> list[Any]:
    spec = importlib.util.find_spec(".tests", package_name)
    if not spec:
        return []

    tests_mod = importlib.import_module(spec.name)
    return [
        mod_obj
        for name, mod_obj in inspect.getmembers(tests_mod, inspect.ismodule)
        if name.startswith("test_")
    ]


def _get_upgrade_test_modules(module: str) -> Generator[Any]:
    upgrade_modules = (
        f"odoo.upgrade.{module}",
        f"odoo.addons.{module}.migrations",
        f"odoo.addons.{module}.upgrades",
    )
    for module_name in upgrade_modules:
        if not importlib.util.find_spec(module_name):
            continue

        upg = importlib.import_module(module_name)
        for path in map(Path, upg.__path__):
            for test in path.glob("tests/test_*.py"):
                spec = importlib.util.spec_from_file_location(
                    f"{upg.__name__}.tests.{test.stem}", test
                )
                if not spec:
                    continue
                # make_suite runs once per position, so without this check the
                # module body is executed twice -- at_install then post_install --
                # producing two distinct sets of class objects for one file.
                if (pymod := sys.modules.get(spec.name)) is None:
                    pymod = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = pymod
                    try:
                        spec.loader.exec_module(pymod)
                    except BaseException:
                        # Drop the half-initialised module, as importlib's own
                        # loader does. Leaving it cached made the *second*
                        # position find it non-None, skip the exec and yield a
                        # module whose test classes were never defined -- so the
                        # file's tests silently did not run and nothing failed.
                        sys.modules.pop(spec.name, None)
                        raise
                yield pymod


def make_suite(module_names: list[str], position: str = "at_install") -> OdooSuite:
    config_tags = TagsSelector(tools.config["test_tags"])
    position_tag = TagsSelector(position)
    tests = (
        t
        for module_name in module_names
        for m in get_test_modules(module_name)
        for t in get_module_test_cases(m)
        if position_tag.check(t) and config_tags.check(t)
    )
    return OdooSuite(sorted(tests, key=lambda t: getattr(t, "test_sequence", 0)))


def run_suite(
    suite: OdooSuite, global_report: OdooTestResult | None = None
) -> OdooTestResult:
    from ..modules import module

    module.current_test = True
    try:
        results = OdooTestResult(global_report=global_report)
        suite(results)
    finally:
        module.current_test = False
    return results
