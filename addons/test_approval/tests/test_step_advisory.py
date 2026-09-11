from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestStepAdvisory(ApprovalCommon):
    """An advisory step asks and records, but decides nothing.

    An engineering change's optional reviewers and commenters are asked with everyone
    else, and what they say is kept; the change goes ahead on its required approvals
    alone, and an optional reviewer saying no stops nothing.
    """

    def _category(self, **vals):
        return self._make_category(
            name=f"Advisory {self.id()}", approvers=[], company_id=False, **vals
        )

    def _step(self, category, sequence, users, **vals):
        return self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": f"Step {sequence}",
                "sequence": sequence,
                "minimum": 1,
                "user_ids": [(6, 0, users.ids)],
                **vals,
            }
        )

    def _blocking_and_advisory(self, **category_vals):
        category = self._category(**category_vals)
        self._step(category, 10, self.approver_1)
        self._step(category, 20, self.approver_2, advisory=True)
        return category, self._prepare_request(category)

    def _row(self, request, user):
        return request.approver_ids.filtered(lambda row: row.user_id == user)

    def test_the_request_is_approved_without_its_advisory_step(self):
        _category, request = self._blocking_and_advisory()

        request.with_user(self.approver_1).action_approve()

        self.assertEqual(request.state, "approved")
        self.assertEqual(self._row(request, self.approver_2).state, "waiting")
        self.assertFalse(request._get_approval_activities())

    def test_an_advisory_approval_does_not_count(self):
        _category, request = self._blocking_and_advisory()

        request.with_user(self.approver_2).action_approve()

        self.assertEqual(request.state, "pending")
        self.assertEqual(self._row(request, self.approver_2).state, "approved")

    def test_an_advisory_refusal_refuses_nothing(self):
        _category, request = self._blocking_and_advisory()

        request.with_user(self.approver_2).with_context(
            skip_wizard=True
        ).action_refuse()

        self.assertEqual(request.state, "pending")
        self.assertEqual(self._row(request, self.approver_2).state, "refused")
        self.assertEqual(self._row(request, self.approver_1).state, "pending")
        request.with_user(self.approver_1).action_approve()
        self.assertEqual(request.state, "approved")

    def test_a_blocking_refusal_still_refuses(self):
        _category, request = self._blocking_and_advisory()

        request.with_user(self.approver_1).with_context(
            skip_wizard=True
        ).action_refuse()

        self.assertEqual(request.state, "refused")

    def test_an_advisory_step_nobody_can_answer_does_not_block_confirmation(self):
        category = self._category()
        self._step(category, 10, self.approver_1)
        partner_model = self.env["ir.model"]._get("res.partner")
        self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": "Advice from the partner's salesperson",
                "sequence": 20,
                "minimum": 1,
                "advisory": True,
                "subject_model_id": partner_model.id,
                "subject_user_path": "user_id",
            }
        )
        partner = self.env["res.partner"].create({"name": f"Nobody's {self.id()}"})

        request = self._prepare_request(
            category, res_model="res.partner", res_id=partner.id
        )

        self.assertEqual(request.state, "pending")

    def _two_blocking_around_advisory(self):
        category = self._category()
        self._step(category, 10, self.approver_1)
        self._step(category, 15, self.approver_2, advisory=True)
        self._step(category, 20, self.manager_user)
        return (
            self.env["approval.test.synced.document"]
            .with_user(self.owner_user)
            .sudo()
            .create(
                {
                    "name": f"Advised {self.id()}",
                    "test_category_id": category.id,
                    "state": "submitted",
                }
            )
        )

    def test_an_advisory_decision_reports_no_progress(self):
        document = self._two_blocking_around_advisory()
        request = document.approval_request_id

        request.with_user(self.approver_2).action_approve()
        self.assertEqual(document.applied_outcomes, "")

        request.with_user(self.approver_1).action_approve()
        self.assertEqual(document.applied_outcomes, "progress;")

    def test_a_blocking_approval_reports_progress_while_advice_is_pending(self):
        document = self._two_blocking_around_advisory()
        request = document.approval_request_id

        request.with_user(self.approver_1).action_approve()

        self.assertEqual(request.state, "pending")
        self.assertEqual(document.applied_outcomes, "progress;")

    def test_advisory_approvers_are_asked_beside_the_open_step(self):
        category = self._category(notify_sequentially=True)
        self._step(category, 10, self.approver_1)
        self._step(category, 30, self.approver_2, advisory=True)
        self._step(category, 20, self.manager_user)

        request = self._prepare_request(category)

        asked = request._get_approval_activities().user_id
        self.assertEqual(asked, self.approver_1 | self.approver_2)
