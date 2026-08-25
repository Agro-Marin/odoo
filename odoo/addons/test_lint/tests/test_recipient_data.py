"""Every recipients-data payload carries the whole of `RecipientData`.

This used to `ast.parse` all 9390 core Python files looking for dict literals
whose keys included `{"is_follower", "ushare"}`, and check a hardcoded list of
twelve key names against them. Measured over the tree it matched **one** literal
-- the return of `mail.tools.recipients.build_recipient_data` -- and zero in
`agromarin`, `enterprise` and `design-themes`. It cost 17% of the suite's
runtime to find it.

The twelve key names it carried were a byte-for-byte copy of the field list of
`RecipientData`, a *total* `TypedDict` declared immediately above the factory it
was checking. So the gate was a hand-maintained duplicate of a type annotation,
and the duplicate is the part that rots: add a field to `RecipientData` and the
old gate went on asserting the old twelve.

What is left asks the question directly, of the annotation rather than of a
regex over the tree. `mypy.ini` scopes the type checker to the six framework
packages, so `odoo/addons/**` is not type-checked and this is not redundant with
`py_typecheck.yml` -- it is what stands in for it here.
"""

import ast
import functools
import importlib.util
import inspect
from pathlib import Path

from odoo.modules import Manifest
from odoo.tests.common import BaseCase, no_retry


@functools.cache
def _recipients_module():
    """`mail/tools/recipients.py`, loaded on its own.

    By path rather than as `odoo.addons.mail.tools.recipients`, which would run
    `mail`'s package `__init__` and pull in the whole addon for two names. The
    file imports nothing but `typing`, so it stands alone.
    """
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
        returned = self._returned_keys(self.mail.build_recipient_data)
        self.assertTrue(
            returned,
            "build_recipient_data no longer returns a dict literal, so this "
            "check cannot see what it produces -- read the fields off the "
            "return annotation instead, or restore the literal",
        )
        declared = set(self.RecipientData.__annotations__)
        self.assertEqual(
            returned,
            declared,
            "build_recipient_data and RecipientData disagree about the payload. "
            "A consumer reads the whole payload off any entry in the list, so a "
            "missing key is a KeyError in whichever notification path reaches it "
            "first.",
        )

    def test_the_typed_dict_is_total(self):
        """A partial `TypedDict` would make the check above assert nothing."""
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
