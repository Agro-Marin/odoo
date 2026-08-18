"""The gate records its own verdict — ADR-0037.

Before this, `_check_inbound_request` answered `(allowed, status, reason)` and
both callers threw the reason into a log line. `base_automation`'s controller
returned a JSON error and wrote nothing; `api_transport`'s returned the refusal
one step *before* it opened its `api.event.log` row. So a refused request was
recorded nowhere, in either mechanism, and "who is failing authentication
against us" had no answer in any store.

Two of these tests carry the decision rather than the mechanism:

* successes are NOT recorded unless the record opts in, because a row per
  admission repeats a mistake this stack already measured — routing
  `check_inbound_auth` through `authenticate_request` turned a fleet reporting
  once per position fix into six-figure daily audit volume;
* caller-rate-limit refusals COLLAPSE into one row per window, because an
  attacker chooses how many refusals to generate and a log that fills the disk
  under attack is not a control.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

_GATE = "odoo.addons.credential.models.mixins.inbound_gate_mixin"


@tagged("post_install", "-at_install")
class TestInboundAccessLog(TransactionCase):
    """Driven through `base.automation`.

    It is the concrete gate implementer that had NO structured record of a
    refusal at all — `api.endpoint.inbound` is an AbstractModel with no table,
    and its concrete implementers live in a sibling repo. So this exercises the
    half of the finding that was worst, in the module that owns the receiver.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.logs = cls.env["inbound.access.log"].sudo()
        cls.model_id = cls.env.ref("base.model_res_partner").id

    def _endpoint(self, code, **vals):
        return self.env["base.automation"].create(
            {
                "name": code,
                "model_id": self.model_id,
                "trigger": "on_webhook",
                "auth_type": "bearer",
                **vals,
            }
        )

    def _rows(self, endpoint):
        return self.logs.search(
            [("gate_model", "=", endpoint._name), ("gate_id", "=", endpoint.id)]
        )

    # ------------------------------------------------------------------
    # The gap this closes
    # ------------------------------------------------------------------

    def test_a_refusal_is_recorded(self):
        endpoint = self._endpoint("gate_refused")

        allowed, status, _reason = endpoint._check_inbound_request(
            {"Authorization": "Bearer wrong"}, remote_addr="203.0.113.7"
        )

        self.assertFalse(allowed)
        row = self._rows(endpoint)
        self.assertEqual(len(row), 1)
        self.assertFalse(row.allowed)
        self.assertEqual(row.outcome, "unauthenticated")
        self.assertEqual(row.status_code, status)
        self.assertEqual(row.source_ip, "203.0.113.7")
        self.assertEqual(row.attempt_count, 1)

    def test_the_row_survives_the_endpoint(self):
        """An audit trail is read exactly when the record is gone."""
        endpoint = self._endpoint("gate_deleted")
        endpoint._check_inbound_request({}, remote_addr="203.0.113.8")
        row = self._rows(endpoint)
        self.assertEqual(row.gate_name, endpoint.display_name)

        endpoint.unlink()
        row.invalidate_recordset()
        self.assertTrue(row.exists())
        self.assertTrue(row.gate_name, "the snapshot is what makes it readable")

    def test_two_different_bad_tokens_are_two_facts(self):
        endpoint = self._endpoint("gate_two_tokens")
        endpoint._check_inbound_request(
            {"Authorization": "Bearer one"}, remote_addr="203.0.113.9"
        )
        endpoint._check_inbound_request(
            {"Authorization": "Bearer two"}, remote_addr="203.0.113.9"
        )
        self.assertEqual(len(self._rows(endpoint)), 2)

    # ------------------------------------------------------------------
    # Successes are opt-in — the volume decision
    # ------------------------------------------------------------------

    def test_an_admitted_request_is_not_recorded_by_default(self):
        endpoint = self._endpoint("gate_quiet", auth_type="none")

        allowed, _status, _reason = endpoint._check_inbound_request({})

        self.assertTrue(allowed)
        self.assertFalse(
            self._rows(endpoint),
            "a row per successful admission is what the GPS fleet measurement "
            "ruled out",
        )

    def test_an_admitted_request_is_recorded_when_asked_for(self):
        endpoint = self._endpoint(
            "gate_loud", auth_type="none", log_inbound_access=True
        )

        endpoint._check_inbound_request({})

        row = self._rows(endpoint)
        self.assertEqual(len(row), 1)
        self.assertTrue(row.allowed)
        self.assertEqual(row.outcome, "allowed")

    def test_a_gate_that_is_off_records_nothing(self):
        """`off` means no decision was made; recording one would be a lie."""
        endpoint = self._endpoint("gate_off", log_inbound_access=True)

        endpoint._check_inbound_request({}, mode=endpoint.AUTH_MODE_OFF)

        self.assertFalse(self._rows(endpoint))

    @mute_logger(_GATE)
    def test_audit_mode_records_what_it_let_through(self):
        """The one success worth recording whether or not anyone asked.

        Audit mode admits an unauthenticated request on purpose. That is the
        state an operator most needs a list of, and it is not `allowed`.
        """
        endpoint = self._endpoint("gate_audit")

        allowed, _status, _reason = endpoint._check_inbound_request(
            {}, mode=endpoint.AUTH_MODE_AUDIT
        )

        self.assertTrue(allowed)
        row = self._rows(endpoint)
        self.assertEqual(len(row), 1)
        self.assertEqual(row.outcome, "audit_accepted")

    # ------------------------------------------------------------------
    # The collapse — the other half of the decision
    # ------------------------------------------------------------------

    def test_repeated_caller_limit_refusals_collapse(self):
        endpoint = self._endpoint("gate_flood")

        with patch.object(
            type(endpoint),
            "_check_inbound_caller",
            return_value=(False, 429, "caller rate limit"),
        ):
            for _ in range(25):
                endpoint._check_inbound_request({}, remote_addr="198.51.100.4")

        rows = self._rows(endpoint)
        self.assertEqual(len(rows), 1, "25 refusals must not be 25 rows")
        self.assertEqual(rows.attempt_count, 25)
        self.assertGreaterEqual(rows.last_seen_at, rows.timestamp)

    def test_the_collapse_is_per_caller(self):
        endpoint = self._endpoint("gate_flood_two")

        with patch.object(
            type(endpoint),
            "_check_inbound_caller",
            return_value=(False, 429, "caller rate limit"),
        ):
            for address in ("198.51.100.5", "198.51.100.6", "198.51.100.5"):
                endpoint._check_inbound_request({}, remote_addr=address)

        rows = self._rows(endpoint)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(rows.mapped("attempt_count")), [1, 2])

    @mute_logger(_GATE)
    def test_a_distinguishable_refusal_does_not_collapse(self):
        """Two bad tokens from one address are two events, not one repeated."""
        endpoint = self._endpoint("gate_no_collapse")

        for _ in range(3):
            endpoint._check_inbound_request(
                {"Authorization": "Bearer nope"}, remote_addr="198.51.100.7"
            )

        self.assertEqual(len(self._rows(endpoint)), 3)

    @mute_logger(_GATE)
    def test_repeated_audit_admissions_collapse(self):
        """Audit mode reports a standing configuration state -- the credential
        is not provisioned -- not a per-request event. A fleet reporting once
        per position fix wrote one row and two warnings per fix for it."""
        endpoint = self._endpoint("gate_audit_flood")

        for _ in range(40):
            endpoint._check_inbound_request(
                {}, remote_addr="198.51.100.8", mode=endpoint.AUTH_MODE_AUDIT
            )

        rows = self._rows(endpoint)
        self.assertEqual(len(rows), 1, "40 fixes past one unprovisioned gate")

    @mute_logger(_GATE)
    def test_the_audit_collapse_is_per_gate_not_per_caller(self):
        """The caller-rate-limit collapse is keyed by address because which
        address is being refused is the fact. This one is not: the fact is
        that the gate has no credential, and a sender behind a rotating
        egress pool would otherwise open a row per request."""
        endpoint = self._endpoint("gate_audit_rotating_pool")

        for address in ("198.51.100.9", "198.51.100.10", "198.51.100.11"):
            endpoint._check_inbound_request(
                {}, remote_addr=address, mode=endpoint.AUTH_MODE_AUDIT
            )

        rows = self._rows(endpoint)
        self.assertEqual(len(rows), 1, "three addresses, one unprovisioned gate")
        self.assertEqual(rows.source_ip, "198.51.100.9", "the first one seen")

    @mute_logger(_GATE)
    def test_two_gates_in_audit_mode_are_two_conditions(self):
        one = self._endpoint("gate_audit_one")
        two = self._endpoint("gate_audit_two")

        for endpoint in (one, two, one):
            endpoint._check_inbound_request(
                {}, remote_addr="198.51.100.12", mode=endpoint.AUTH_MODE_AUDIT
            )

        self.assertEqual(len(self._rows(one)), 1)
        self.assertEqual(len(self._rows(two)), 1)

    @mute_logger(_GATE)
    def test_the_audit_collapse_never_writes_the_standing_row(self):
        """The guard on the whole design, and the reason the row is not
        counted. Counting means an UPDATE of a row every concurrent request
        shares; under the REPEATABLE READ every Odoo cursor runs at, two
        requests updating one row conflict whatever columns they touch, and
        serialising them does not help. Counting the audit row put a
        serialisation failure back on this deployment's GPS ingest within
        seconds of deploying it."""
        endpoint = self._endpoint("gate_audit_no_write")
        endpoint._check_inbound_request(
            {}, remote_addr="198.51.100.20", mode=endpoint.AUTH_MODE_AUDIT
        )
        row = self._rows(endpoint)
        self.assertEqual(len(row), 1)

        with patch.object(type(row), "write", autospec=True) as write:
            for _ in range(20):
                endpoint._check_inbound_request(
                    {}, remote_addr="198.51.100.20", mode=endpoint.AUTH_MODE_AUDIT
                )

        write.assert_not_called()
        self.assertEqual(len(self._rows(endpoint)), 1)

    def test_a_bad_token_refusal_is_recorded_but_not_logged(self):
        """It is recorded because that is the gap ADR-0037 closed, and not
        logged because the caller chooses how many to send: a line per
        refused token is a flood an attacker controls."""
        endpoint = self._endpoint("gate_quiet_refusal")

        with self.assertNoLogs(_GATE, "WARNING"):
            endpoint._check_inbound_request(
                {"Authorization": "Bearer nope"}, remote_addr="198.51.100.21"
            )

        self.assertEqual(self._rows(endpoint).outcome, "unauthenticated")

    @mute_logger(_GATE)
    def test_the_audit_row_records_why_it_was_unauthenticated(self):
        """A trail of admissions that does not say what was missing cannot be
        acted on: every one of them reads the same."""
        endpoint = self._endpoint("gate_audit_reason")

        endpoint._check_inbound_request(
            {}, remote_addr="198.51.100.11", mode=endpoint.AUTH_MODE_AUDIT
        )

        row = self._rows(endpoint)
        self.assertTrue(row.reason)
        self.assertIn("No credential configured", row.reason)

    # ------------------------------------------------------------------
    # The log line follows the record — one condition, one report
    # ------------------------------------------------------------------

    def test_a_standing_audit_condition_is_reported_once(self):
        endpoint = self._endpoint("gate_audit_quiet")

        with self.assertLogs(_GATE, "WARNING") as logs:
            for n in range(30):
                endpoint._check_inbound_request(
                    {},
                    remote_addr=f"198.51.100.{n + 100}",
                    mode=endpoint.AUTH_MODE_AUDIT,
                )

        self.assertEqual(
            len(logs.output), 1, "one unprovisioned gate is one thing to say"
        )
        self.assertIn("UNAUTHENTICATED request accepted", logs.output[0])

    def test_an_enforced_refusal_is_recorded_not_logged(self):
        """The reason used to be logged where it was raised, per request, and
        in audit mode re-stated by the caller that received it -- so a fleet
        past an unprovisioned gate printed it twice per position fix. The row
        is where a refusal belongs."""
        endpoint = self._endpoint("gate_single_line")

        with self.assertNoLogs(_GATE, "WARNING"):
            endpoint._check_inbound_request({}, remote_addr="198.51.100.13")

        self.assertTrue(self._rows(endpoint).reason)

    # ------------------------------------------------------------------
    # The record must not be able to break the request
    # ------------------------------------------------------------------

    @mute_logger(_GATE)
    def test_a_failure_to_record_does_not_change_the_verdict(self):
        """A trail that can refuse a request by failing to write is worse than
        one that misses a row."""
        endpoint = self._endpoint("gate_log_broken")

        with patch.object(
            type(endpoint),
            "_store_inbound_verdict",
            side_effect=RuntimeError("table is gone"),
        ):
            allowed, status, _reason = endpoint._check_inbound_request(
                {"Authorization": "Bearer wrong"}, remote_addr="203.0.113.10"
            )

        self.assertFalse(allowed)
        self.assertEqual(status, 401)

    # ------------------------------------------------------------------
    # Write-once
    # ------------------------------------------------------------------

    def test_the_row_cannot_be_edited(self):
        endpoint = self._endpoint("gate_immutable")
        endpoint._check_inbound_request({}, remote_addr="203.0.113.11")
        row = self._rows(endpoint)

        with self.assertRaises(UserError):
            row.write({"reason": "something else"})
        with self.assertRaises(UserError):
            row.unlink()

    def test_the_retention_cron_may_delete(self):
        endpoint = self._endpoint("gate_retention")
        endpoint._check_inbound_request({}, remote_addr="203.0.113.12")
        self.assertTrue(self._rows(endpoint))

        # -1 rather than 0: the transaction clock is frozen, so the row's
        # timestamp and a cutoff of `now` are the same instant and `<` is false.
        # The cron is being exercised, not the arithmetic of a real retention.
        self.logs.cron_gc_inbound_access_logs(retention_days=-1)

        self.assertFalse(self._rows(endpoint))


