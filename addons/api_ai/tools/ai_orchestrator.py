import logging
from datetime import datetime

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.api_transport.tools.api_client import OutboundAPIClient
from odoo.addons.api_transport.tools.exceptions import (
    AuthenticationError,
    ClientError,
    CommError,
    ValidationError,
)

_logger = logging.getLogger(__name__)

NON_RETRYABLE_ERRORS = (AuthenticationError, ClientError, ValidationError)


def is_retryable(exc):
    return not isinstance(exc, NON_RETRYABLE_ERRORS)


class AIOrchestrator:
    def __init__(self, env):
        self.env = env

    def select_provider(
        self,
        use_case_tags=None,
        required_capabilities=None,
        optimize_for="balanced",
        company_id=None,
        provider_code=None,
    ):
        if provider_code:
            provider = self.env["ai.provider"].search(
                [
                    ("code", "=", provider_code),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if provider and self._has_valid_credential(provider, company_id):
                return provider
            _logger.warning(
                "Requested provider '%s' not found or has no valid credentials",
                provider_code,
            )
            return None

        providers = self.env["ai.provider"].search(
            [
                ("active", "=", True),
            ],
        )

        if not providers:
            _logger.error("No active AI providers configured")
            return None

        if required_capabilities:
            allowed = set(self.env["ai.provider"]._fields)
            unknown = set(required_capabilities) - allowed
            if unknown:
                raise UserError(
                    _(
                        "Unknown AI capability fields: %(fields)s",
                        fields=", ".join(sorted(unknown)),
                    ),
                )
            for field, value in required_capabilities.items():
                providers = providers.filtered(
                    lambda p, field=field, value=value: p[field] == value,
                )

        if use_case_tags:
            tag_ids = (
                self.env["ai.use.case.tag"].search([("code", "in", use_case_tags)]).ids
            )
            if tag_ids:
                providers = providers.filtered(
                    lambda p: any(
                        tag_id in p.best_for_tag_ids.ids for tag_id in tag_ids
                    ),
                )

        providers_with_credentials = self.env["ai.provider"]
        for provider in providers:
            if self._has_valid_credential(provider, company_id):
                providers_with_credentials |= provider

        if not providers_with_credentials:
            _logger.warning(
                "No providers found with valid credentials for company_id=%s",
                company_id,
            )
            return None

        return self._optimize_selection(providers_with_credentials, optimize_for)

    def select_model(
        self,
        use_case_tags=None,
        required_capabilities=None,
        optimize_for="balanced",
        company_id=None,
        provider_code=None,
        kind=None,
    ):
        domain = [("active", "=", True), ("provider_id.active", "=", True)]
        if kind:
            domain.append(("kind", "=", kind))
        if provider_code:
            domain.append(("provider_id.code", "=", provider_code))

        candidates = self.env["ai.model"].search(domain)
        if not candidates:
            _logger.error("No active AI models configured for %s", domain)
            return None

        if required_capabilities:
            allowed = set(self.env["ai.model"]._fields)
            unknown = set(required_capabilities) - allowed
            if unknown:
                raise UserError(
                    _(
                        "Unknown AI capability fields: %(fields)s",
                        fields=", ".join(sorted(unknown)),
                    ),
                )
            for field, value in required_capabilities.items():
                candidates = candidates.filtered(
                    lambda m, field=field, value=value: m[field] == value,
                )

        if use_case_tags:
            tag_ids = (
                self.env["ai.use.case.tag"].search([("code", "in", use_case_tags)]).ids
            )
            if tag_ids:
                candidates = candidates.filtered(
                    lambda m: any(
                        tag_id in m.provider_id.best_for_tag_ids.ids
                        for tag_id in tag_ids
                    ),
                )

        usable = self.env["ai.model"]
        for model in candidates:
            if self._has_valid_credential(model.provider_id, company_id):
                usable |= model

        if not usable:
            _logger.warning(
                "No models found with valid credentials for company_id=%s",
                company_id,
            )
            return None

        return self._optimize_model_selection(usable, optimize_for)

    def execute_with_fallback(
        self,
        primary_model,
        request_func,
        fallback_chain=None,
        log_metadata=None,
        company_id=None,
    ):
        models_to_try = [primary_model]
        if fallback_chain:
            models_to_try.extend(fallback_chain)
        else:
            models_to_try.extend(primary_model.fallback_model_ids)

        last_error = None
        last_exception = None
        previous_model = None

        for idx, model in enumerate(models_to_try):
            is_fallback = idx > 0
            provider = model.provider_id
            try:
                _logger.info(
                    "Attempting AI request with %s on %s (fallback=%s)",
                    model.code,
                    provider.name,
                    is_fallback,
                )

                annotated = provider.with_context(
                    **{
                        OutboundAPIClient.EVENT_LOG_ANNOTATIONS_KEY: (
                            self._event_annotations(
                                model,
                                is_fallback,
                                previous_model,
                                log_metadata,
                            )
                        )
                    }
                )
                client = self._get_client(annotated, company_id)

                start_time = datetime.now()
                result = request_func(client, model)
                duration = (datetime.now() - start_time).total_seconds() * 1000

                _logger.info(
                    "AI request successful with %s on %s (%.2fms)",
                    model.code,
                    provider.name,
                    duration,
                )

                return result

            except Exception as e:
                last_error = str(e)
                last_exception = e
                previous_model = model
                retryable = is_retryable(e)
                _logger.warning(
                    "Model %s on %s failed: %s%s",
                    model.code,
                    provider.name,
                    e,
                    (
                        ". Trying fallback..."
                        if retryable and idx < len(models_to_try) - 1
                        else ". No more fallbacks."
                    ),
                )

                if not retryable:
                    _logger.warning(
                        "%s is not retryable; stopping the fallback chain at %s "
                        "instead of asking %d more model(s) the same question.",
                        type(e).__name__,
                        model.code,
                        len(models_to_try) - idx - 1,
                    )
                    break

                if idx == len(models_to_try) - 1:
                    break

                continue

        error_msg = f"All AI models failed. Last error: {last_error}"
        _logger.error(error_msg)
        raise CommError(error_msg) from last_exception

    def _has_valid_credential(self, provider, company_id=None):
        company_id = company_id or self.env.company.id

        credential = self.env["credential.credential"]._get_for_endpoint(
            provider.endpoint_id, company=company_id
        )

        return bool(credential)

    def _optimize_selection(self, providers, strategy):
        if not providers:
            return self.env["ai.provider"]

        if strategy == "cost":
            free_tier = providers.filtered(lambda p: p.has_free_tier)
            if free_tier:
                return free_tier[0]
            return providers.sorted(
                lambda p: p.default_model_id.cost_per_1m_input or float("inf")
            )[0]

        if strategy == "accuracy":
            return providers.sorted(
                lambda p: int(p.default_model_id.accuracy_rating or "0"),
                reverse=True,
            )[0]

        if strategy == "speed":
            return providers.sorted(
                lambda p: int(p.default_model_id.speed_rating or "0"),
                reverse=True,
            )[0]

        if strategy == "balanced":

            def balanced_score(provider):
                model = provider.default_model_id
                accuracy = int(model.accuracy_rating or "3")
                speed = int(model.speed_rating or "3")
                reliability = int(provider.reliability_rating or "3")

                cost = model.cost_per_1m_input or 0.1
                cost_factor = max(0.1, cost / 1.0)

                return (accuracy * 2 + speed + reliability) / cost_factor

            return providers.sorted(balanced_score, reverse=True)[0]

        _logger.warning("Unknown optimization strategy: %s", strategy)
        return providers[0]

    def _optimize_model_selection(self, ai_models, strategy):
        if not ai_models:
            return self.env["ai.model"]

        if strategy == "cost":
            free_tier = ai_models.filtered(lambda m: m.provider_id.has_free_tier)
            if free_tier:
                return free_tier[0]
            return ai_models.sorted(
                lambda m: m.cost_per_1m_input or float("inf"),
            )[0]

        if strategy == "accuracy":
            return ai_models.sorted(
                lambda m: int(m.accuracy_rating or "0"),
                reverse=True,
            )[0]

        if strategy == "speed":
            return ai_models.sorted(
                lambda m: int(m.speed_rating or "0"),
                reverse=True,
            )[0]

        if strategy == "balanced":

            def balanced_score(ai_model):
                accuracy = int(ai_model.accuracy_rating or "3")
                speed = int(ai_model.speed_rating or "3")
                reliability = int(ai_model.provider_id.reliability_rating or "3")

                cost = ai_model.cost_per_1m_input or 0.1
                cost_factor = max(0.1, cost / 1.0)

                return (accuracy * 2 + speed + reliability) / cost_factor

            return ai_models.sorted(balanced_score, reverse=True)[0]

        _logger.warning("Unknown optimization strategy: %s", strategy)
        return ai_models[0]

    def _get_client(self, provider, company_id=None):
        return provider._get_ai_client(company_id or self.env.company.id)

    _CALLER_ANNOTATIONS = ("origin_model", "origin_record_id")

    def _event_annotations(self, ai_model, was_fallback, previous_model, metadata=None):
        tags = [
            f"ai_provider:{ai_model.provider_id.code}",
            f"ai_model:{ai_model.code}",
            f"fallback:{was_fallback}",
        ]
        if was_fallback and previous_model:
            tags.append(f"after:{previous_model.code}")

        annotations = {"tags": ",".join(tags)}
        for key in self._CALLER_ANNOTATIONS:
            value = (metadata or {}).get(key)
            if value:
                annotations[key] = value
        return annotations


def get_ai_orchestrator(env):
    return AIOrchestrator(env)
