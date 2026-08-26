#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mail_hook_keyword_check as mhk


class Tree:
    def __init__(self, stack: TemporaryDirectory):
        self.root = Path(stack.name)
        self.framework = self.root / "mail" / "models"
        self.framework.mkdir(parents=True)

    def write(self, rel: str, src: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
        return path

    def measure(self):
        return mhk.measure(
            [self.root], framework_dir=self.framework, caller_dir=self.root / "mail"
        )


class HookCase(unittest.TestCase):
    def setUp(self):
        self._stack = TemporaryDirectory()
        self.addCleanup(self._stack.cleanup)
        self.tree = Tree(self._stack)

    def hooks(self, **kwargs):
        self.tree.write(
            "mail/models/mixin_mail_thread.py",
            "class MixinMailThread:\n"
            "    def _notify_by_email_prepare_rendering_context(\n"
            "        self, message, msg_values, tracking_values=None\n"
            "    ):\n"
            "        return {}\n"
            "\n"
            "    def _notify_by_email_prepare(self, message, msg_values):\n"
            "        return self._notify_by_email_prepare_rendering_context(\n"
            "            message, msg_values, tracking_values=msg_values\n"
            "        )\n",
        )


class TestTheRegressionItWasBuiltFor(HookCase):
    def test_an_override_left_behind_is_reported(self):
        self.hooks()
        self.tree.write(
            "project/models/project_task.py",
            "class ProjectTask:\n"
            "    def _notify_by_email_prepare_rendering_context(self, message, msg_values):\n"
            "        return super()._notify_by_email_prepare_rendering_context(\n"
            "            message, msg_values\n"
            "        )\n",
        )
        (finding,) = self.tree.measure()
        self.assertEqual(finding.hook, "_notify_by_email_prepare_rendering_context")
        self.assertEqual(finding.missing, ("tracking_values",))
        self.assertIn("project_task.py", finding.path)

    def test_the_same_override_updated_is_not(self):
        self.hooks()
        self.tree.write(
            "project/models/project_task.py",
            "class ProjectTask:\n"
            "    def _notify_by_email_prepare_rendering_context(\n"
            "        self, message, msg_values, tracking_values=None\n"
            "    ):\n"
            "        return super()._notify_by_email_prepare_rendering_context(\n"
            "            message, msg_values, tracking_values=tracking_values\n"
            "        )\n",
        )
        self.assertEqual(self.tree.measure(), [])


class TestWhatIsDeliberatelyNotFlagged(HookCase):
    def test_a_positionally_passed_parameter_may_be_renamed(self):
        self.tree.write(
            "mail/models/mixin_mail_thread.py",
            "class MixinMailThread:\n"
            "    def _track_subtype(self, initial_values):\n"
            "        return False\n"
            "\n"
            "    def _notify_track(self, initial_values):\n"
            "        return self._track_subtype(initial_values)\n"
            "\n"
            "    def _message_probe(self, message, tracking_values=None):\n"
            "        return self._message_probe(message, tracking_values=1)\n",
        )
        self.tree.write(
            "crm/models/crm_lead.py",
            "class CrmLead:\n"
            "    def _track_subtype(self, init_values):\n"
            "        return super()._track_subtype(init_values)\n",
        )
        self.assertEqual(self.tree.measure(), [])

    def test_an_override_absorbing_kwargs_is_free(self):
        self.hooks()
        self.tree.write(
            "crm/models/crm_lead.py",
            "class CrmLead:\n"
            "    def _notify_by_email_prepare_rendering_context(self, message, msg_values, **kwargs):\n"
            "        return super()._notify_by_email_prepare_rendering_context(\n"
            "            message, msg_values, **kwargs\n"
            "        )\n",
        )
        self.assertEqual(self.tree.measure(), [])

    def test_a_method_the_framework_never_declared_is_not_a_hook(self):
        self.hooks()
        self.tree.write(
            "crm/models/crm_lead.py",
            "class CrmLead:\n"
            "    def _message_invented_here(self, message):\n"
            "        return message\n",
        )
        self.assertEqual(self.tree.measure(), [])

    def test_a_test_fixture_override_is_free(self):
        self.hooks()
        self.tree.write(
            "project/tests/test_something.py",
            "class TaskProbe:\n"
            "    def _notify_by_email_prepare_rendering_context(self, message, msg_values):\n"
            "        return {}\n",
        )
        self.assertEqual(self.tree.measure(), [])

    def test_a_module_level_function_is_not_an_override(self):
        self.hooks()
        self.tree.write(
            "project/models/helpers.py",
            "def _notify_by_email_prepare_rendering_context(message, msg_values):\n"
            "    return {}\n",
        )
        self.assertEqual(self.tree.measure(), [])

    def test_a_keyword_only_parameter_counts_as_accepted(self):
        self.hooks()
        self.tree.write(
            "crm/models/crm_lead.py",
            "class CrmLead:\n"
            "    def _notify_by_email_prepare_rendering_context(\n"
            "        self, message, msg_values, *, tracking_values=None\n"
            "    ):\n"
            "        return {}\n",
        )
        self.assertEqual(self.tree.measure(), [])


class TestABaseDeclaredTwice(HookCase):
    def setUp(self):
        super().setUp()
        self.tree.write(
            "mail/models/a_mixin.py",
            "class MixinMailThread:\n"
            "    def _message_update_content(self, message, **kwargs):\n"
            "        return None\n"
            "\n"
            "    def _message_caller(self, message):\n"
            "        return self._message_update_content(message, strict=True)\n",
        )
        self.tree.write(
            "mail/models/z_channel.py",
            "class DiscussChannel:\n"
            "    def _message_update_content(self, message, strict=False):\n"
            "        return None\n",
        )

    def test_a_keyword_only_the_second_declaration_takes_is_accepted(self):
        self.tree.write(
            "crm/models/crm_lead.py",
            "class CrmLead:\n"
            "    def _message_update_content(self, message, strict=False):\n"
            "        return None\n",
        )
        self.assertEqual(self.tree.measure(), [])

    def test_that_keyword_still_binds_an_override_that_lacks_it(self):
        self.tree.write(
            "hr/models/employee.py",
            "class HrEmployee:\n"
            "    def _message_update_content(self, message):\n"
            "        return None\n",
        )
        (finding,) = self.tree.measure()
        self.assertEqual(finding.missing, ("strict",))
        self.assertIn("employee.py", finding.path)


class TestDeclarationsInsideTheFrameworkAreCheckedToo(HookCase):
    def test_a_stale_redeclaration_inside_mail_is_reported(self):
        self.hooks()
        self.tree.write(
            "mail/models/discuss_channel.py",
            "class DiscussChannel:\n"
            "    def _notify_by_email_prepare_rendering_context(self, message, msg_values):\n"
            "        return {}\n",
        )
        (finding,) = self.tree.measure()
        self.assertEqual(finding.missing, ("tracking_values",))
        self.assertIn("discuss_channel.py", finding.path)

    def test_the_declaration_introducing_the_keyword_does_not_flag_itself(self):
        self.hooks()
        self.assertEqual(self.tree.measure(), [])


class TestItRefusesRatherThanReportZero(HookCase):
    def test_no_hooks_found_refuses(self):
        self.tree.write("crm/models/crm_lead.py", "class CrmLead:\n    pass\n")
        with self.assertRaises(SystemExit) as caught:
            self.tree.measure()
        self.assertIn("no hooks found", str(caught.exception))

    def test_hooks_that_are_never_called_by_keyword_refuse(self):
        self.tree.write(
            "mail/models/mixin_mail_thread.py",
            "class MixinMailThread:\n"
            "    def _notify_by_email_prepare_rendering_context(self, message):\n"
            "        return {}\n",
        )
        with self.assertRaises(SystemExit) as caught:
            self.tree.measure()
        self.assertIn("passes no keyword", str(caught.exception))


class TestTheRealTree(unittest.TestCase):
    def test_the_community_tree_is_clean(self):
        self.assertEqual([str(f) for f in mhk.measure()], [])

    def test_the_scan_reaches_the_real_mail_hooks(self):
        self.assertTrue((mhk.ROOT / mhk.FRAMEWORK_DIR).is_dir())


if __name__ == "__main__":
    unittest.main()