@tagged("post_install", "-at_install")
class TestInboundRateLimitScope(TransactionCase):
    """The inbound quota belongs to the endpoint, not to the acting company.

    `rate.limit.bucket` keys on `model:id:company`, so whatever is passed as the
    company IS part of the bucket's identity: a second value is a second bucket
    with its own full allowance. The gate used to pass `env.company.id`, which is
    ambient request state — every inbound controller runs `sudo()`, so it
    described whoever happened to be acting rather than the endpoint being
    protected. Anything putting a company in the context (an authenticated call
    carrying `allowed_company_ids`, a `with_company()` inside a subclass's
    `_process_queued_event`, async replay through `delayed()`) therefore handed
    the caller a fresh bucket, and the limit here is a security control.

    It now passes `_inbound_company_id()` — the endpoint's own company, the same
    value the gate already stamps on its audit row.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_id = cls.env.ref("base.model_res_partner").id
        cls.company_a = cls.env["res.company"].create({"name": "Gate Scope A"})
        cls.company_b = cls.env["res.company"].create({"name": "Gate Scope B"})
        cls.buckets = cls.env["rate.limit.bucket"].sudo()

    def _endpoint(self, code, allowed):
        return self.env["base.automation"].create(
            {
                "name": code,
                "model_id": self.model_id,
                "trigger": "on_webhook",
                "auth_type": "none",
                "rate_limit_enabled": True,
                "rate_limit_requests": allowed,
            }
        )

    def _keys(self, endpoint):
        return self.buckets.search(
            [
                ("endpoint_model", "=", endpoint._name),
                ("endpoint_id", "=", endpoint.id),
            ]
        ).mapped("bucket_key")

    def test_switching_company_does_not_buy_a_fresh_allowance(self):
        endpoint = self._endpoint("gate_scope_bypass", allowed=2)

        self.assertTrue(endpoint.with_company(self.company_a)._consume_rate_limit())
        self.assertTrue(endpoint.with_company(self.company_a)._consume_rate_limit())
        self.assertFalse(
            endpoint.with_company(self.company_a)._consume_rate_limit(),
            "the endpoint's own allowance is spent",
        )

        self.assertFalse(
            endpoint.with_company(self.company_b)._consume_rate_limit(),
            "a different active company must NOT reset the endpoint's quota",
        )

    def test_one_endpoint_keeps_one_bucket_across_companies(self):
        endpoint = self._endpoint("gate_scope_single", allowed=5)

        endpoint.with_company(self.company_a)._consume_rate_limit()
        endpoint.with_company(self.company_b)._consume_rate_limit()

        self.assertEqual(
            self._keys(endpoint),
            [f"base.automation:{endpoint.id}:global"],
            "base.automation carries no company_id, so the endpoint is unscoped "
            "and must hold exactly one bucket whatever company is active",
        )
