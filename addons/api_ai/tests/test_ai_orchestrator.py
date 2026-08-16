from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.api_ai.tools.ai_orchestrator import AIOrchestrator, is_retryable
from odoo.addons.api_transport.tools.exceptions import (
    AuthenticationError,
    ClientError,
    CommError,
    CommTimeoutError,
    RateLimitError,
    ServerError,
    ValidationError,
)


class _FakeClient:
    pass


@tagged("post_install", "-at_install")
class TestRetryClassification(TransactionCase):
    def test_permanent_failures_are_not_retryable(self):
        for exc in (
            AuthenticationError("401"),
            ClientError("400 bad request"),
            ValidationError("schema mismatch"),
        ):
            self.assertFalse(is_retryable(exc), f"{type(exc).__name__} must not retry")

    def test_transient_failures_are_retryable(self):
        for exc in (
            ServerError("503"),
            CommTimeoutError("timed out"),
            RateLimitError("429"),
            CommError("something generic"),
        ):
            self.assertTrue(is_retryable(exc), f"{type(exc).__name__} must retry")

    def test_unknown_exceptions_stay_retryable(self):
        self.assertTrue(is_retryable(RuntimeError("who knows")))


@tagged("post_install", "-at_install")
class TestExecuteWithFallback(TransactionCase):
    def setUp(self):
        super().setUp()
        self.models = self.env["ai.model"].search([("kind", "=", "chat")], limit=4)
        if len(self.models) < 3:
            self.skipTest("need at least 3 seeded chat models")
        self.primary = self.models[0]
        self.rest = self.models[1:]
        self.primary.fallback_model_ids = [(6, 0, self.rest.ids)]
        self.orch = AIOrchestrator(self.env)

    def _run(self, raiser, use_assert_raises=True):
        attempted = []

        def recording(client, ai_model):
            attempted.append(ai_model.code)
            return raiser(client, ai_model)

        with patch.object(
            AIOrchestrator,
            "_get_client",
            side_effect=lambda p, company_id=None: _FakeClient(),
        ):
            if use_assert_raises:
                with self.assertRaises(CommError):
                    self.orch.execute_with_fallback(self.primary, recording)
            else:
                raised = None
                try:
                    self.orch.execute_with_fallback(self.primary, recording)
                except CommError as exc:
                    raised = exc
                self.assertIsNotNone(raised, "the chain should have raised CommError")
        return attempted

    def test_auth_error_stops_at_the_first_provider(self):
        attempted = self._run(
            lambda client, provider: (_ for _ in ()).throw(
                AuthenticationError("401 Unauthorized: invalid x-api-key")
            )
        )
        self.assertEqual(
            attempted,
            [self.primary.code],
            "a bad credential for one provider must not be asked of the others",
        )

    def test_client_error_stops_at_the_first_provider(self):
        attempted = self._run(
            lambda client, provider: (_ for _ in ()).throw(ClientError("400"))
        )
        self.assertEqual(attempted, [self.primary.code])

    def test_server_error_walks_the_whole_chain(self):
        attempted = self._run(
            lambda client, provider: (_ for _ in ()).throw(ServerError("503"))
        )
        self.assertEqual(len(attempted), len(self.models))

    def test_rate_limit_walks_the_chain(self):
        attempted = self._run(
            lambda client, provider: (_ for _ in ()).throw(RateLimitError("429"))
        )
        self.assertEqual(len(attempted), len(self.models))

    def test_a_non_retryable_failure_fabricates_no_exchange(self):
        model = self.env["api.event.log"]
        before = model.search([("direction", "=", "outbound")]).ids
        attempted = self._run(
            lambda client, provider: (_ for _ in ()).throw(AuthenticationError("401")),
            use_assert_raises=False,
        )
        self.env.flush_all()
        self.env.cr.precommit.run()

        self.assertEqual(attempted, [self.primary.code], "the chain must stop")
        written = model.search([("direction", "=", "outbound")]).filtered(
            lambda log: log.id not in before
        )
        self.assertFalse(
            written,
            f"nothing reached the wire, so nothing may claim an exchange; got "
            f"{written.mapped('tags')}",
        )

    def test_a_retryable_failure_walks_the_chain_without_inventing_rows(self):
        model = self.env["api.event.log"]
        before = model.search([("direction", "=", "outbound")]).ids
        attempted = self._run(
            lambda client, provider: (_ for _ in ()).throw(ServerError("503")),
            use_assert_raises=False,
        )
        self.env.flush_all()
        self.env.cr.precommit.run()

        self.assertEqual(len(attempted), len(self.models), "every hop is tried")
        written = model.search([("direction", "=", "outbound")]).filtered(
            lambda log: log.id not in before
        )
        self.assertFalse(written, "a fake client exchanges nothing")

    def test_success_on_a_fallback_returns_its_result(self):
        def fail_then_succeed(client, ai_model):
            if ai_model == self.primary:
                raise ServerError("503")
            return {"ok": ai_model.code}

        seen = self._run_ok(fail_then_succeed)
        self.assertEqual(seen, [self.primary.code, self.rest[0].code])
        self.assertEqual(self.result, {"ok": self.rest[0].code})

    def test_success_on_the_primary_asks_nobody_else(self):
        seen = self._run_ok(lambda client, ai_model: "done")
        self.assertEqual(seen, [self.primary.code])
        self.assertEqual(self.result, "done")

    def test_a_hop_may_stay_on_the_same_provider(self):
        sibling = self.env["ai.model"].create(
            {
                "provider_id": self.primary.provider_id.id,
                "name": f"{self.primary.name} (cheap)",
                "code": f"{self.primary.code}-cheap",
            }
        )
        self.primary.fallback_model_ids = [(6, 0, sibling.ids)]

        def fail_then_succeed(client, ai_model):
            if ai_model == self.primary:
                raise ServerError("503")
            return "recovered"

        seen = self._run_ok(fail_then_succeed)
        self.assertEqual(seen, [self.primary.code, sibling.code])
        self.assertEqual(
            sibling.provider_id,
            self.primary.provider_id,
            "the fallback ran on the key the primary already used",
        )

    def _run_ok(self, request_func):
        seen = []

        def recording(client, ai_model):
            seen.append(ai_model.code)
            return request_func(client, ai_model)

        with patch.object(
            AIOrchestrator,
            "_get_client",
            side_effect=lambda p, company_id=None: _FakeClient(),
        ):
            self.result = self.orch.execute_with_fallback(self.primary, recording)
        return seen


