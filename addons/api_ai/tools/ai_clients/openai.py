import logging

from .openai_compatible import OpenAICompatibleClient
from odoo.addons.api_transport.tools.exceptions import CommError

_logger = logging.getLogger(__name__)


class OpenAIClient(OpenAICompatibleClient):
    ENDPOINT_CODE = "openai"

    VALID_MODELS = [
        "gpt-5.1",
        "gpt-5.1-instant",
        "gpt-5.1-thinking",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
        "o3",
        "o4-mini",
        "o1",
        "o1-mini",
        "o1-preview",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
    ]

    MAX_TEMPERATURE = 2.0
    MIN_TEMPERATURE = 0.0
    MAX_TOKENS_LIMIT = 16384

    def streaming_completion(self, messages, model=None, **kwargs):
        model = self._resolve_model(model)
        try:
            self._validate_params(model=model, temperature=kwargs.get("temperature"))

            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                **kwargs,
            }

            _logger.debug(
                "OpenAI streaming completion request: model=%s, messages=%s",
                model,
                len(messages),
            )
            response = self._client.post(
                "/chat/completions", json=payload, stream=True, raw=True
            )

            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    decoded = line.decode("utf-8")
                except UnicodeDecodeError as e:
                    _logger.warning(
                        "Failed to decode streaming chunk: %s. Skipping.",
                        e,
                    )
                    continue
                yield decoded

        except CommError:
            raise
        except Exception as e:
            _logger.exception("Unexpected error in OpenAI streaming_completion")
            raise CommError(f"OpenAI streaming completion failed: {e!s}") from e


def get_openai_client(env, company_id=None):
    return OpenAIClient(env, company_id)
