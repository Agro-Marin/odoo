import unittest
from typing import Any, cast

from odoo.modules import loading
from odoo.tools import OrderedSet

BaseCase = unittest.TestCase

PUBLIC = "hr.employee.public"


class _Cursor:
    sql_log_count = 0


class _Registry:
    def __init__(self, models_of):
        self.models_of = models_of
        self.init_calls = []

    def load(self, package):
        return list(self.models_of.get(package.name, ()))

    def descendants(self, model_names, *_kinds):
        return OrderedSet(model_names)

    def _setup_models__(self, _cr, _model_names, skip_if_clean=False):
        return None

    def init_models(self, _cr, model_names, context, _install=True):
        self.init_calls.append((list(model_names), context))


class _Env:
    def __init__(self, registry):
        self.registry = registry
        self.cr = _Cursor()


class _Package:
    def __init__(self, name, state):
        self.name = name
        self.state = state


def _load(env, package, operation, models_to_check, models_updated):
    loader = loading._PackageLoader(
        env,
        env.cr,
        package,
        index=1,
        module_count=2,
        migrations=cast("Any", None),
        update_module=True,
        install_demo=False,
        run_tests=False,
        report=None,
        models_to_check=models_to_check,
        models_updated=models_updated,
    )
    loader.operation = operation
    loader.load_models()


class TestModelsUpdatedSharing(BaseCase):
    def setUp(self):
        self.env = _Env(_Registry({"hr": [PUBLIC], "hr_second_lastname": [PUBLIC]}))
        self.models_to_check: OrderedSet[str] = OrderedSet()
        self.models_updated: set[str] = set()

    def _upgrade_hr(self):
        _load(
            self.env,
            _Package("hr", "to upgrade"),
            "upgrade",
            self.models_to_check,
            self.models_updated,
        )

    def _load_extension(self):
        _load(
            self.env,
            _Package("hr_second_lastname", "installed"),
            None,
            self.models_to_check,
            self.models_updated,
        )

    def test_an_upgraded_package_records_into_the_shared_set(self):
        self._upgrade_hr()
        self.assertIn(PUBLIC, self.models_updated)

    def test_a_later_package_extending_an_upgraded_model_queues_a_recheck(self):
        self._upgrade_hr()
        self._load_extension()
        self.assertIn(PUBLIC, self.models_to_check)

    def test_an_untouched_model_is_not_queued(self):
        self._load_extension()
        self.assertNotIn(PUBLIC, self.models_to_check)
