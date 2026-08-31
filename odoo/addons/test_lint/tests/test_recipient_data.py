import ast
import functools
import importlib.util
import inspect
from pathlib import Path

from odoo.modules import Manifest
from odoo.tests.common import BaseCase, no_retry


@functools.cache
def _recipients_module():
    manifest = Manifest.for_addon("mail")
    if manifest is None:
        return None
    path = Path(manifest.path) / "tools" / "recipients.py"
    spec = importlib.util.spec_from_file_location("_test_lint_recipients", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@no_retry
class TestRecipientData(BaseCase):
    def setUp(self):
        super().setUp()
        self.mail = _recipients_module()
        if self.mail is None:
            self.skipTest("mail is not on this addons path")

    @property
    def RecipientData(self):
        return self.mail.RecipientData

    def test_the_factory_fills_every_field_of_the_typed_dict(self):
        returned = self._returned_keys(self.mail.prepare_recipient_data)
        self.assertTrue(
            returned,
            "prepare_recipient_data no longer returns a dict literal, so this "
            "check cannot see what it produces -- read the fields off the "
            "return annotation instead, or restore the literal",
        )
        declared = set(self.RecipientData.__annotations__)
        self.assertEqual(
            returned,
            declared,
            "prepare_recipient_data and RecipientData disagree about the payload. "
            "A consumer reads the whole payload off any entry in the list, so a "
            "missing key is a KeyError in whichever notification path reaches it "
            "first.",
        )

    def test_the_typed_dict_is_total(self):
        self.assertTrue(
            self.RecipientData.__total__,
            "RecipientData became partial, so its keys are optional and the "
            "agreement asserted above no longer means every entry carries them",
        )

    @staticmethod
    def _returned_keys(function) -> set[str]:
        tree = ast.parse(inspect.getsource(function).lstrip())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
                continue
            keys = set()
            for key in node.value.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    return set()
                keys.add(key.value)
            return keys
        return set()
