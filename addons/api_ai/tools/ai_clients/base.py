import logging

from ..json_payload import parse_json_response
from odoo.addons.api_transport.tools.api_client import get_api_client

_logger = logging.getLogger(__name__)

_JSON_INSTRUCTION = "\n\nReturn your response as valid JSON."


class BaseAIClient:
    ENDPOINT_CODE = None

    FALLBACK_MODEL = None

    VALID_MODELS = ()

    _default_model = None

    MIN_TEMPERATURE = 0.0
    MAX_TEMPERATURE = 1.0
    MAX_TOKENS_LIMIT = 8192

    def __init__(self, env, company_id=None):
        if not self.ENDPOINT_CODE:
            raise NotImplementedError(
                f"{type(self).__name__} must declare ENDPOINT_CODE",
            )
        self.env = env
        self.company_id = company_id
        self._default_model = None
        self._client = get_api_client(env, self.ENDPOINT_CODE, company_id)

    def simple_completion(self, prompt, model=None, **kwargs):
        raise NotImplementedError(
            f"{type(self).__name__} must implement simple_completion",
        )

    def json_completion(self, prompt, model=None, **kwargs):
        if "json" not in prompt.lower():
            prompt = f"{prompt}{_JSON_INSTRUCTION}"
        text = self.simple_completion(prompt, model=model, **kwargs)
        return parse_json_response(text, env=self.env)

    def _resolve_model(self, model=None):
        if model:
            return model

        configured = self._provider_default_model()
        if configured:
            return configured

        return self._catalog_default_model() or self.FALLBACK_MODEL

    def _catalog_default_model(self):
        spec = self._catalog_spec()
        return spec.get("chat_model") if spec else None

    def _catalog_spec(self):
        from ..vendor_catalog import PROVIDERS

        for spec in PROVIDERS.values():
            if spec.get("chat_service") == self.ENDPOINT_CODE:
                return spec
        return None

    def _provider_default_model(self):
        if self._default_model is not None:
            return self._default_model

        provider_model = self.env.get("ai.provider")
        if provider_model is None:
            self._default_model = ""
            return self._default_model

        provider = provider_model.sudo().search(
            [("endpoint_id.code", "=", self.ENDPOINT_CODE)],
            limit=1,
        )
        self._default_model = provider.default_model_id.code or ""
        return self._default_model

    def _validate_params(self, model=None, temperature=None, max_tokens=None):
        if model is not None and self.VALID_MODELS and model not in self.VALID_MODELS:
            _logger.warning(
                "Model %r is not in %s's known models %s. Sending it anyway; "
                "the API will reject it if it does not exist.",
                model,
                type(self).__name__,
                list(self.VALID_MODELS),
            )

        if temperature is not None:
            if not isinstance(temperature, (int, float)) or isinstance(
                temperature, bool
            ):
                raise ValueError(
                    f"Temperature must be numeric, got {type(temperature).__name__}",
                )
            if not (self.MIN_TEMPERATURE <= temperature <= self.MAX_TEMPERATURE):
                raise ValueError(
                    f"Temperature must be between {self.MIN_TEMPERATURE} and "
                    f"{self.MAX_TEMPERATURE}, got {temperature}",
                )

        if max_tokens is not None:
            if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
                raise ValueError(
                    f"max_tokens must be a positive integer, got {max_tokens!r}",
                )
            if max_tokens <= 0:
                raise ValueError(
                    f"max_tokens must be a positive integer, got {max_tokens}",
                )
            if max_tokens > self.MAX_TOKENS_LIMIT:
                _logger.warning(
                    "max_tokens (%s) exceeds %s's recommended limit (%s). This may "
                    "cause API errors or high costs.",
                    max_tokens,
                    type(self).__name__,
                    self.MAX_TOKENS_LIMIT,
                )