@tagged("post_install", "-at_install")
class TestOptimizeSelection(TransactionCase):
    def setUp(self):
        super().setUp()
        self.orch = AIOrchestrator(self.env)
        self.providers = self.env["ai.provider"].search([], limit=3)
        if len(self.providers) < 3:
            self.skipTest("need at least 3 seeded providers")
        self.cheap, self.accurate, self.fast = (
            self.providers[0],
            self.providers[1],
            self.providers[2],
        )
        self.providers.write({"has_free_tier": False})
        self.cheap.default_model_id.write(
            {"cost_per_1m_input": 0.10, "accuracy_rating": "2", "speed_rating": "2"}
        )
        self.accurate.default_model_id.write(
            {"cost_per_1m_input": 30.0, "accuracy_rating": "5", "speed_rating": "2"}
        )
        self.fast.default_model_id.write(
            {"cost_per_1m_input": 5.0, "accuracy_rating": "3", "speed_rating": "5"}
        )

    def test_cost_picks_the_cheapest(self):
        self.assertEqual(
            self.orch._optimize_selection(self.providers, "cost"), self.cheap
        )

    def test_cost_prefers_a_free_tier(self):
        self.accurate.has_free_tier = True
        try:
            chosen = self.orch._optimize_selection(self.providers, "cost")
            self.assertEqual(chosen, self.accurate)
        finally:
            self.accurate.has_free_tier = False

    def test_accuracy_picks_the_highest_rated(self):
        self.assertEqual(
            self.orch._optimize_selection(self.providers, "accuracy"), self.accurate
        )

    def test_speed_picks_the_fastest(self):
        self.assertEqual(
            self.orch._optimize_selection(self.providers, "speed"), self.fast
        )

    def test_balanced_returns_one_of_the_candidates(self):
        chosen = self.orch._optimize_selection(self.providers, "balanced")
        self.assertIn(chosen, self.providers)

    def test_unknown_strategy_falls_back_to_the_first(self):
        chosen = self.orch._optimize_selection(self.providers, "no-such-strategy")
        self.assertEqual(chosen, self.providers[0])

    def test_empty_recordset_returns_empty(self):
        empty = self.env["ai.provider"].browse()
        self.assertFalse(self.orch._optimize_selection(empty, "cost"))
