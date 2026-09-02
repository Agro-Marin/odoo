"""A fixture model belongs to a ``test_*`` module, not to the module it exercises.

A model whose ``_name`` carries ``test`` as a namespace segment -- ``a.test.b``,
never merely ``a.b.test`` -- exists to be written to by a suite. Declaring one
from a production module registers it unconditionally: every customer database
that installs the module gets its table, its ``ir.model`` row, its
``ir.model.fields`` rows and whatever ACL surface follows, forever, for a
consumer that only ever runs under ``--test-enable``.

The framework's own convention is the opposite one and predates the fork:
``test_orm``, ``test_base_order``, ``test_date_range`` and ``test_automation``
are separate modules, so nothing installs their models by accident. This gate
holds that line at zero.

The shape stops at the *last* segment on purpose. ``mailing.mailing.test``,
``mailing.sms.test`` and ``accounting.assert.test`` are shipped features -- a
test mailing, a test SMS, an accounting consistency test -- where ``test`` is
the domain noun rather than a namespace, and they are named that way in menus
their users read.
"""

import ast
import logging
import os
from pathlib import Path

from odoo.modules import Manifest

from . import lint_case

_logger = logging.getLogger(__name__)


def core_module_roots_by_name() -> list[tuple[str, str]]:
    return sorted(
        (str(manifest.path), manifest.name)
        for manifest in Manifest.all_addon_manifests()
        if lint_case.is_core_path(str(manifest.path))
    )


def module_of(path: str, roots: list[tuple[str, str]]) -> str | None:
    for root, name in roots:
        if path.startswith(root + os.sep):
            return name
    return None


def declared_model_names(source: str):
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            for target in statement.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "_name"
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                ):
                    yield statement.value.value


def is_fixture_model_name(name: str) -> bool:
    return "test" in name.split(".")[:-1]


class TestFixtureModelsLiveInTestModules(lint_case.LintCase):
    def test_no_fixture_model_is_declared_by_a_production_module(self):
        roots = core_module_roots_by_name()
        scanned = 0
        findings = []
        for path in lint_case.iter_module_files("*.py"):
            if not lint_case.is_core_path(path):
                continue
            module = module_of(path, roots)
            if module is None or module.startswith("test_"):
                continue
            scanned += 1
            source = Path(path).read_text(encoding="utf-8")
            findings.extend(
                f"{path}: {name}"
                for name in declared_model_names(source)
                if is_fixture_model_name(name)
            )

        _logger.info(
            "scanned %s python file(s) of modules that are not test_*", scanned
        )
        self.assert_ratchet(
            findings,
            "lint_fixture_model_module",
            "fixture model(s) declared outside a test_* module",
            "Move the model, and the tests that write to it, into a test_* "
            "module that depends on this one -- see test_approval, "
            "test_mixin_report_sql and test_html_editor.",
        )
