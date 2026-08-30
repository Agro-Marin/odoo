"""`xml_import` keeps three parallel stacks; all three are seeded.

`envs` and `_noupdate` were given an initial entry and `_sequences` was not, so
`next_sequence()` read `[-1]` off an empty list for any caller that reaches
`_tag_record` without a `_tag_root` frame -- which mail's `mixin_template_reset`
does, calling `obj._tag_record(rec)` on a freshly constructed importer.

The env is a stub: none of this touches the ORM, and the point is what
`__init__` sets up before anything is parsed.
"""

import typing
import unittest

from odoo.tools.convert import xml_import

if typing.TYPE_CHECKING:
    from odoo.api import Environment


class _StubEnv:
    """Enough Environment for `__init__`, which only re-derives the context."""

    context: dict = {}

    def __call__(self, **kwargs):
        return self


class TestImporterStacks(unittest.TestCase):
    def _importer(self) -> xml_import:
        # cast rather than a real Environment: none of what this pins touches the
        # ORM, and odoo.tools is a mypy hard zero
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
        # None, not 0: 0 would make next_sequence() hand out 10, 20, ... to a
        # record whose file never asked for auto_sequence
        self.assertIsNone(self._importer()._sequences[-1])

    def test_noupdate_and_env_still_answer_the_same_way(self):
        obj = self._importer()
        self.assertIs(obj.noupdate, False)
        self.assertIsInstance(obj.env, _StubEnv)
