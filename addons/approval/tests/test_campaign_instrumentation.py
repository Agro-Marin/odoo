"""The campaign instrumentation's own invariants -- TEMPORARY, goes with the campaign.

`machine_doc_v1/conventions.md`, "Campaign Instrumentation", states three things a
reader is asked to rely on. Each is a test here, because a census nobody checks
drifts into a ranked work list that sends a session after noise:

* a call that SUCCEEDS logs no refusal, so `odoo.approval.refusal` aggregated over a
  corpus is what the engine actually turns away rather than what it asked itself;
* every `raise` of a user-facing error reports a refusal, so that census is complete
  and not a biased sample of the sites somebody remembered;
* every method `CALL_TRACES` names still exists, so a rename cannot silently unwrap
  an entry point and leave a target printing nothing.
"""

import ast
import re
from pathlib import Path

from .common import ApprovalCommon
from odoo.addons.approval.models import approval_trace as trace

RAISE = re.compile(r"^\s*raise (UserError|ValidationError|AccessError)\(")
REFUSAL_EVENT = re.compile(r"trace\.REFUSAL\.event\(")

# A raise reached by several callers for several reasons reports at each CALLER
# instead, so one event cannot collapse four causes into one census row.
REPORTED_BY_ITS_CALLERS = frozenset({"_raise_not_assigned_approver"})

ADDON = Path(__file__).resolve().parents[1]


def _source_files():
    for folder in ("models", "wizards", "reports"):
        yield from sorted((ADDON / folder).glob("*.py"))


class TestCampaignRefusalCensus(ApprovalCommon):
    def test_a_green_flow_logs_no_refusal(self):
        """The null control: nothing the engine turns away happens here, so the
        refusal target must stay silent. It did not, once: a guard answering a
        question through a refusing form filed a refusal for every caller that
        merely asked."""
        category = self._make_category(
            name="Census Green",
            approvers=[self.approver_1, self.approver_2],
        )
        with self.assertNoLogs("odoo.approval.refusal", level="DEBUG"):
            request = self._prepare_request(category)
            request.with_user(self.approver_1).action_approve()
            request.with_user(self.approver_2).action_approve()
            self.assertEqual(request.state, "approved")
            request.with_user(self.approver_2).action_withdraw()
            self.assertEqual(request.state, "pending")
            request.with_user(self.approver_2).action_approve()
            self.assertEqual(request.state, "approved")
            request.with_user(self.manager_user).action_reset_to_draft()
            self.assertEqual(request.state, "new")
            request.action_confirm()

    def test_a_refused_call_names_its_own_kind(self):
        category = self._make_category(name="Census Red", approvers=[self.approver_1])
        request = self._prepare_request(category)
        with self.assertLogs("odoo.approval.refusal", level="DEBUG") as captured:
            with self.assertRaises(Exception):
                request.action_confirm()
        self.assertTrue(
            any("confirm_not_draft" in line for line in captured.output),
            captured.output,
        )
        self.assertTrue(
            any(f"request={request.id}" in line for line in captured.output),
            captured.output,
        )

    def test_every_raise_reports_a_refusal(self):
        """Completeness, so the ranked census is not a sample of what was easy to
        instrument. A new guard either reports its own kind or is named in
        REPORTED_BY_ITS_CALLERS with the callers that report for it."""
        unreported = []
        for path in _source_files():
            lines = path.read_text().split("\n")
            for index, line in enumerate(lines):
                if not RAISE.match(line):
                    continue
                if REFUSAL_EVENT.search("\n".join(lines[max(0, index - 14) : index])):
                    continue
                owner = next(
                    (
                        match.group(1)
                        for earlier in range(index, -1, -1)
                        if (match := re.match(r"^    def (\w+)", lines[earlier]))
                    ),
                    "?",
                )
                if owner in REPORTED_BY_ITS_CALLERS:
                    continue
                unreported.append(f"{path.name}:{index + 1} {owner}")
        self.assertEqual(unreported, [], "\n".join(unreported))

    def test_the_reported_kinds_are_distinct(self):
        """Two sites sharing a kind are one census row, which hides one of them."""
        kinds = []
        for path in _source_files():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                target = node.func
                if not (
                    isinstance(target, ast.Attribute)
                    and target.attr == "event"
                    and isinstance(target.value, ast.Attribute)
                    and target.value.attr == "REFUSAL"
                ):
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant):
                    kinds.append(first.value)
        duplicated = sorted({kind for kind in kinds if kinds.count(kind) > 1})
        self.assertEqual(duplicated, [], f"kinds used twice: {duplicated}")


class TestCampaignCallTraces(ApprovalCommon):
    def test_every_wrapped_method_exists(self):
        missing = [
            f"{model_name}.{method}"
            for model_name, methods in trace.CALL_TRACES.items()
            for method in methods
            if model_name in self.env.registry
            and not hasattr(self.env.registry[model_name], method)
        ]
        self.assertEqual(missing, [], "\n".join(missing))

    def test_every_wrapped_model_is_concrete(self):
        """An abstract model's registry class is inherited by nobody, so wrapping it
        instruments nothing: the mixins are instrumented by hand instead."""
        abstract = [
            model_name
            for model_name in trace.CALL_TRACES
            if model_name in self.env.registry and self.env[model_name]._abstract
        ]
        self.assertEqual(abstract, [], "\n".join(abstract))

    def test_every_target_name_is_declared(self):
        unknown = sorted(
            {
                target
                for methods in trace.CALL_TRACES.values()
                for target in methods.values()
            }
            - set(trace._BY_NAME)
        )
        self.assertEqual(unknown, [], "\n".join(unknown))
