import typing
import unittest

from odoo.tools.convert import xml_import

if typing.TYPE_CHECKING:
    from odoo.api import Environment


class _StubEnv:
    context: dict = {}

    def __call__(self, **kwargs):
        return self


class TestImporterStacks(unittest.TestCase):
    def _importer(self) -> xml_import:
        env = typing.cast("Environment", _StubEnv())
        return xml_import(env, "base", None, "init")

    def test_all_three_stacks_answer_before_any_root_is_entered(self):
        obj = self._importer()
        self.assertEqual(len(obj.envs), 1)
        self.assertEqual(len(obj._noupdate), 1)
        self.assertEqual(len(obj._sequences), 1, "_sequences was the one left unseeded")

    def test_next_sequence_outside_a_root_answers_instead_of_raising(self):
        self.assertIsNone(self._importer().next_sequence())

    def test_the_seeded_frame_means_auto_sequence_off(self):
        self.assertIsNone(self._importer()._sequences[-1])

    def test_noupdate_and_env_still_answer_the_same_way(self):
        obj = self._importer()
        self.assertIs(obj.noupdate, False)
        self.assertIsInstance(obj.env, _StubEnv)
