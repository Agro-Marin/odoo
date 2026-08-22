from odoo.tests import TransactionCase, tagged

INBOUND_ONLY_FIELDS = (
    "signature_header",
    "signature_prefix",
    "verification_method",
    "ip_whitelist",
    "max_payload_size",
    "timestamp_verification_enabled",
    "timestamp_header",
    "timestamp_max_age_seconds",
    "rate_limit_window_seconds",
)

IDENTITY_FIELDS = ("credential_id", "auth_type", "credential_fingerprint")

SHARED_ADMISSION_FIELDS = (
    "rate_limit_enabled",
    "rate_limit_requests",
    "rate_limit_strict",
)

FORBIDDEN_ON_THE_GATE = (
    "name",
    "active",
    "company_id",
    "sequence",
    "code",
    "description",
    "retry_enabled",
    "retry_max_attempts",
    "retry_initial_delay",
    "retry_backoff_type",
    "date_last_activity",
    "duplicate_detection_enabled",
    "duplicate_window_seconds",
    "processing_mode",
    "event_log_ids",
    "event_count",
)


@tagged("post_install", "-at_install")
class TestGateMixinBoundary(TransactionCase):
    def test_the_gate_exists_and_inbound_inherits_it(self):
        self.assertIn("inbound.gate.mixin", self.env)
        self.assertIn("credential.auth.mixin", self.env)
        inbound = self.env["api.endpoint.inbound"]
        for field in (*IDENTITY_FIELDS, *INBOUND_ONLY_FIELDS):
            self.assertIn(field, inbound._fields, field)

    def test_the_gate_carries_only_identity_and_admission(self):
        gate_fields = set(self.env["inbound.gate.mixin"]._fields)
        leaked = sorted(set(FORBIDDEN_ON_THE_GATE) & gate_fields)
        self.assertFalse(
            leaked,
            f"the gate acquired {leaked}, which is channel bookkeeping or "
            f"dispatch. ADR-0017 accepts a shared mixin only because it carries "
            f"neither; widening it here retroactively vindicates the objection "
            f"the record overruled.",
        )

    def test_outbound_endpoints_do_not_carry_admission_controls(self):
        outbound_fields = set(self.env["api.endpoint.outbound"]._fields)
        leaked = sorted(set(INBOUND_ONLY_FIELDS) & outbound_fields)
        self.assertFalse(
            leaked,
            f"api.endpoint.outbound acquired {leaked}. An outbound endpoint is "
            f"the caller: it has no allowlist to enforce, no replay window and "
            f"no payload to cap. This is what `api.channel.mixin` inheriting "
            f"the gate instead of `credential.auth.mixin` would look like.",
        )

    def test_admission_is_declared_once_on_the_shared_ancestor(self):
        ancestor = set(self.env["credential.auth.mixin"]._fields)
        for field in SHARED_ADMISSION_FIELDS:
            self.assertIn(
                field,
                ancestor,
                f"{field} is spent by an inbound gate and an outbound caller "
                f"alike, so it belongs on credential.auth.mixin. Declaring it on "
                f"both mixins is what it looked like before, and api.endpoint."
                f"inbound inherited both copies.",
            )

    def test_rate_limiting_has_one_spelling(self):
        for model in ("api.endpoint.inbound", "api.endpoint.outbound"):
            self.assertTrue(
                hasattr(self.env[model], "check_rate_limit"),
                f"{model} lost check_rate_limit",
            )
            self.assertFalse(
                hasattr(self.env[model], "_consume_rate_limit"),
                f"{model} carries a second name for spending a rate-limit token. "
                f"There were two identical implementations, and on an inbound "
                f"endpoint -- which inherits both mixins -- one of them was dead.",
            )

    def test_inbound_refuses_a_bucket_it_cannot_read_and_outbound_does_not(self):
        self.assertTrue(
            self.env["api.endpoint.inbound"]
            .default_get(["rate_limit_strict"])
            .get("rate_limit_strict"),
            "inbound strictness is a security control and must survive the move "
            "of the field onto the shared ancestor, which defaults it to False",
        )

    def test_outbound_endpoints_still_carry_identity(self):
        outbound_fields = set(self.env["api.endpoint.outbound"]._fields)
        for field in IDENTITY_FIELDS:
            self.assertIn(
                field,
                outbound_fields,
                f"{field} is identity, which both directions need — it belongs "
                f"on credential.auth.mixin, not on the gate",
            )


@tagged("post_install", "-at_install")
class TestGateDelegation(TransactionCase):
    def _endpoint(self, **vals):
        return self.env["api.endpoint.outbound"].create(
            {
                "name": "delegation probe",
                "code": "delegation_probe",
                "endpoint_url": "https://example.invalid/api",
                "auth_type": "bearer",
                **vals,
            }
        )

    def test_the_window_drives_the_bucket(self):
        inbound = self.env["api.endpoint.inbound"]
        self.assertIn("rate_limit_window_seconds", inbound._fields)
        self.assertIn(
            "rate_limit_period",
            self.env["api.endpoint.outbound"]._fields,
            "the outbound Selection is deliberately untouched",
        )

    def test_inbound_carries_one_spelling_of_the_window(self):
        self.assertNotIn(
            "rate_limit_period",
            self.env["api.endpoint.inbound"]._fields,
            "an inbound endpoint carrying both spellings makes the Selection "
            "dead configuration: rate_limit_window_seconds defaults to 60 and "
            "always wins in rate.limit.bucket._get_endpoint_config, so a "
            "period set here is silently ignored",
        )
        self.assertNotIn(
            "rate_limit_window_seconds",
            self.env["api.endpoint.outbound"]._fields,
            "an outbound endpoint has no admission window",
        )

    def test_strict_mode_resolves_to_the_inbound_default(self):
        defaults = self.env["api.endpoint.inbound"].default_get(["rate_limit_strict"])
        self.assertTrue(defaults.get("rate_limit_strict"))
        self.assertFalse(
            self.env["api.endpoint.outbound"]
            .default_get(["rate_limit_strict"])
            .get("rate_limit_strict")
        )
